from __future__ import annotations

from ai.types import Model, SimpleStreamOptions, StreamOptions, ThinkingLevel


def build_base_options(model: Model, options: SimpleStreamOptions | None = None, api_key: str | None = None) -> StreamOptions:
    max_tokens = min(model.max_tokens, 32000)
    if options is not None and options.max_tokens is not None:
        max_tokens = options.max_tokens

    return StreamOptions(
        temperature=options.temperature if options is not None else None,
        max_tokens=max_tokens,
        api_key=api_key or (options.api_key if options is not None else None),
        transport=options.transport if options is not None else "auto",
        cache_retention=options.cache_retention if options is not None else None,
        session_id=options.session_id if options is not None else None,
        on_payload=options.on_payload if options is not None else None,
        headers=dict(options.headers) if options is not None else {},
        max_retry_delay_ms=options.max_retry_delay_ms if options is not None else None,
        metadata=dict(options.metadata) if options is not None else {},
        http_post=options.http_post if options is not None else None,
        http_stream=options.http_stream if options is not None else None,
    )


def clamp_reasoning(effort: ThinkingLevel | None) -> ThinkingLevel | None:
    return "high" if effort == "xhigh" else effort
