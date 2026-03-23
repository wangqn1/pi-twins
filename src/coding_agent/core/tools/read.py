# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass

from .path_utils import resolve_read_path
from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_head
from .types import ToolExecutionError, ToolResult

SUPPORTED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@dataclass
class ReadTool:
    cwd: str

    def run(
        self,
        *,
        path: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> ToolResult:
        absolute_path = resolve_read_path(path, self.cwd)

        try:
            mime_type, _ = mimetypes.guess_type(absolute_path)
            if mime_type in SUPPORTED_IMAGE_MIMES:
                with open(absolute_path, "rb") as handle:
                    encoded = base64.b64encode(handle.read()).decode("ascii")
                return ToolResult(
                    content=[
                        {"type": "text", "text": f"Read image file [{mime_type}]"},
                        {"type": "image", "data": encoded, "mimeType": mime_type},
                    ],
                    details=None,
                )

            with open(absolute_path, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except FileNotFoundError as exc:
            raise ToolExecutionError(f"File not found: {path}") from exc
        except PermissionError as exc:
            raise ToolExecutionError(f"Permission denied: {path}") from exc

        lines = raw.split("\n")
        total_lines = len(lines)

        start = max((offset or 1) - 1, 0)
        if start >= total_lines:
            raise ToolExecutionError(f"Offset {offset} is beyond end of file ({total_lines} lines total)")

        if limit is not None:
            selected = "\n".join(lines[start : start + limit])
            user_limited_lines = len(lines[start : start + limit])
        else:
            selected = "\n".join(lines[start:])
            user_limited_lines = None

        truncation = truncate_head(selected)
        start_line_display = start + 1

        if truncation.first_line_exceeds_limit:
            line_size = format_size(len(lines[start].encode("utf-8")))
            text = (
                f"[Line {start_line_display} is {line_size}, exceeds {format_size(DEFAULT_MAX_BYTES)} limit. "
                f"Use bash to inspect partial bytes.]"
            )
            return ToolResult(content=[{"type": "text", "text": text}], details={"truncation": truncation.to_dict()})

        output = truncation.content
        details: dict[str, object] | None = None

        if truncation.truncated:
            end_line = start_line_display + truncation.output_lines - 1
            next_offset = end_line + 1
            output += f"\n\n[Showing lines {start_line_display}-{end_line} of {total_lines}. Use offset={next_offset} to continue.]"
            details = {"truncation": truncation.to_dict()}
        elif user_limited_lines is not None and start + user_limited_lines < total_lines:
            next_offset = start + user_limited_lines + 1
            remaining = total_lines - (start + user_limited_lines)
            output += f"\n\n[{remaining} more lines in file. Use offset={next_offset} to continue.]"

        return ToolResult(content=[{"type": "text", "text": output}], details=details)

    def run_from_dict(self, payload: dict[str, object]) -> ToolResult:
        return self.run(
            path=str(payload["path"]),
            offset=int(payload["offset"]) if "offset" in payload and payload["offset"] is not None else None,
            limit=int(payload["limit"]) if "limit" in payload and payload["limit"] is not None else None,
        )
