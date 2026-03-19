from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent import AgentToolResult

_upload_fn: Callable[[str, str | None], None] | None = None


def set_upload_function(fn: Callable[[str, str | None], None]) -> None:
    global _upload_fn
    _upload_fn = fn


@dataclass
class _AttachTool:
    name: str = "attach"
    label: str = "attach"
    description: str = "Attach a file to your response. Use this to share files, images, or documents with the user."
    parameters: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.parameters = {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "path": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["label", "path"],
        }

    def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None, on_update: Any = None) -> AgentToolResult:
        del tool_call_id, on_update
        if signal is not None and getattr(signal, "aborted", False):
            raise RuntimeError("Operation aborted")
        if _upload_fn is None:
            raise RuntimeError("Upload function not configured")
        absolute_path = str(Path(str(params["path"])).resolve())
        title = str(params["title"]) if params.get("title") is not None else Path(absolute_path).name
        _upload_fn(absolute_path, title)
        return AgentToolResult(content=[{"type": "text", "text": f"Attached file: {title}"}], details=None)


attach_tool = _AttachTool()
