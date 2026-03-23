# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .types import Extension, ExtensionContext, ExtensionUIContext, RegisteredCommand, RegisteredTool

ExtensionErrorListener = Callable[[dict[str, Any]], None]


@dataclass
class _BindingState:
    model_getter: Callable[[], Any] = lambda: None
    is_idle_fn: Callable[[], bool] = lambda: True
    abort_fn: Callable[[], None] = lambda: None
    has_pending_messages_fn: Callable[[], bool] = lambda: False
    shutdown_fn: Callable[[], None] = lambda: None
    context_usage_fn: Callable[[], dict[str, Any] | None] = lambda: None
    compact_fn: Callable[[dict[str, Any] | None], Any] = lambda options=None: None
    system_prompt_fn: Callable[[], str] = lambda: ""


class ExtensionRunner:
    def __init__(self, extensions: list[Extension], cwd: str, session_manager: Any, model_registry: Any) -> None:
        self.extensions = list(extensions)
        self.cwd = cwd
        self.session_manager = session_manager
        self.model_registry = model_registry
        self.ui_context = ExtensionUIContext()
        self._bindings = _BindingState()
        self._error_listeners: list[ExtensionErrorListener] = []
        self._registered_tools: list[RegisteredTool] = []
        self._registered_commands: list[RegisteredCommand] = []
        self._handlers: dict[str, list[tuple[str, Callable[[dict[str, Any], ExtensionContext], Any]]]] = {}

        for extension in self.extensions:
            self._registered_tools.extend(extension.registered_tools)
            self._registered_commands.extend(extension.registered_commands)
            for event_type, handlers in extension.handlers.items():
                current = self._handlers.setdefault(event_type, [])
                current.extend((extension.name, handler) for handler in handlers)

    @property
    def registered_tools(self) -> list[RegisteredTool]:
        return list(self._registered_tools)

    @property
    def registered_commands(self) -> list[RegisteredCommand]:
        return list(self._registered_commands)

    def get_command(self, name: str) -> RegisteredCommand | None:
        for command in self._registered_commands:
            if command.name == name:
                return command
        return None

    def execute_command(self, name: str, args: list[str]) -> Any:
        command = self.get_command(name)
        if command is None or command.handler is None:
            raise ValueError(f"Unknown extension command: {name}")
        return command.handler(list(args), self.create_context())

    def bind_session(self, session: Any) -> None:
        self._bindings = _BindingState(
            model_getter=lambda: session.model,
            is_idle_fn=lambda: not bool(session.state.is_streaming),
            abort_fn=session.abort,
            has_pending_messages_fn=lambda: bool(getattr(session.agent, "_steering_queue", []) or getattr(session.agent, "_follow_up_queue", [])),
            shutdown_fn=lambda: None,
            context_usage_fn=session.get_context_usage,
            compact_fn=lambda options=None: session.compact((options or {}).get("customInstructions")),
            system_prompt_fn=lambda: str(session.state.system_prompt),
        )

    def add_error_listener(self, listener: ExtensionErrorListener) -> Callable[[], None]:
        self._error_listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._error_listeners:
                self._error_listeners.remove(listener)

        return unsubscribe

    def _notify_error(self, extension_name: str, event_type: str, error: Exception) -> None:
        payload = {
            "type": "extension_error",
            "extension": extension_name,
            "event": event_type,
            "error": str(error),
        }
        for listener in list(self._error_listeners):
            listener(payload)

    def has_handlers(self, event_type: str) -> bool:
        return bool(self._handlers.get(event_type))

    def create_context(self) -> ExtensionContext:
        return ExtensionContext(
            cwd=self.cwd,
            session_manager=self.session_manager,
            model_registry=self.model_registry,
            ui=self.ui_context,
            has_ui=False,
            model_getter=self._bindings.model_getter,
            is_idle_fn=self._bindings.is_idle_fn,
            abort_fn=self._bindings.abort_fn,
            has_pending_messages_fn=self._bindings.has_pending_messages_fn,
            shutdown_fn=self._bindings.shutdown_fn,
            context_usage_fn=self._bindings.context_usage_fn,
            compact_fn=self._bindings.compact_fn,
            system_prompt_fn=self._bindings.system_prompt_fn,
        )

    def emit(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        for extension_name, handler in self._handlers.get(event_type, []):
            try:
                handler(dict(event), self.create_context())
            except Exception as exc:  # noqa: BLE001
                self._notify_error(extension_name, event_type, exc)

    def emit_context(self, event: dict[str, Any]) -> dict[str, Any]:
        current = dict(event)
        current["messages"] = list(event.get("messages", []))
        for extension_name, handler in self._handlers.get("context", []):
            try:
                result = handler(dict(current), self.create_context())
            except Exception as exc:  # noqa: BLE001
                self._notify_error(extension_name, "context", exc)
                raise
            if isinstance(result, dict) and "messages" in result:
                current["messages"] = list(result["messages"])
        return current

    def emit_tool_call(self, event: dict[str, Any]) -> dict[str, Any] | None:
        for extension_name, handler in self._handlers.get("tool_call", []):
            try:
                result = handler(dict(event), self.create_context())
            except Exception as exc:  # noqa: BLE001
                self._notify_error(extension_name, "tool_call", exc)
                raise
            if isinstance(result, dict) and result.get("block"):
                return result
        return None

    def emit_tool_result(self, event: dict[str, Any]) -> dict[str, Any] | None:
        current = dict(event)
        for extension_name, handler in self._handlers.get("tool_result", []):
            try:
                result = handler(dict(current), self.create_context())
            except Exception as exc:  # noqa: BLE001
                self._notify_error(extension_name, "tool_result", exc)
                raise
            if not isinstance(result, dict):
                continue
            if "content" in result:
                current["content"] = result["content"]
            if "details" in result:
                current["details"] = result["details"]
            if "isError" in result:
                current["isError"] = bool(result["isError"])
        return current

    def emit_before_agent_start(self, event: dict[str, Any]) -> dict[str, Any]:
        current_prompt = str(event.get("systemPrompt", ""))
        messages: list[dict[str, Any]] = []
        for extension_name, handler in self._handlers.get("before_agent_start", []):
            try:
                result = handler({**event, "systemPrompt": current_prompt}, self.create_context())
            except Exception as exc:  # noqa: BLE001
                self._notify_error(extension_name, "before_agent_start", exc)
                raise
            if not isinstance(result, dict):
                continue
            message = result.get("message")
            if isinstance(message, dict):
                messages.append(message)
            if "systemPrompt" in result and result["systemPrompt"] is not None:
                current_prompt = str(result["systemPrompt"])
        return {"messages": messages, "systemPrompt": current_prompt}

    def emit_session_before_compact(self, event: dict[str, Any]) -> dict[str, Any] | None:
        current: dict[str, Any] | None = None
        for extension_name, handler in self._handlers.get("session_before_compact", []):
            try:
                result = handler(dict(event), self.create_context())
            except Exception as exc:  # noqa: BLE001
                self._notify_error(extension_name, "session_before_compact", exc)
                raise
            if not isinstance(result, dict):
                continue
            if result.get("cancel"):
                return {"cancel": True}
            if "compaction" in result and result["compaction"] is not None:
                current = {"compaction": dict(result["compaction"])}
        return current
