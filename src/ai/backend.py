# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Callable, Protocol

from .types import AssistantMessage, LLMContext, Model, Usage, text_block


@dataclass
class CompleteOptions:
    reasoning: str | None = None
    api_key: str | None = None
    session_id: str | None = None


class LLMBackend(Protocol):
    def complete(self, model: Model, context: LLMContext, options: CompleteOptions | None = None) -> AssistantMessage:
        """Return one assistant message for current context."""


class EchoBackend:
    """Deterministic backend used for local testing and development."""

    def complete(self, model: Model, context: LLMContext, options: CompleteOptions | None = None) -> AssistantMessage:
        last_user_text = ""
        for message in reversed(context.messages):
            if getattr(message, "role", None) != "user":
                continue
            content = getattr(message, "content", "")
            if isinstance(content, str):
                last_user_text = content
            elif isinstance(content, list):
                blocks = [block.get("text", "") for block in content if block.get("type") == "text"]
                last_user_text = "\n".join(blocks)
            break

        return AssistantMessage(
            content=[text_block(f"Echo: {last_user_text}".strip())],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )


class ScriptedBackend:
    """Backend where the caller controls each response for parity tests."""

    def __init__(self, responder: Callable[[Model, LLMContext, CompleteOptions | None], AssistantMessage]) -> None:
        self._responder = responder

    def complete(self, model: Model, context: LLMContext, options: CompleteOptions | None = None) -> AssistantMessage:
        return self._responder(model, context, options)
