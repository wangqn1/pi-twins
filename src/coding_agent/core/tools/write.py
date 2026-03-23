# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .path_utils import resolve_to_cwd
from .types import ToolResult


@dataclass
class WriteTool:
    cwd: str

    def run(self, *, path: str, content: str) -> ToolResult:
        absolute_path = Path(resolve_to_cwd(path, self.cwd))
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_text(content, encoding="utf-8")
        return ToolResult(content=[{"type": "text", "text": f"Successfully wrote {len(content)} bytes to {path}"}])

    def run_from_dict(self, payload: dict[str, object]) -> ToolResult:
        return self.run(path=str(payload["path"]), content=str(payload["content"]))
