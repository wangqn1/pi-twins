from __future__ import annotations

import tempfile
from dataclasses import dataclass
from typing import Any

from agent import AgentToolResult

from ..sandbox import ExecOptions
from .truncate import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES, format_size, truncate_tail


@dataclass
class BashTool:
    executor: Any
    name: str = "bash"
    label: str = "bash"
    description: str = (
        f"Execute a bash command. Output is truncated to last {DEFAULT_MAX_LINES} lines "
        f"or {DEFAULT_MAX_BYTES // 1024}KB."
    )
    parameters: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.parameters = {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "command": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["label", "command"],
        }

    def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None, on_update: Any = None) -> AgentToolResult:
        del tool_call_id, signal, on_update
        timeout = float(params["timeout"]) if params.get("timeout") is not None else None
        result = self.executor.exec(str(params["command"]), ExecOptions(timeout=timeout))
        output = result.stdout
        if result.stderr:
            output = f"{output}\n{result.stderr}" if output else result.stderr

        temp_file_path: str | None = None
        if len(output.encode("utf-8")) > DEFAULT_MAX_BYTES:
            with tempfile.NamedTemporaryFile(prefix="mom-bash-", suffix=".log", delete=False, mode="w", encoding="utf-8") as handle:
                handle.write(output)
                temp_file_path = handle.name

        truncation = truncate_tail(output)
        text = truncation.content or "(no output)"
        details: dict[str, Any] | None = None
        if truncation.truncated:
            details = {"truncation": truncation.__dict__}
            if temp_file_path:
                details["fullOutputPath"] = temp_file_path
            start_line = truncation.total_lines - truncation.output_lines + 1
            end_line = truncation.total_lines
            if truncation.last_line_partial:
                text += f"\n\n[Showing last {format_size(truncation.output_bytes)} of line {end_line}. Full output: {temp_file_path}]"
            elif truncation.truncated_by == "lines":
                text += f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines}. Full output: {temp_file_path}]"
            else:
                text += f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines} ({format_size(DEFAULT_MAX_BYTES)} limit). Full output: {temp_file_path}]"

        if result.code != 0:
            raise RuntimeError(f"{text}\n\nCommand exited with code {result.code}".strip())
        return AgentToolResult(content=[{"type": "text", "text": text}], details=details)


def create_bash_tool(executor: Any) -> BashTool:
    return BashTool(executor)
