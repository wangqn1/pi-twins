from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from agent import AgentToolResult

from ..sandbox import ExecOptions
from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_head

IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _shell_escape(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


@dataclass
class ReadTool:
    executor: Any
    name: str = "read"
    label: str = "read"
    description: str = "Read file contents. Supports text files and common image formats."
    parameters: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.parameters = {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "path": {"type": "string"},
                "offset": {"type": "number"},
                "limit": {"type": "number"},
            },
            "required": ["label", "path"],
        }

    def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None, on_update: Any = None) -> AgentToolResult:
        del tool_call_id, signal, on_update
        path = str(params["path"])
        suffix = PurePosixPath(path).suffix.lower()
        mime_type = IMAGE_MIME_TYPES.get(suffix)
        if mime_type:
            result = self.executor.exec(f"base64 < {_shell_escape(path)}", ExecOptions())
            if result.code != 0:
                raise RuntimeError(result.stderr or f"Failed to read file: {path}")
            return AgentToolResult(
                content=[
                    {"type": "text", "text": f"Read image file [{mime_type}]"},
                    {"type": "image", "data": result.stdout.replace('\n', ''), "mimeType": mime_type},
                ],
                details=None,
            )

        count_result = self.executor.exec(f"wc -l < {_shell_escape(path)}", ExecOptions())
        if count_result.code != 0:
            raise RuntimeError(count_result.stderr or f"Failed to read file: {path}")
        total_file_lines = int(count_result.stdout.strip() or "0") + 1
        start_line = max(int(params.get("offset") or 1), 1)
        if start_line > total_file_lines:
            raise RuntimeError(f"Offset {params.get('offset')} is beyond end of file ({total_file_lines} lines total)")
        cmd = f"cat {_shell_escape(path)}" if start_line == 1 else f"tail -n +{start_line} {_shell_escape(path)}"
        result = self.executor.exec(cmd, ExecOptions())
        if result.code != 0:
            raise RuntimeError(result.stderr or f"Failed to read file: {path}")
        selected = result.stdout
        user_limited_lines: int | None = None
        if params.get("limit") is not None:
            limit = int(params["limit"])
            lines = selected.split("\n")
            selected = "\n".join(lines[:limit])
            user_limited_lines = min(limit, len(lines))
        truncation = truncate_head(selected)
        text = truncation.content
        details: dict[str, Any] | None = None
        if truncation.first_line_exceeds_limit:
            line_size = format_size(len(selected.split("\n")[0].encode("utf-8")))
            text = (
                f"[Line {start_line} is {line_size}, exceeds {format_size(DEFAULT_MAX_BYTES)} limit. "
                f"Use bash: sed -n '{start_line}p' {path} | head -c {DEFAULT_MAX_BYTES}]"
            )
            details = {"truncation": truncation.__dict__}
        elif truncation.truncated:
            end_line = start_line + truncation.output_lines - 1
            next_offset = end_line + 1
            text += (
                f"\n\n[Showing lines {start_line}-{end_line} of {total_file_lines}"
                f"{'' if truncation.truncated_by == 'lines' else f' ({format_size(DEFAULT_MAX_BYTES)} limit)'}"
                f". Use offset={next_offset} to continue]"
            )
            details = {"truncation": truncation.__dict__}
        elif user_limited_lines is not None and start_line - 1 + user_limited_lines < total_file_lines:
            remaining = total_file_lines - (start_line - 1 + user_limited_lines)
            text += f"\n\n[{remaining} more lines in file. Use offset={start_line + user_limited_lines} to continue]"
        return AgentToolResult(content=[{"type": "text", "text": text}], details=details)


def create_read_tool(executor: Any) -> ReadTool:
    return ReadTool(executor)
