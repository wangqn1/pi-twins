# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from time import sleep
from typing import Any, Callable, Literal

from agent import Agent, AgentEvent
from ai import AssistantMessage, Model, Usage, text_block
from ai.overflow import is_context_overflow

from .compaction import (
    CompactionSettings,
    RetrySettings,
    calculate_context_tokens,
    compact as run_compaction,
    estimate_context_tokens,
    get_latest_compaction_entry,
    prepare_compaction,
    should_compact,
)
from .auth_storage import AuthStorage
from .export_html import export_session_to_html
from .model_registry import ModelRegistry
from .messages import create_custom_message
from .prompt_templates import PromptTemplate, expand_prompt_template
from .resource_loader import DefaultResourceLoader
from .share_session import export_share_bundle
from .session_manager import SessionManager
from .settings_manager import SettingsManager
from .slash_dispatcher import dispatch_slash_command
from .system_prompt import build_system_prompt

_RETRYABLE_ERROR_RE = re.compile(
    r"overloaded|rate.?limit|too many requests|429|500|502|503|504|service.?unavailable|"
    r"server error|internal error|connection.?error|connection.?refused|other side closed|"
    r"fetch failed|upstream.?connect|reset before headers|terminated|retry delay",
    re.IGNORECASE,
)


def _role(message: Any) -> str | None:
    if isinstance(message, dict):
        return message.get("role")
    return getattr(message, "role", None)


def _usage(message: Any) -> dict[str, Any] | None:
    if isinstance(message, dict):
        usage = message.get("usage")
        return usage if isinstance(usage, dict) else None
    usage = getattr(message, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "to_dict"):
        return usage.to_dict()
    if isinstance(usage, dict):
        return usage
    return None


def _assistant_stop_reason(message: Any) -> str | None:
    if isinstance(message, dict):
        return message.get("stopReason") or message.get("stop_reason")
    return getattr(message, "stop_reason", None) or getattr(message, "stopReason", None)


def _assistant_error_message(message: Any) -> str | None:
    if isinstance(message, dict):
        value = message.get("errorMessage") or message.get("error_message")
        return str(value) if value else None
    value = getattr(message, "error_message", None) or getattr(message, "errorMessage", None)
    return str(value) if value else None


def _as_assistant_message(message: Any) -> AssistantMessage | None:
    if _role(message) != "assistant":
        return None
    if isinstance(message, AssistantMessage):
        return message
    if not isinstance(message, dict):
        return None

    usage_payload = message.get("usage", {})
    usage = Usage(
        input=int(usage_payload.get("input", 0) if isinstance(usage_payload, dict) else 0),
        output=int(usage_payload.get("output", 0) if isinstance(usage_payload, dict) else 0),
        cache_read=int(usage_payload.get("cacheRead", 0) if isinstance(usage_payload, dict) else 0),
        cache_write=int(usage_payload.get("cacheWrite", 0) if isinstance(usage_payload, dict) else 0),
        total_tokens=int(usage_payload.get("totalTokens", 0) if isinstance(usage_payload, dict) else 0),
    )
    stop_reason = _assistant_stop_reason(message) or "stop"
    if stop_reason not in {"stop", "length", "toolUse", "error", "aborted"}:
        stop_reason = "stop"
    return AssistantMessage(
        content=message.get("content", []) if isinstance(message.get("content"), list) else [],
        api=str(message.get("api", "mock")),
        provider=str(message.get("provider", "mock")),
        model=str(message.get("model", "unknown")),
        usage=usage,
        stop_reason=stop_reason,
        timestamp=int(message.get("timestamp", 0) or 0),
        error_message=_assistant_error_message(message),
    )


@dataclass
class SessionStats:
    session_file: str | None
    session_id: str
    user_messages: int
    assistant_messages: int
    tool_calls: int
    tool_results: int
    total_messages: int
    tokens: dict[str, int]
    cost: float


