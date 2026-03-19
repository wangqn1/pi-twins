from __future__ import annotations

from ai.api_registry import APIProvider, clear_api_providers, register_api_provider

from .anthropic import stream_anthropic, stream_simple_anthropic
from .openai_completions import stream_openai_completions, stream_simple_openai_completions


def register_built_in_api_providers() -> None:
    register_api_provider(
        APIProvider(
            api="anthropic-messages",
            stream=stream_anthropic,
            stream_simple=stream_simple_anthropic,
        )
    )
    register_api_provider(
        APIProvider(
            api="openai-completions",
            stream=stream_openai_completions,
            stream_simple=stream_simple_openai_completions,
        )
    )


def reset_api_providers() -> None:
    clear_api_providers()
    register_built_in_api_providers()


register_built_in_api_providers()
