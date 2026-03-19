from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class ToolExecutionError(RuntimeError):
    """Raised when a tool fails and should be reported to the caller."""


@dataclass
class ToolResult:
    content: list[dict[str, Any]]
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

