# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent import AgentToolResult

from .bash import BashTool
from .edit import EditTool
from .find import FindTool
from .grep import GrepTool
from .ls import LsTool
from .read import ReadTool
from .screenshot import ScreenshotTool
from .types import ToolExecutionError, ToolResult
from .write import WriteTool

ToolRunner = Callable[[dict[str, Any]], ToolResult]


@dataclass
class ToolRegistry:
    cwd: str

    def __post_init__(self) -> None:
        self._tools: dict[str, ToolRunner] = {
            "read": ReadTool(self.cwd).run_from_dict,
            "write": WriteTool(self.cwd).run_from_dict,
            "edit": EditTool(self.cwd).run_from_dict,
            "bash": BashTool(self.cwd).run_from_dict,
            "grep": GrepTool(self.cwd).run_from_dict,
            "find": FindTool(self.cwd).run_from_dict,
            "ls": LsTool(self.cwd).run_from_dict,
            "screenshot": ScreenshotTool(self.cwd).run_from_dict,
        }

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    def run(self, name: str, payload: dict[str, Any]) -> ToolResult:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name](payload)


@dataclass
class RegistryToolAdapter:
    registry: ToolRegistry
    name: str
    label: str
    description: str
    parameters: dict[str, Any] | None = None

    def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        del tool_call_id, signal, on_update
        result = self.registry.run(self.name, params)
        return AgentToolResult(content=result.content, details=result.details)


def create_coding_tools(cwd: str) -> list[RegistryToolAdapter]:
    registry = ToolRegistry(cwd)
    descriptions = {
        "read": "Read file content with truncation support.",
        "bash": "Execute shell command in working directory.",
        "edit": "Replace exact text in file.",
        "write": "Write full content to file.",
        "grep": "Search content in files.",
        "find": "Find paths by glob.",
        "ls": "List directory entries.",
        "screenshot": "Capture a macOS screenshot and return it as an image for multimodal analysis.",
    }
    parameters = {
        "screenshot": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Output path for the captured screenshot."},
                "interactive": {
                    "type": "boolean",
                    "description": "Whether to interactively select a region or window.",
                },
            },
            "required": ["path"],
        }
    }
    return [
        RegistryToolAdapter(
            registry=registry,
            name=name,
            label=name,
            description=descriptions.get(name, f"{name} tool"),
            parameters=parameters.get(name),
        )
        for name in registry.list_tools()
    ]


__all__ = [
    "BashTool",
    "EditTool",
    "FindTool",
    "GrepTool",
    "LsTool",
    "ReadTool",
    "RegistryToolAdapter",
    "ScreenshotTool",
    "ToolExecutionError",
    "ToolRegistry",
    "ToolResult",
    "WriteTool",
    "create_coding_tools",
]
