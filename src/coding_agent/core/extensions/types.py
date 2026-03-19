from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ai import Model

Handler = Callable[[dict[str, Any], "ExtensionContext"], Any]
ToolExecutor = Callable[[str, dict[str, Any], Any, Any, "ExtensionContext"], Any]
CommandHandler = Callable[[list[str], "ExtensionContext"], Any]


@dataclass
class ExtensionUIContext:
    def select(self, title: str, options: list[str], opts: dict[str, Any] | None = None) -> None:
        del title, options, opts
        return None

    def confirm(self, title: str, message: str, opts: dict[str, Any] | None = None) -> bool:
        del title, message, opts
        return False

    def input(self, title: str, placeholder: str | None = None, opts: dict[str, Any] | None = None) -> None:
        del title, placeholder, opts
        return None

    def notify(self, message: str, type: str = "info") -> None:
        del message, type


@dataclass
class ExtensionContext:
    cwd: str
    session_manager: Any
    model_registry: Any
    ui: ExtensionUIContext
    has_ui: bool
    model_getter: Callable[[], Model | None]
    is_idle_fn: Callable[[], bool]
    abort_fn: Callable[[], None]
    has_pending_messages_fn: Callable[[], bool]
    shutdown_fn: Callable[[], None]
    context_usage_fn: Callable[[], dict[str, Any] | None]
    compact_fn: Callable[[dict[str, Any] | None], Any]
    system_prompt_fn: Callable[[], str]

    @property
    def model(self) -> Model | None:
        return self.model_getter()

    def is_idle(self) -> bool:
        return self.is_idle_fn()

    def abort(self) -> None:
        self.abort_fn()

    def has_pending_messages(self) -> bool:
        return self.has_pending_messages_fn()

    def shutdown(self) -> None:
        self.shutdown_fn()

    def get_context_usage(self) -> dict[str, Any] | None:
        return self.context_usage_fn()

    def compact(self, options: dict[str, Any] | None = None) -> Any:
        return self.compact_fn(options)

    def get_system_prompt(self) -> str:
        return self.system_prompt_fn()


@dataclass
class ToolDefinition:
    name: str
    label: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    execute: ToolExecutor | None = None
    prompt_snippet: str | None = None
    prompt_guidelines: list[str] = field(default_factory=list)


@dataclass
class RegisteredTool:
    definition: ToolDefinition
    extension_name: str


@dataclass
class RegisteredCommand:
    name: str
    description: str | None = None
    extension_name: str = ""
    path: str | None = None
    handler: CommandHandler | None = None


@dataclass
class Extension:
    name: str
    path: str | None = None
    handlers: dict[str, list[Handler]] = field(default_factory=dict)
    registered_tools: list[RegisteredTool] = field(default_factory=list)
    registered_commands: list[RegisteredCommand] = field(default_factory=list)


class ExtensionAPI:
    def __init__(self, extension: Extension) -> None:
        self._extension = extension

    def on(self, event_type: str, handler: Handler) -> None:
        self._extension.handlers.setdefault(event_type, []).append(handler)

    def register_tool(self, definition: ToolDefinition) -> RegisteredTool:
        registered = RegisteredTool(definition=definition, extension_name=self._extension.name)
        self._extension.registered_tools.append(registered)
        return registered

    def register_command(
        self,
        name: str,
        description: str | None = None,
        handler: CommandHandler | None = None,
    ) -> RegisteredCommand:
        registered = RegisteredCommand(
            name=name,
            description=description,
            extension_name=self._extension.name,
            path=self._extension.path,
            handler=handler,
        )
        self._extension.registered_commands.append(registered)
        return registered


def build_extension(name: str, factory: Callable[[ExtensionAPI], Any]) -> Extension:
    extension = Extension(name=name)
    factory(ExtensionAPI(extension))
    return extension
