from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .path_utils import resolve_to_cwd
from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_head
from .types import ToolExecutionError, ToolResult

DEFAULT_LIMIT = 500


@dataclass
class LsTool:
    cwd: str

    def run(self, *, path: str | None = None, limit: int = DEFAULT_LIMIT) -> ToolResult:
        directory = Path(resolve_to_cwd(path or ".", self.cwd))
        if not directory.exists():
            raise ToolExecutionError(f"Path not found: {directory}")
        if not directory.is_dir():
            raise ToolExecutionError(f"Not a directory: {directory}")

        entries = sorted(directory.iterdir(), key=lambda item: item.name.lower())
        rendered: list[str] = []
        for entry in entries[: max(limit, 1)]:
            rendered.append(entry.name + ("/" if entry.is_dir() else ""))

        if not rendered:
            return ToolResult(content=[{"type": "text", "text": "(empty directory)"}])

        limit_reached = len(entries) > len(rendered)
        raw = "\n".join(rendered)
        truncation = truncate_head(raw, max_lines=10**9)
        output = truncation.content
        details: dict[str, object] = {}
        notices: list[str] = []

        if limit_reached:
            notices.append(f"{limit} entries limit reached")
            details["entryLimitReached"] = limit
        if truncation.truncated:
            notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
            details["truncation"] = truncation.to_dict()
        if notices:
            output += f"\n\n[{' . '.join(notices)}]"

        return ToolResult(content=[{"type": "text", "text": output}], details=details or None)

    def run_from_dict(self, payload: dict[str, object]) -> ToolResult:
        return self.run(
            path=str(payload["path"]) if "path" in payload and payload["path"] is not None else None,
            limit=int(payload["limit"]) if "limit" in payload and payload["limit"] is not None else DEFAULT_LIMIT,
        )
