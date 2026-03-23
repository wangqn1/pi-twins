# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal

AssistantStopReason = Literal["stop", "length", "toolUse", "error", "aborted"]
ThinkingLevel = Literal["minimal", "low", "medium", "high", "xhigh"]
CacheRetention = Literal["none", "short", "long"]
Transport = Literal["sse", "websocket", "auto"]
ContentBlock = dict[str, Any]
AssistantMessageEvent = dict[str, Any]


@dataclass
class UsageCost:
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "input": self.input,
            "output": self.output,
            "cacheRead": self.cache_read,
            "cacheWrite": self.cache_write,
            "total": self.total,
        }


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total_tokens: int = 0
    cost: UsageCost = field(default_factory=UsageCost)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "output": self.output,
            "cacheRead": self.cache_read,
            "cacheWrite": self.cache_write,
            "totalTokens": self.total_tokens,
            "cost": self.cost.to_dict(),
        }


@dataclass
class ModelCost:
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "input": self.input,
            "output": self.output,
            "cacheRead": self.cache_read,
            "cacheWrite": self.cache_write,
        }


@dataclass
class Model:
    provider: str
    id: str
    name: str = ""
    api: str = "mock"
    base_url: str = ""
    reasoning: bool = False
    context_window: int = 200_000
    max_tokens: int = 8_192
    input: list[str] = field(default_factory=lambda: ["text"])
    headers: dict[str, str] = field(default_factory=dict)
    cost: ModelCost = field(default_factory=ModelCost)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "id": self.id,
            "name": self.name,
            "api": self.api,
            "baseUrl": self.base_url,
            "reasoning": self.reasoning,
            "contextWindow": self.context_window,
            "maxTokens": self.max_tokens,
            "input": list(self.input),
            "headers": dict(self.headers),
            "cost": self.cost.to_dict(),
        }


@dataclass
class UserMessage:
    content: str | list[ContentBlock]
    timestamp: int
    role: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssistantMessage:
    content: list[ContentBlock]
    api: str
    provider: str
    model: str
    usage: Usage
    stop_reason: AssistantStopReason
    timestamp: int
    role: str = "assistant"
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "role": self.role,
            "content": self.content,
            "api": self.api,
            "provider": self.provider,
            "model": self.model,
            "usage": self.usage.to_dict(),
            "stopReason": self.stop_reason,
            "timestamp": self.timestamp,
        }
        if self.error_message is not None:
            result["errorMessage"] = self.error_message
        return result


@dataclass
class ToolResultMessage:
    tool_call_id: str
    tool_name: str
    content: list[ContentBlock]
    is_error: bool
    timestamp: int
    details: Any = None
    role: str = "toolResult"

    def to_dict(self) -> dict[str, Any]:
        result = {
            "role": self.role,
            "toolCallId": self.tool_call_id,
            "toolName": self.tool_name,
            "content": self.content,
            "isError": self.is_error,
            "timestamp": self.timestamp,
        }
        if self.details is not None:
            result["details"] = self.details
        return result


Message = UserMessage | AssistantMessage | ToolResultMessage


@dataclass
class LLMContext:
    system_prompt: str
    messages: list[Message]
    tools: list[Any] = field(default_factory=list)


@dataclass
class StreamOptions:
    temperature: float | None = None
    max_tokens: int | None = None
    api_key: str | None = None
    signal: Any = None
    transport: Transport = "auto"
    cache_retention: CacheRetention | None = None
    session_id: str | None = None
    on_payload: Callable[[Any, Model], Any | None] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    max_retry_delay_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Test seam for offline parity checks; defaults to urllib transport in providers.
    http_post: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] | None = None
    http_stream: Callable[[str, dict[str, str], dict[str, Any]], list[str] | Any] | None = None


@dataclass
class SimpleStreamOptions(StreamOptions):
    reasoning: ThinkingLevel | None = None
    thinking_budgets: dict[str, int] = field(default_factory=dict)


def text_block(text: str) -> ContentBlock:
    return {"type": "text", "text": text}


def thinking_block(thinking: str) -> ContentBlock:
    return {"type": "thinking", "thinking": thinking}


def tool_call_block(tool_call_id: str, name: str, arguments: dict[str, Any]) -> ContentBlock:
    return {"type": "toolCall", "id": tool_call_id, "name": name, "arguments": arguments}
