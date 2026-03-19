from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Any, Callable

from ai import AssistantMessage, CompleteOptions, LLMContext, Model, SimpleStreamOptions, Usage, UserMessage, complete_simple, text_block
from ai.backend import LLMBackend, ScriptedBackend
from coding_agent.core.sdk import CreateAgentSessionOptions, create_agent_session
from coding_agent.core.session_manager import SessionManager

from .context import sync_log_to_session_manager
from .sandbox import SandboxConfig, create_executor
from .tools import create_mom_tools, set_upload_function
from .workspace import MomWorkspace


class MomBackend(LLMBackend):
    def complete(self, model: Model, context: LLMContext, options: CompleteOptions | None = None) -> AssistantMessage:
        stream_options = SimpleStreamOptions(
            api_key=options.api_key if options else None,
            session_id=options.session_id if options else None,
            reasoning=options.reasoning if options and options.reasoning is not None else None,
        )
        return complete_simple(model, context, stream_options)


@dataclass
class PendingMessage:
    user_name: str
    text: str
    attachments: list[dict[str, str]] = field(default_factory=list)
    timestamp: int = field(default_factory=lambda: int(time() * 1000))


@dataclass
class MomRunnerConfig:
    sandbox: SandboxConfig
    workspace_dir: str
    channel_id: str
    backend: LLMBackend | None = None
    model: Model | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None


def _read_memory(workspace: MomWorkspace, channel_id: str) -> str:
    parts: list[str] = []
    global_memory = Path(workspace.global_memory_path())
    if global_memory.exists():
        content = global_memory.read_text(encoding="utf-8").strip()
        if content:
            parts.append(f"Global Memory:\n{content}")
    channel_memory = Path(workspace.channel_memory_path(channel_id))
    if channel_memory.exists():
        content = channel_memory.read_text(encoding="utf-8").strip()
        if content:
            parts.append(f"Channel Memory:\n{content}")
    return "\n\n".join(parts) if parts else "(no working memory yet)"


def build_system_prompt(workspace: MomWorkspace, channel_id: str, workspace_path: str) -> str:
    memory = _read_memory(workspace, channel_id)
    return (
        "You are mom, a Slack bot assistant. Be concise.\n\n"
        "You have tools: bash, read, write, edit, attach.\n"
        "Use bash as your primary tool for doing work.\n"
        "Do not output markdown tables unless explicitly asked.\n"
        f"Workspace root: {workspace_path}\n"
        f"Channel workspace: {workspace_path}/{channel_id}\n\n"
        "Memory:\n"
        f"{memory}\n"
    )


def _make_default_model(config: MomRunnerConfig) -> Model:
    base_url = config.llm_base_url or os.environ.get("LLM_BASE_URL") or ""
    api_key = config.llm_api_key or os.environ.get("LLM_API_KEY") or None
    model_id = config.llm_model or os.environ.get("LLM_MODEL") or "qwen3.5-122b-vl"
    del api_key
    return Model(
        provider="openai-compatible",
        id=model_id,
        name=model_id,
        api="openai-completions",
        base_url=base_url,
        context_window=200_000,
        max_tokens=8192,
    )


def _user_message(text: str, timestamp_ms: int) -> UserMessage:
    return UserMessage(content=[text_block(text)], timestamp=timestamp_ms)


class MomRunner:
    def __init__(self, config: MomRunnerConfig) -> None:
        self.config = config
        self.workspace = MomWorkspace(config.workspace_dir)
        self.executor = create_executor(config.sandbox)
        self.host_channel_dir = self.workspace.channel_dir(config.channel_id)
        self.session_manager = SessionManager.open(self.workspace.channel_context_path(config.channel_id), self.host_channel_dir)
        self.model = config.model or _make_default_model(config)
        self.backend = config.backend or MomBackend()
        self.tools = create_mom_tools(self.executor)
        workspace_path = self.executor.get_workspace_path(config.workspace_dir)
        self.system_prompt = build_system_prompt(self.workspace, config.channel_id, workspace_path)
        self.session = create_agent_session(
            CreateAgentSessionOptions(
                cwd=workspace_path,
                model=self.model,
                tools=self.tools,
                session_manager=self.session_manager,
                backend=self.backend,
                system_prompt=self.system_prompt,
                auto_retry=True,
                auto_compaction=True,
            )
        )

    def abort(self) -> None:
        self.session.abort()

    def run(self, ctx: Any, store: Any | None = None, pending_messages: list[PendingMessage] | None = None) -> dict[str, Any]:
        del store
        Path(self.host_channel_dir).mkdir(parents=True, exist_ok=True)
        sync_log_to_session_manager(self.session_manager, self.host_channel_dir, getattr(ctx.message, "ts", None) if hasattr(ctx, "message") else None)
        set_upload_function(lambda file_path, title=None: ctx.upload_file(file_path, title))

        prompt_messages: list[Any] = []
        if pending_messages:
            for pending in pending_messages:
                prompt_messages.append(_user_message(f"[{pending.user_name}]: {pending.text}", pending.timestamp))

        message = getattr(ctx, "message", None)
        if message is not None:
            text = f"[{getattr(message, 'user_name', None) or getattr(message, 'user', 'unknown')}]: {getattr(message, 'text', '')}"
            prompt_messages.append(_user_message(text, int(getattr(message, 'timestamp', int(time() * 1000)))))

        if not prompt_messages:
            raise RuntimeError("No prompt messages to run")

        if hasattr(ctx, "set_typing"):
            ctx.set_typing(True)
        self.session.prompt(prompt_messages if len(prompt_messages) > 1 else prompt_messages[0])
        assistant = next((msg for msg in reversed(self.session.state.messages) if getattr(msg, "role", None) == "assistant"), None)
        if assistant is None:
            raise RuntimeError("No assistant response")

        text_parts = [str(block.get("text", "")) for block in getattr(assistant, "content", []) if isinstance(block, dict) and block.get("type") == "text"]
        response_text = "\n".join(part for part in text_parts if part).strip()

        if response_text != "[SILENT]":
            if hasattr(ctx, "respond"):
                ctx.respond(response_text or "")

        if hasattr(ctx, "set_typing"):
            ctx.set_typing(False)

        return {"stopReason": getattr(assistant, "stop_reason", "stop"), "errorMessage": getattr(assistant, "error_message", None)}


def get_or_create_runner(
    sandbox: SandboxConfig,
    channel_id: str,
    channel_dir: str,
    *,
    backend: LLMBackend | None = None,
    model: Model | None = None,
) -> MomRunner:
    workspace_dir = str(Path(channel_dir).parent)
    return MomRunner(MomRunnerConfig(sandbox=sandbox, workspace_dir=workspace_dir, channel_id=channel_id, backend=backend, model=model))
