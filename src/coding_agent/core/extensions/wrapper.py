# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent import AgentToolResult

from .runner import ExtensionRunner
from .types import RegisteredTool


@dataclass
class _RegisteredToolAdapter:
    registered_tool: RegisteredTool
    runner: ExtensionRunner

    @property
    def name(self) -> str:
        return self.registered_tool.definition.name

    @property
    def label(self) -> str:
        return self.registered_tool.definition.label

    @property
    def description(self) -> str:
        return self.registered_tool.definition.description

    def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None, on_update: Any = None) -> AgentToolResult:
        execute = self.registered_tool.definition.execute
        if execute is None:
            raise RuntimeError(f"Extension tool {self.name} is missing an execute handler")
        return execute(tool_call_id, params, signal, on_update, self.runner.create_context())


def wrap_registered_tool(registered_tool: RegisteredTool, runner: ExtensionRunner) -> _RegisteredToolAdapter:
    return _RegisteredToolAdapter(registered_tool=registered_tool, runner=runner)


def wrap_registered_tools(registered_tools: list[RegisteredTool], runner: ExtensionRunner) -> list[_RegisteredToolAdapter]:
    return [wrap_registered_tool(tool, runner) for tool in registered_tools]


@dataclass
class _WrappedAgentTool:
    tool: Any

    @property
    def name(self) -> str:
        return str(self.tool.name)

    @property
    def label(self) -> str:
        return str(self.tool.label)

    @property
    def description(self) -> str:
        return str(self.tool.description)

    def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None, on_update: Any = None) -> AgentToolResult:
        return self.tool.execute(tool_call_id, params, signal, on_update)


def wrap_tool_with_extensions(tool: Any, runner: ExtensionRunner) -> _WrappedAgentTool:
    del runner
    return _WrappedAgentTool(tool=tool)


def wrap_tools_with_extensions(tools: list[Any], runner: ExtensionRunner) -> list[_WrappedAgentTool]:
    return [wrap_tool_with_extensions(tool, runner) for tool in tools]
