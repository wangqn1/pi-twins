# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any, Callable, Literal, Protocol

from ai import (
    AssistantMessage,
    AssistantMessageEventStream,
    LLMContext,
    Message,
    Model,
    SimpleStreamOptions,
)

ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]
AgentMessage = Message | Any
AgentEvent = dict[str, Any]


class AbortSignal:
    def __init__(self) -> None:
        self._event = Event()

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def throw_if_aborted(self) -> None:
        if self.aborted:
            raise RuntimeError("Request was aborted")


class AbortController:
    def __init__(self) -> None:
        self.signal = AbortSignal()

    def abort(self) -> None:
        self.signal._event.set()


@dataclass
class AgentToolResult:
    content: list[dict[str, Any]]
    details: Any = None


AgentToolUpdateCallback = Callable[[AgentToolResult], None]


class AgentTool(Protocol):
    name: str
    label: str
    description: str

    def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: AbortSignal | None = None,
        on_update: AgentToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        """Run one tool call and return tool result."""


TransformContext = Callable[[list[AgentMessage], AbortSignal | None], list[AgentMessage]]
GetApiKey = Callable[[str], str | None]
QueuedMessagesGetter = Callable[[], list[AgentMessage]]
StreamFn = Callable[[Model, LLMContext, SimpleStreamOptions | None], AssistantMessageEventStream]
BeforeToolCall = Callable[[dict[str, Any], AbortSignal | None], dict[str, Any] | None]
AfterToolCall = Callable[[dict[str, Any], AbortSignal | None], dict[str, Any] | None]


@dataclass
class AgentContext:
    system_prompt: str
    messages: list[AgentMessage]
    tools: list[AgentTool] = field(default_factory=list)


@dataclass
class AgentLoopConfig:
    model: Model
    convert_to_llm: Callable[[list[AgentMessage]], list[Message]]
    stream_fn: StreamFn
    transform_context: TransformContext | None = None
    get_api_key: GetApiKey | None = None
    get_steering_messages: QueuedMessagesGetter | None = None
    get_follow_up_messages: QueuedMessagesGetter | None = None
    before_tool_call: BeforeToolCall | None = None
    after_tool_call: AfterToolCall | None = None
    options: SimpleStreamOptions | None = None
    max_turns: int | None = None
    max_tool_calls: int | None = None


@dataclass
class AgentState:
    system_prompt: str
    model: Model
    thinking_level: ThinkingLevel
    tools: list[AgentTool]
    messages: list[AgentMessage]
    is_streaming: bool = False
    stream_message: AgentMessage | None = None
    pending_tool_calls: set[str] = field(default_factory=set)
    error: str | None = None


def build_error_message(model: Model, error_message: str, *, stop_reason: str = "error") -> AssistantMessage:
    from time import time

    from ai import Usage

    return AssistantMessage(
        content=[],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(),
        stop_reason=stop_reason,  # type: ignore[arg-type]
        error_message=error_message,
        timestamp=int(time() * 1000),
    )
