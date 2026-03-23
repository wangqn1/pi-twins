# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import re

from .types import AssistantMessage

OVERFLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"prompt is too long", re.IGNORECASE),
    re.compile(r"input is too long for requested model", re.IGNORECASE),
    re.compile(r"exceeds the context window", re.IGNORECASE),
    re.compile(r"input token count.*exceeds the maximum", re.IGNORECASE),
    re.compile(r"maximum prompt length is \d+", re.IGNORECASE),
    re.compile(r"reduce the length of the messages", re.IGNORECASE),
    re.compile(r"maximum context length is \d+ tokens", re.IGNORECASE),
    re.compile(r"exceeds the limit of \d+", re.IGNORECASE),
    re.compile(r"exceeds the available context size", re.IGNORECASE),
    re.compile(r"greater than the context length", re.IGNORECASE),
    re.compile(r"context window exceeds limit", re.IGNORECASE),
    re.compile(r"exceeded model token limit", re.IGNORECASE),
    re.compile(r"too large for model with \d+ maximum context length", re.IGNORECASE),
    re.compile(r"model_context_window_exceeded", re.IGNORECASE),
    re.compile(r"context[_ ]length[_ ]exceeded", re.IGNORECASE),
    re.compile(r"too many tokens", re.IGNORECASE),
    re.compile(r"token limit exceeded", re.IGNORECASE),
)


def is_context_overflow(message: AssistantMessage, context_window: int | None = None) -> bool:
    if message.stop_reason == "error" and message.error_message:
        text = message.error_message
        if any(pattern.search(text) for pattern in OVERFLOW_PATTERNS):
            return True
        if re.search(r"^4(00|13)\s*(status code)?\s*\(no body\)", text, re.IGNORECASE):
            return True

    if context_window and message.stop_reason == "stop":
        input_tokens = int(message.usage.input) + int(message.usage.cache_read)
        if input_tokens > context_window:
            return True
    return False


def get_overflow_patterns() -> list[re.Pattern[str]]:
    return list(OVERFLOW_PATTERNS)
