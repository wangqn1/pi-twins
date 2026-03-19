from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from typing import Any

from agent import AgentToolResult

from ..sandbox import ExecOptions


def _shell_escape(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


@dataclass
class EditTool:
    executor: Any
    name: str = "edit"
    label: str = "edit"
    description: str = "Edit a file by replacing exact text. Use for surgical changes."
    parameters: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.parameters = {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "path": {"type": "string"},
                "oldText": {"type": "string"},
                "newText": {"type": "string"},
            },
            "required": ["label", "path", "oldText", "newText"],
        }

    def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None, on_update: Any = None) -> AgentToolResult:
        del tool_call_id, signal, on_update
        path = str(params["path"])
        old_text = str(params["oldText"])
        new_text = str(params["newText"])
        read_result = self.executor.exec(f"cat {_shell_escape(path)}", ExecOptions())
        if read_result.code != 0:
            raise RuntimeError(read_result.stderr or f"File not found: {path}")
        content = read_result.stdout
        occurrences = content.count(old_text)
        if occurrences == 0:
            raise RuntimeError(f"Could not find the exact text in {path}. The old text must match exactly including all whitespace and newlines.")
        if occurrences > 1:
            raise RuntimeError(f"Found {occurrences} occurrences of the text in {path}. The text must be unique. Please provide more context to make it unique.")
        updated = content.replace(old_text, new_text, 1)
        if updated == content:
            raise RuntimeError(f"No changes made to {path}.")
        write_result = self.executor.exec(f"printf '%s' {_shell_escape(updated)} > {_shell_escape(path)}", ExecOptions())
        if write_result.code != 0:
            raise RuntimeError(write_result.stderr or f"Failed to write file: {path}")
        diff = "".join(unified_diff(content.splitlines(keepends=True), updated.splitlines(keepends=True), fromfile=path, tofile=path))
        return AgentToolResult(
            content=[{"type": "text", "text": f"Successfully replaced text in {path}. Changed {len(old_text)} characters to {len(new_text)} characters."}],
            details={"diff": diff},
        )


def create_edit_tool(executor: Any) -> EditTool:
    return EditTool(executor)