@dataclass
class AgentSessionConfig:
    agent: Agent
    session_manager: SessionManager
    cwd: str
    settings_manager: SettingsManager | None = None
    auth_storage: AuthStorage | None = None
    model_registry: ModelRegistry | None = None
    scoped_models: list[dict[str, Any]] = field(default_factory=list)
    resource_loader: DefaultResourceLoader | None = None
    retry_settings: RetrySettings = field(default_factory=RetrySettings)
    compaction_settings: CompactionSettings = field(default_factory=CompactionSettings)
    auto_retry: bool = True
    auto_compaction: bool = True
    before_compact_hook: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    compaction_complete_fn: Callable[..., AssistantMessage] | None = None
    extension_runner: Any = None


class AgentSession:
    def __init__(self, config: AgentSessionConfig) -> None:
        self.agent = config.agent
        self.session_manager = config.session_manager
        self.settings_manager = config.settings_manager or SettingsManager.in_memory()
        self.auth_storage = config.auth_storage or AuthStorage.in_memory()
        self.cwd = config.cwd
        self.model_registry = config.model_registry or ModelRegistry()
        self.scoped_models = list(config.scoped_models)
        self._resource_loader = config.resource_loader or DefaultResourceLoader()
        self.retry_settings = config.retry_settings
        self.compaction_settings = config.compaction_settings
        self.auto_retry = bool(config.auto_retry)
        self.auto_compaction = bool(config.auto_compaction)
        self.before_compact_hook = config.before_compact_hook
        self.compaction_complete_fn = config.compaction_complete_fn
        self.extension_runner = config.extension_runner

        self._listeners: list[Callable[[AgentEvent], None]] = []
        self._unsubscribe_agent = self.agent.subscribe(self._on_agent_event)
        self._retry_attempt = 0
        self._overflow_recovery_attempted = False
        self._in_recovery = False
        self._install_agent_tool_hooks()
        self._restore_from_session()

    def _emit_session_event(self, event: AgentEvent) -> None:
        for listener in list(self._listeners):
            listener(event)

    def _restore_from_session(self) -> None:
        context = self.session_manager.build_session_context()
        self.agent.replace_messages(context.messages)

        if context.model is not None:
            provider = context.model.get("provider")
            model_id = context.model.get("modelId")
            if provider and model_id:
                resolved = self.model_registry.find(provider, model_id)
                if resolved is None:
                    resolved = Model(provider=provider, id=model_id)
                self.agent.set_model(resolved)

        thinking = self.agent.state.thinking_level or "off"
        if any(entry.get("type") == "thinking_level_change" for entry in self.session_manager.get_branch()):
            thinking = context.thinking_level or "off"
        self.agent.set_thinking_level(thinking)  # type: ignore[arg-type]

    def _build_runtime_system_prompt(self, prompt: str | None) -> str:
        active_tool_names = [getattr(tool, "name", "") for tool in self.agent.state.tools if getattr(tool, "name", "")]
        append_parts = self._resource_loader.getAppendSystemPrompt()
        return build_system_prompt(
            custom_prompt=prompt,
            selected_tools=active_tool_names,
            append_system_prompt="\n\n".join(append_parts) if append_parts else None,
            cwd=self.cwd,
            context_files=self._resource_loader.getAgentsFiles()["agentsFiles"],
            skills=self._resource_loader.getSkills()["skills"],
        )

    def _install_agent_tool_hooks(self) -> None:
        self.agent.set_before_tool_call(self._before_tool_call)
        self.agent.set_after_tool_call(self._after_tool_call)

    def _before_tool_call(self, payload: dict[str, Any], signal: Any = None) -> dict[str, Any] | None:
        del signal
        if self.extension_runner is None or not self.extension_runner.has_handlers("tool_call"):
            return None
        tool_call = payload.get("toolCall", {})
        return self.extension_runner.emit_tool_call(
            {
                "type": "tool_call",
                "toolName": str(tool_call.get("name", "")),
                "toolCallId": str(tool_call.get("id", "")),
                "input": payload.get("args", {}),
            }
        )

    def _after_tool_call(self, payload: dict[str, Any], signal: Any = None) -> dict[str, Any] | None:
        del signal
        if self.extension_runner is None or not self.extension_runner.has_handlers("tool_result"):
            return None
        tool_call = payload.get("toolCall", {})
        result = payload.get("result")
        content = getattr(result, "content", [])
        details = getattr(result, "details", None)
        event = self.extension_runner.emit_tool_result(
            {
                "type": "tool_result",
                "toolName": str(tool_call.get("name", "")),
                "toolCallId": str(tool_call.get("id", "")),
                "input": payload.get("args", {}),
                "content": content,
                "details": details,
                "isError": bool(payload.get("isError", False)),
            }
        )
        if not isinstance(event, dict):
            return None
        overrides: dict[str, Any] = {}
        if "content" in event:
            overrides["content"] = event["content"]
        if "details" in event:
            overrides["details"] = event["details"]
        if "isError" in event:
            overrides["isError"] = bool(event["isError"])
        return overrides or None

    def _on_agent_event(self, event: AgentEvent) -> None:
        event_type = event.get("type")
        if event_type == "message_end":
            message = event.get("message")
            if message is not None:
                self.session_manager.append_message(message)

        if self.extension_runner is not None:
            self.extension_runner.emit(event)

        for listener in list(self._listeners):
            listener(event)

    def _get_last_assistant_message(self) -> Any | None:
        for message in reversed(self.agent.state.messages):
            if _role(message) == "assistant":
                return message
        return None

    def _remove_last_assistant_from_agent_state(self) -> None:
        messages = list(self.agent.state.messages)
        if messages and _role(messages[-1]) == "assistant":
            self.agent.replace_messages(messages[:-1])

    def _is_retryable_error(self, message: Any) -> bool:
        if _role(message) != "assistant":
            return False
        if _assistant_stop_reason(message) != "error":
            return False
        error_message = _assistant_error_message(message)
        if not error_message:
            return False

        assistant = _as_assistant_message(message)
        context_window = getattr(self.model, "context_window", 0) if self.model is not None else 0
        if assistant is not None and is_context_overflow(assistant, int(context_window) if context_window else None):
            return False
        return _RETRYABLE_ERROR_RE.search(error_message) is not None

    def _handle_retryable_error(self, message: Any) -> bool:
        if not self.auto_retry or not self.retry_settings.enabled:
            return False
        if not self._is_retryable_error(message):
            return False

        self._retry_attempt += 1
        if self._retry_attempt > self.retry_settings.max_retries:
            self._emit_session_event(
                {
                    "type": "auto_retry_end",
                    "success": False,
                    "attempt": self._retry_attempt - 1,
                    "finalError": _assistant_error_message(message) or "Unknown error",
                }
            )
            self._retry_attempt = 0
            return False

        delay_ms = min(
            self.retry_settings.base_delay_ms * (2 ** (self._retry_attempt - 1)),
            self.retry_settings.max_delay_ms,
        )
        self._emit_session_event(
            {
                "type": "auto_retry_start",
                "attempt": self._retry_attempt,
                "maxAttempts": self.retry_settings.max_retries,
                "delayMs": delay_ms,
                "errorMessage": _assistant_error_message(message) or "Unknown error",
            }
        )

        self._remove_last_assistant_from_agent_state()
        if delay_ms > 0:
            sleep(delay_ms / 1000)
        self.agent.continue_run()
        return True

    def _handle_auto_compaction(self, message: Any) -> Literal["none", "compacted", "continued"]:
        if not self.auto_compaction or not self.compaction_settings.enabled:
            return "none"
        assistant = _as_assistant_message(message)
        if assistant is None:
            return "none"

        context_window = int(getattr(self.model, "context_window", 0) or 0)
        if context_window <= 0:
            return "none"

        if assistant.stop_reason == "error" and is_context_overflow(assistant, context_window):
            if self._overflow_recovery_attempted:
                self._emit_session_event(
                    {
                        "type": "auto_compaction_end",
                        "result": None,
                        "aborted": False,
                        "willRetry": False,
                        "errorMessage": (
                            "Context overflow recovery failed after one compact-and-retry attempt. "
                            "Try reducing context or switching models."
                        ),
                    }
                )
                return "none"

            self._overflow_recovery_attempted = True
            self._remove_last_assistant_from_agent_state()
            self._emit_session_event({"type": "auto_compaction_start", "reason": "overflow"})
            try:
                result = self.compact()
            except ValueError as exc:
                self._emit_session_event(
                    {
                        "type": "auto_compaction_end",
                        "result": None,
                        "aborted": False,
                        "willRetry": False,
                        "errorMessage": str(exc),
                    }
                )
                return "none"

            will_retry = not (self.agent.state.messages and _role(self.agent.state.messages[-1]) == "assistant")
            self._emit_session_event(
                {
                    "type": "auto_compaction_end",
                    "result": result,
                    "aborted": False,
                    "willRetry": will_retry,
                }
            )
            if not will_retry:
                return "compacted"
            self.agent.continue_run()
            return "continued"

        if assistant.stop_reason == "error":
            estimate = estimate_context_tokens(self.agent.state.messages)
            if estimate.last_usage_index is None:
                return "none"
            latest_compaction = get_latest_compaction_entry(self.session_manager.get_branch())
            if latest_compaction is not None:
                usage_source = self.agent.state.messages[estimate.last_usage_index]
                usage_source_ts = usage_source.get("timestamp", 0) if isinstance(usage_source, dict) else getattr(usage_source, "timestamp", 0)
                compaction_ts = int(datetime.fromisoformat(str(latest_compaction["timestamp"]).replace("Z", "+00:00")).timestamp() * 1000)
                if int(usage_source_ts or 0) <= compaction_ts:
                    return "none"
            context_tokens = estimate.tokens
        else:
            context_tokens = calculate_context_tokens(_usage(message) or {})

        if should_compact(context_tokens, context_window, self.compaction_settings):
            self._emit_session_event({"type": "auto_compaction_start", "reason": "threshold"})
            try:
                result = self.compact()
            except ValueError as exc:
                self._emit_session_event(
                    {
                        "type": "auto_compaction_end",
                        "result": None,
                        "aborted": False,
                        "willRetry": False,
                        "errorMessage": str(exc),
                    }
                )
                return "none"

            self._emit_session_event(
                {
                    "type": "auto_compaction_end",
                    "result": result,
                    "aborted": False,
                    "willRetry": False,
                }
            )
            return "compacted"

        return "none"

    def _post_run_recovery(self) -> None:
        for _ in range(32):
            last_assistant = self._get_last_assistant_message()
            if last_assistant is None:
                return

            compaction_result = self._handle_auto_compaction(last_assistant)
            if compaction_result == "continued":
                continue
            if compaction_result == "compacted":
                return

            if self._handle_retryable_error(last_assistant):
                continue

            stop_reason = _assistant_stop_reason(last_assistant)
            if stop_reason not in {"error", "aborted"} and self._retry_attempt > 0:
                attempt = self._retry_attempt
                self._retry_attempt = 0
                self._emit_session_event({"type": "auto_retry_end", "success": True, "attempt": attempt})
            if stop_reason != "error":
                self._overflow_recovery_attempted = False
            return

    def _run_with_recovery(self, run: Callable[[], None]) -> None:
        if self._in_recovery:
            run()
            return
        self._in_recovery = True
        try:
            run()
            self._post_run_recovery()
        finally:
            self._in_recovery = False

    def subscribe(self, listener: Callable[[AgentEvent], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    @property
    def state(self):  # noqa: ANN201
        return self.agent.state

    @property
    def model(self):  # noqa: ANN201
        return self.agent.state.model

    @property
    def thinking_level(self):  # noqa: ANN201
        return self.agent.state.thinking_level

    @property
    def session_file(self) -> str | None:
        return self.session_manager.get_session_file()

    @property
    def session_id(self) -> str:
        return self.session_manager.get_session_id()

    @property
    def retry_attempt(self) -> int:
        return self._retry_attempt

    @property
    def resource_loader(self) -> DefaultResourceLoader:
        return self._resource_loader

    @property
    def prompt_templates(self) -> list[PromptTemplate]:
        return list(self._resource_loader.getPrompts()["prompts"])

    @property
    def is_retry_in_progress(self) -> bool:
        return False

    def set_auto_retry(self, enabled: bool) -> None:
        self.auto_retry = bool(enabled)

    def set_auto_compaction(self, enabled: bool) -> None:
        self.auto_compaction = bool(enabled)

    def prompt(self, message: str | Any | list[Any]) -> None:
        if isinstance(message, str):
            message = expand_prompt_template(message, self.prompt_templates)
            if dispatch_slash_command(self, message):
                return
        original_system_prompt = self.agent.state.system_prompt
        self.agent.set_system_prompt(self._build_runtime_system_prompt(original_system_prompt))
        if self.extension_runner is not None and isinstance(message, str) and self.extension_runner.has_handlers("before_agent_start"):
            result = self.extension_runner.emit_before_agent_start(
                {
                    "type": "before_agent_start",
                    "prompt": message,
                    "systemPrompt": original_system_prompt,
                }
            )
            for custom in result.get("messages", []):
                timestamp_ms = int(datetime.now().timestamp() * 1000)
                custom_message = create_custom_message(
                    custom_type=str(custom.get("customType", "extension")),
                    content=custom.get("content", ""),
                    display=bool(custom.get("display", False)),
                    details=custom.get("details"),
                    timestamp_ms=timestamp_ms,
                )
                self.agent.append_message(custom_message)
                self.session_manager.append_custom_message_entry(
                    custom_type=str(custom.get("customType", "extension")),
                    content=custom.get("content", ""),
                    display=bool(custom.get("display", False)),
                    details=custom.get("details"),
                )
            if result.get("systemPrompt") is not None:
                self.agent.set_system_prompt(str(result["systemPrompt"]))

        try:
            self._run_with_recovery(lambda: self.agent.prompt(message))
        finally:
            if self.agent.state.system_prompt != original_system_prompt:
                self.agent.set_system_prompt(original_system_prompt)

    def continue_run(self) -> None:
        self._run_with_recovery(self.agent.continue_run)

    def abort_retry(self) -> None:
        self._retry_attempt = 0

    def abort(self) -> None:
        self.agent.abort()

    def set_system_prompt(self, prompt: str) -> None:
        self.agent.set_system_prompt(prompt)

    def set_model(self, model: Model) -> None:
        self.agent.set_model(model)
        self.session_manager.append_model_change(model.provider, model.id)

    def set_thinking_level(self, level: str) -> None:
        self.agent.set_thinking_level(level)  # type: ignore[arg-type]
        self.session_manager.append_thinking_level_change(level)

    def set_tools(self, tools: list[Any]) -> None:
        self.agent.set_tools(tools)

    def replace_messages(self, messages: list[Any]) -> None:
        self.agent.replace_messages(messages)

    def clear_messages(self) -> None:
        self.agent.clear_messages()

    def new_session(self, parent_session: str | None = None, session_id: str | None = None) -> str | None:
        result = self.session_manager.new_session(parent_session=parent_session, session_id=session_id)
        self.agent.session_id = self.session_manager.get_session_id()
        self._retry_attempt = 0
        self._overflow_recovery_attempted = False
        self._restore_from_session()
        return result

    def compact(self, custom_instructions: str | None = None) -> dict[str, Any]:
        path_entries = self.session_manager.get_branch()
        preparation = prepare_compaction(path_entries, self.compaction_settings)
        if preparation is None:
            raise ValueError("Nothing to compact (session too small or already compacted)")

        from_hook = False
        from_extension = False
        if self.extension_runner is not None and self.extension_runner.has_handlers("session_before_compact"):
            extension_result = self.extension_runner.emit_session_before_compact(
                {
                    "type": "session_before_compact",
                    "preparation": preparation,
                    "branchEntries": path_entries,
                    "customInstructions": custom_instructions,
                }
            )
            if extension_result and extension_result.get("cancel"):
                raise ValueError("Compaction cancelled by extension")
            if extension_result and extension_result.get("compaction"):
                result = dict(extension_result["compaction"])
                from_extension = True
            elif self.before_compact_hook is not None:
                hook_result = self.before_compact_hook(preparation)
                if hook_result and hook_result.get("summary"):
                    from_hook = True
                    result = {
                        "summary": str(hook_result["summary"]),
                        "firstKeptEntryId": str(hook_result.get("firstKeptEntryId", preparation["firstKeptEntryId"])),
                        "tokensBefore": int(hook_result.get("tokensBefore", preparation["tokensBefore"])),
                        "details": hook_result.get("details", preparation.get("details")),
                    }
                else:
                    kwargs: dict[str, Any] = {"custom_instructions": custom_instructions}
                    if self.compaction_complete_fn is not None:
                        kwargs["complete_fn"] = self.compaction_complete_fn
                    result = run_compaction(
                        preparation,
                        self.model,
                        **kwargs,
                    )
            else:
                kwargs = {"custom_instructions": custom_instructions}
                if self.compaction_complete_fn is not None:
                    kwargs["complete_fn"] = self.compaction_complete_fn
                result = run_compaction(
                    preparation,
                    self.model,
                    **kwargs,
                )
        elif self.before_compact_hook is not None:
            hook_result = self.before_compact_hook(preparation)
            if hook_result and hook_result.get("summary"):
                from_hook = True
                result = {
                    "summary": str(hook_result["summary"]),
                    "firstKeptEntryId": str(hook_result.get("firstKeptEntryId", preparation["firstKeptEntryId"])),
                    "tokensBefore": int(hook_result.get("tokensBefore", preparation["tokensBefore"])),
                    "details": hook_result.get("details", preparation.get("details")),
                }
            else:
                kwargs: dict[str, Any] = {"custom_instructions": custom_instructions}
                if self.compaction_complete_fn is not None:
                    kwargs["complete_fn"] = self.compaction_complete_fn
                result = run_compaction(
                    preparation,
                    self.model,
                    **kwargs,
                )
        else:
            kwargs: dict[str, Any] = {"custom_instructions": custom_instructions}
            if self.compaction_complete_fn is not None:
                kwargs["complete_fn"] = self.compaction_complete_fn
            result = run_compaction(
                preparation,
                self.model,
                **kwargs,
            )
        self.session_manager.append_compaction(
            summary=result["summary"],
            first_kept_entry_id=result["firstKeptEntryId"],
            tokens_before=result["tokensBefore"],
            details=result.get("details"),
            from_hook=from_hook,
        )
        self._restore_from_session()
        if self.extension_runner is not None:
            compaction_entry = self.session_manager.get_entries()[-1]
            self.extension_runner.emit(
                {
                    "type": "session_compact",
                    "compactionEntry": compaction_entry,
                    "fromExtension": from_extension,
                }
            )
        return result

    def get_context_usage(self) -> dict[str, Any]:
        context_window = int(getattr(self.model, "context_window", 0) or 0)
        estimate = estimate_context_tokens(self.agent.state.messages)
        percent = (estimate.tokens / context_window * 100.0) if context_window > 0 else None
        return {
            "tokens": estimate.tokens,
            "contextWindow": context_window,
            "percent": percent,
            "usageTokens": estimate.usage_tokens,
            "trailingTokens": estimate.trailing_tokens,
        }

    def switch_session(self, session_path: str) -> None:
        self.session_manager.set_session_file(session_path)
        self.agent.session_id = self.session_manager.get_session_id()
        self._retry_attempt = 0
        self._overflow_recovery_attempted = False
        self._restore_from_session()

    def reload(self) -> None:
        self.settings_manager.reload()
        self._resource_loader.reload()

    def get_last_assistant_text(self) -> str | None:
        for message in reversed(self.agent.state.messages):
            if _role(message) != "assistant":
                continue
            content = message.get("content", []) if isinstance(message, dict) else getattr(message, "content", [])
            if isinstance(content, list):
                parts = [str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text"]
                return "\n".join(part for part in parts if part).strip() or None
        return None

    def export_to_html(self, output_path: str | None = None) -> str:
        session_file = self.session_file
        if not session_file:
            raise ValueError("Cannot export in-memory session to HTML")
        return export_session_to_html(
            session_file=session_file,
            header=self.session_manager.get_header(),
            entries=self.session_manager.get_entries(),
            output_path=output_path,
            title=self.session_manager.get_session_name(),
        )

    def share_session(self, output_path: str | None = None, include_html_preview: bool = True) -> str:
        session_file = self.session_file
        if not session_file:
            raise ValueError("Cannot share in-memory session")
        html_path = self.export_to_html() if include_html_preview else None
        return export_share_bundle(
            session_file=session_file,
            header=self.session_manager.get_header(),
            entries=self.session_manager.get_entries(),
            output_path=output_path,
            html_path=html_path,
        )

    def set_session_name(self, name: str) -> None:
        self.session_manager.append_session_info(name)

    def get_session_stats(self) -> SessionStats:
        messages = list(self.agent.state.messages)
        user_messages = 0
        assistant_messages = 0
        tool_results = 0
        tool_calls = 0
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_write = 0
        total_cost = 0.0

        for message in messages:
            role = _role(message)
            if role == "user":
                user_messages += 1
            elif role == "assistant":
                assistant_messages += 1
                blocks = message.get("content", []) if isinstance(message, dict) else getattr(message, "content", [])
                if isinstance(blocks, list):
                    tool_calls += sum(1 for block in blocks if isinstance(block, dict) and block.get("type") == "toolCall")
                usage = _usage(message) or {}
                total_input += int(usage.get("input", 0))
                total_output += int(usage.get("output", 0))
                total_cache_read += int(usage.get("cacheRead", 0))
                total_cache_write += int(usage.get("cacheWrite", 0))
                cost = usage.get("cost", {})
                if isinstance(cost, dict):
                    total_cost += float(cost.get("total", 0.0))
            elif role == "toolResult":
                tool_results += 1

        tokens_total = total_input + total_output + total_cache_read + total_cache_write
        return SessionStats(
            session_file=self.session_manager.get_session_file(),
            session_id=self.session_manager.get_session_id(),
            user_messages=user_messages,
            assistant_messages=assistant_messages,
            tool_calls=tool_calls,
            tool_results=tool_results,
            total_messages=len(messages),
            tokens={
                "input": total_input,
                "output": total_output,
                "cacheRead": total_cache_read,
                "cacheWrite": total_cache_write,
                "total": tokens_total,
            },
            cost=total_cost,
        )

    def dispose(self) -> None:
        if self._unsubscribe_agent is not None:
            self._unsubscribe_agent()
            self._unsubscribe_agent = None
        self._listeners = []

    def _append_local_assistant_message(self, text: str) -> AssistantMessage:
        message = AssistantMessage(
            content=[text_block(text)],
            api=self.model.api,
            provider=self.model.provider,
            model=self.model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(datetime.now().timestamp() * 1000),
        )
        self.agent.append_message(message)
        self.session_manager.append_message(message)
        event = {"type": "message_end", "message": message}
        if self.extension_runner is not None:
            self.extension_runner.emit(event)
        for listener in list(self._listeners):
            listener(event)
        return message
