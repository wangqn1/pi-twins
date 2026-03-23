# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from .api_registry import get_api_provider
from .event_stream import AssistantMessageEventStream
from .providers.register_builtins import register_built_in_api_providers
from .types import AssistantMessage, LLMContext, Model, SimpleStreamOptions, StreamOptions

register_built_in_api_providers()


def _resolve_provider(api: str):
    provider = get_api_provider(api)
    if provider is None:
        raise RuntimeError(f"No API provider registered for api: {api}")
    return provider


def stream(model: Model, context: LLMContext, options: StreamOptions | None = None) -> AssistantMessageEventStream:
    provider = _resolve_provider(model.api)
    return provider.stream(model, context, options)


def complete(model: Model, context: LLMContext, options: StreamOptions | None = None) -> AssistantMessage:
    return stream(model, context, options).result()


def stream_simple(
    model: Model, context: LLMContext, options: SimpleStreamOptions | None = None
) -> AssistantMessageEventStream:
    provider = _resolve_provider(model.api)
    return provider.stream_simple(model, context, options)


def complete_simple(model: Model, context: LLMContext, options: SimpleStreamOptions | None = None) -> AssistantMessage:
    return stream_simple(model, context, options).result()
