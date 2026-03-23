# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .event_stream import AssistantMessageEventStream
from .types import LLMContext, Model, SimpleStreamOptions, StreamOptions

StreamFunction = Callable[[Model, LLMContext, StreamOptions | None], AssistantMessageEventStream]
SimpleStreamFunction = Callable[[Model, LLMContext, SimpleStreamOptions | None], AssistantMessageEventStream]


@dataclass
class APIProvider:
    api: str
    stream: StreamFunction
    stream_simple: SimpleStreamFunction


_registry: dict[str, tuple[APIProvider, str | None]] = {}


def _wrap_stream(api: str, handler: StreamFunction) -> StreamFunction:
    def wrapped(model: Model, context: LLMContext, options: StreamOptions | None = None) -> AssistantMessageEventStream:
        if model.api != api:
            raise ValueError(f"Mismatched api: {model.api} expected {api}")
        return handler(model, context, options)

    return wrapped


def _wrap_stream_simple(api: str, handler: SimpleStreamFunction) -> SimpleStreamFunction:
    def wrapped(
        model: Model, context: LLMContext, options: SimpleStreamOptions | None = None
    ) -> AssistantMessageEventStream:
        if model.api != api:
            raise ValueError(f"Mismatched api: {model.api} expected {api}")
        return handler(model, context, options)

    return wrapped


def register_api_provider(provider: APIProvider, source_id: str | None = None) -> None:
    wrapped = APIProvider(
        api=provider.api,
        stream=_wrap_stream(provider.api, provider.stream),
        stream_simple=_wrap_stream_simple(provider.api, provider.stream_simple),
    )
    _registry[provider.api] = (wrapped, source_id)


def get_api_provider(api: str) -> APIProvider | None:
    entry = _registry.get(api)
    return entry[0] if entry is not None else None


def get_api_providers() -> list[APIProvider]:
    return [entry[0] for entry in _registry.values()]


def unregister_api_providers(source_id: str) -> None:
    for api, entry in list(_registry.items()):
        if entry[1] == source_id:
            del _registry[api]


def clear_api_providers() -> None:
    _registry.clear()
