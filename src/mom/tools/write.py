from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent import AgentToolResult

from ..sandbox import ExecOptions


def _shell_escape(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


@dataclass
class WriteTool:
    executor: Any
    name: str = "write"
    label: str = "write"
    description: str = "Write content to a file, creating parent directories as needed."
    parameters: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.parameters = {
            "type": "object",
            "properties": {"label": {"type": "string"}, "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["label", "path", "content"],
        }

    def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None, on_update: Any = None) -> AgentToolResult:
        del tool_call_id, signal, on_update
        path = str(params["path"])
        content = str(params["content"])
        directory = path.rsplit("/", 1)[0] if "/" in path else "."
        result = self.executor.exec(
            f"mkdir -p {_shell_escape(directory)} && printf '%s' {_shell_escape(content)} > {_shell_escape(path)}",
            ExecOptions(),
        )
        if result.code != 0:
            raise RuntimeError(result.stderr or f"Failed to write file: {path}")
        return AgentToolResult(content=[{"type": "text", "text": f"Successfully wrote {len(content)} bytes to {path}"}], details=None)


def create_write_tool(executor: Any) -> WriteTool:
    return WriteTool(executor)
