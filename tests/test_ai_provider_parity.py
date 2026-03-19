from __future__ import annotations

import json
from time import time
from typing import Any

import pytest

from ai import (
    APIProvider,
    HTTPRequestError,
    AnthropicOptions,
    AssistantMessage,
    AssistantMessageEventStream,
    LLMContext,
    Model,
    OpenAICompletionsOptions,
    SimpleStreamOptions,
    Usage,
    UserMessage,
    clear_api_providers,
    complete,
    complete_simple,
    register_api_provider,
    reset_api_providers,
    stream_anthropic,
    stream_openai_completions,
    text_block,
    tool_call_block,
)
from coding_agent.core.messages import convert_to_llm


def _assistant(model: Model, text: str = "ok") -> AssistantMessage:
    return AssistantMessage(
        content=[text_block(text)],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(),
        stop_reason="stop",
        timestamp=int(time() * 1000),
    )


def test_api_registry_complete_roundtrip() -> None:
    clear_api_providers()

    def fake_stream(model: Model, context: LLMContext, options: Any = None) -> AssistantMessageEventStream:  # noqa: ANN401
        del context, options
        stream = AssistantMessageEventStream()
        message = _assistant(model, "registry-ok")
        stream.push({"type": "start", "partial": message})
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})
        stream.end(message)
        return stream

    register_api_provider(APIProvider(api="mock-api", stream=fake_stream, stream_simple=fake_stream))
    model = Model(provider="mock", id="echo", api="mock-api")
    context = LLMContext(system_prompt="", messages=[], tools=[])
    result = complete(model, context)
    assert result.content[0]["text"] == "registry-ok"

    reset_api_providers()


def test_openai_provider_payload_and_toolcall_mapping() -> None:
    reset_api_providers()
    captured: dict[str, Any] = {}

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "ready",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "read", "arguments": '{"path":"README.md"}'},
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 2},
            },
        }

    model = Model(
        provider="openai",
        id="gpt-test",
        api="openai-completions",
        base_url="https://api.openai.com/v1",
    )
    context = LLMContext(
        system_prompt="sys",
        messages=[UserMessage(content=[text_block("hello")], timestamp=1)],
        tools=[{"name": "read", "description": "Read file", "parameters": {"type": "object"}}],
    )
    options = OpenAICompletionsOptions(api_key="test-key", http_post=fake_post, max_tokens=256)
    result = complete(model, context, options)

    assert captured["url"].endswith("/chat/completions")
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert captured["payload"]["tools"][0]["function"]["name"] == "read"
    assert result.stop_reason == "toolUse"
    assert result.content[0]["type"] == "text"
    assert result.content[1] == tool_call_block("call_1", "read", {"path": "README.md"})
    assert result.usage.input == 10
    assert result.usage.cache_read == 2


def test_anthropic_provider_payload_and_stop_reason_mapping() -> None:
    reset_api_providers()
    captured: dict[str, Any] = {}

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "content": [
                {"type": "text", "text": "working"},
                {"type": "tool_use", "id": "tc_1", "name": "grep", "input": {"pattern": "TODO"}},
            ],
            "usage": {"input_tokens": 8, "output_tokens": 6},
            "stop_reason": "tool_use",
        }

    model = Model(
        provider="anthropic",
        id="claude-test",
        api="anthropic-messages",
        base_url="https://api.anthropic.com/v1",
    )
    context = LLMContext(system_prompt="system", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    options = AnthropicOptions(api_key="anthropic-key", http_post=fake_post, max_tokens=512)
    result = complete(model, context, options)

    assert captured["url"].endswith("/messages")
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["payload"]["system"] == "system"
    assert result.stop_reason == "toolUse"
    assert result.content[1] == tool_call_block("tc_1", "grep", {"pattern": "TODO"})


def test_convert_to_llm_supports_user_messages_with_attachments() -> None:
    converted = convert_to_llm(
        [
            {
                "role": "user-with-attachments",
                "content": "Describe this screenshot",
                "attachments": [
                    {
                        "type": "image",
                        "fileName": "screen.png",
                        "mimeType": "image/png",
                        "content": "ZmFrZS1pbWFnZQ==",
                    },
                    {
                        "type": "document",
                        "fileName": "notes.txt",
                        "mimeType": "text/plain",
                        "content": "ZmFrZS10ZXh0",
                        "extractedText": "hello attachment",
                    },
                ],
                "timestamp": 123,
            }
        ]
    )

    assert len(converted) == 1
    assert converted[0].role == "user"
    assert converted[0].content[0] == text_block("Describe this screenshot")
    assert converted[0].content[1] == {"type": "image", "data": "ZmFrZS1pbWFnZQ==", "mimeType": "image/png"}
    assert converted[0].content[2]["type"] == "text"
    assert "hello attachment" in converted[0].content[2]["text"]


def test_openai_provider_payload_supports_multimodal_user_content() -> None:
    reset_api_providers()
    captured: dict[str, Any] = {}

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": "seen"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }

    model = Model(provider="openai", id="gpt-test", api="openai-completions")
    context = LLMContext(
        system_prompt="",
        messages=[
            UserMessage(
                content=[
                    text_block("what is in this image?"),
                    {"type": "image", "data": "ZmFrZS1pbWFnZQ==", "mimeType": "image/png"},
                ],
                timestamp=1,
            )
        ],
        tools=[],
    )
    result = complete(model, context, OpenAICompletionsOptions(api_key="test-key", http_post=fake_post))

    user_payload = captured["payload"]["messages"][0]
    assert user_payload["role"] == "user"
    assert user_payload["content"][0] == {"type": "text", "text": "what is in this image?"}
    assert user_payload["content"][1]["type"] == "image_url"
    assert user_payload["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result.content[0]["text"] == "seen"


def test_anthropic_provider_payload_supports_multimodal_user_content() -> None:
    reset_api_providers()
    captured: dict[str, Any] = {}

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "content": [{"type": "text", "text": "seen"}],
            "usage": {"input_tokens": 8, "output_tokens": 6},
            "stop_reason": "end_turn",
        }

    model = Model(provider="anthropic", id="claude-test", api="anthropic-messages")
    context = LLMContext(
        system_prompt="",
        messages=[
            UserMessage(
                content=[
                    text_block("read this screenshot"),
                    {"type": "image", "data": "ZmFrZS1pbWFnZQ==", "mimeType": "image/png"},
                ],
                timestamp=1,
            )
        ],
        tools=[],
    )
    result = complete(model, context, AnthropicOptions(api_key="anthropic-key", http_post=fake_post))

    user_payload = captured["payload"]["messages"][0]
    assert user_payload["role"] == "user"
    assert user_payload["content"][0] == {"type": "text", "text": "read this screenshot"}
    assert user_payload["content"][1]["type"] == "image"
    assert user_payload["content"][1]["source"]["type"] == "base64"
    assert user_payload["content"][1]["source"]["media_type"] == "image/png"
    assert result.content[0]["text"] == "seen"


def test_openai_provider_parses_multimodal_assistant_content() -> None:
    reset_api_providers()

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        del url, headers, payload
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": [
                            {"type": "text", "text": "here"},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZmFrZS1pbWFnZQ=="}},
                        ]
                    },
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }

    model = Model(provider="openai", id="gpt-test", api="openai-completions")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    result = complete(model, context, OpenAICompletionsOptions(api_key="test-key", http_post=fake_post))

    assert result.content[0] == text_block("here")
    assert result.content[1] == {"type": "image", "data": "ZmFrZS1pbWFnZQ==", "mimeType": "image/png"}


def test_anthropic_provider_parses_image_blocks_in_response() -> None:
    reset_api_providers()

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        del url, headers, payload
        return {
            "content": [
                {"type": "text", "text": "working"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "ZmFrZS1pbWFnZQ==",
                    },
                },
            ],
            "usage": {"input_tokens": 8, "output_tokens": 6},
            "stop_reason": "end_turn",
        }

    model = Model(provider="anthropic", id="claude-test", api="anthropic-messages")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    result = complete(model, context, AnthropicOptions(api_key="anthropic-key", http_post=fake_post))

    assert result.content[0] == text_block("working")
    assert result.content[1] == {"type": "image", "data": "ZmFrZS1pbWFnZQ==", "mimeType": "image/png"}


def test_openai_stream_emits_text_and_toolcall_deltas() -> None:
    reset_api_providers()

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        del url, headers, payload
        return {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "ready",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "read", "arguments": '{"path":"README.md"}'},
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 3},
        }

    model = Model(provider="openai", id="gpt-test", api="openai-completions")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    stream = stream_openai_completions(model, context, OpenAICompletionsOptions(api_key="k", http_post=fake_post))
    event_types = [event["type"] for event in stream]

    assert event_types == [
        "start",
        "text_start",
        "text_delta",
        "text_end",
        "toolcall_start",
        "toolcall_delta",
        "toolcall_end",
        "done",
    ]
    assert stream.result().content[1] == tool_call_block("call_1", "read", {"path": "README.md"})


def test_anthropic_stream_emits_text_and_toolcall_deltas() -> None:
    reset_api_providers()

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        del url, headers, payload
        return {
            "content": [
                {"type": "text", "text": "working"},
                {"type": "tool_use", "id": "tc_1", "name": "grep", "input": {"pattern": "TODO"}},
            ],
            "usage": {"input_tokens": 8, "output_tokens": 6},
            "stop_reason": "tool_use",
        }

    model = Model(provider="anthropic", id="claude-test", api="anthropic-messages")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    stream = stream_anthropic(model, context, AnthropicOptions(api_key="k", http_post=fake_post))
    event_types = [event["type"] for event in stream]

    assert event_types == [
        "start",
        "text_start",
        "text_delta",
        "text_end",
        "toolcall_start",
        "toolcall_delta",
        "toolcall_end",
        "done",
    ]
    assert stream.result().content[1] == tool_call_block("tc_1", "grep", {"pattern": "TODO"})


def test_openai_stream_http_stream_parses_sse_deltas() -> None:
    reset_api_providers()

    def fake_stream(url: str, headers: dict[str, str], payload: dict[str, Any]) -> list[str]:
        assert url.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer k"
        assert payload["stream"] is True
        first_tool_delta = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read", "arguments": '{"path":"README'},
                            }
                        ]
                    }
                }
            ]
        }
        second_tool_delta = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": '.md"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 3},
        }
        return [
            f"data: {json.dumps({'choices': [{'delta': {'content': 'hel'}}]})}\n",
            f"data: {json.dumps({'choices': [{'delta': {'content': 'lo'}}]})}\n",
            f"data: {json.dumps(first_tool_delta)}\n",
            f"data: {json.dumps(second_tool_delta)}\n",
            "data: [DONE]\n",
        ]

    model = Model(provider="openai", id="gpt-test", api="openai-completions")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    stream = stream_openai_completions(model, context, OpenAICompletionsOptions(api_key="k", http_stream=fake_stream))
    event_types = [event["type"] for event in stream]
    result = stream.result()

    assert event_types == [
        "start",
        "text_start",
        "text_delta",
        "text_delta",
        "text_end",
        "toolcall_start",
        "toolcall_delta",
        "toolcall_delta",
        "toolcall_end",
        "done",
    ]
    assert result.content[0]["text"] == "hello"
    assert result.content[1] == tool_call_block("call_1", "read", {"path": "README.md"})


def test_anthropic_stream_http_stream_parses_sse_deltas() -> None:
    reset_api_providers()

    def fake_stream(url: str, headers: dict[str, str], payload: dict[str, Any]) -> list[str]:
        assert url.endswith("/messages")
        assert headers["x-api-key"] == "k"
        assert payload["stream"] is True
        return [
            'event: message_start\n',
            'data: {"message":{"usage":{"input_tokens":8,"output_tokens":0}}}\n',
            "\n",
            'event: content_block_start\n',
            'data: {"index":0,"content_block":{"type":"text"}}\n',
            "\n",
            'event: content_block_delta\n',
            'data: {"index":0,"delta":{"type":"text_delta","text":"work"}}\n',
            "\n",
            'event: content_block_delta\n',
            'data: {"index":0,"delta":{"type":"text_delta","text":"ing"}}\n',
            "\n",
            'event: content_block_stop\n',
            'data: {"index":0}\n',
            "\n",
            'event: content_block_start\n',
            'data: {"index":1,"content_block":{"type":"tool_use","id":"tc_1","name":"grep","input":{}}}\n',
            "\n",
            'event: content_block_delta\n',
            'data: {"index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"pattern\\":\\"TODO\\"}"}}\n',
            "\n",
            'event: content_block_stop\n',
            'data: {"index":1}\n',
            "\n",
            'event: message_delta\n',
            'data: {"delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":6}}\n',
            "\n",
        ]

    model = Model(provider="anthropic", id="claude-test", api="anthropic-messages")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    stream = stream_anthropic(model, context, AnthropicOptions(api_key="k", http_stream=fake_stream))
    event_types = [event["type"] for event in stream]
    result = stream.result()

    assert event_types == [
        "start",
        "text_start",
        "text_delta",
        "text_delta",
        "text_end",
        "toolcall_start",
        "toolcall_delta",
        "toolcall_end",
        "done",
    ]
    assert result.content[0]["text"] == "working"
    assert result.content[1] == tool_call_block("tc_1", "grep", {"pattern": "TODO"})


def test_complete_simple_uses_env_api_key_for_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_api_providers()
    captured: dict[str, Any] = {}

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": "env-key-ok"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")
    model = Model(provider="openai", id="gpt-test", api="openai-completions")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    result = complete_simple(model, context, SimpleStreamOptions(http_post=fake_post))
    assert captured["headers"]["Authorization"] == "Bearer env-openai-key"
    assert result.content[0]["text"] == "env-key-ok"


def test_complete_simple_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_api_providers()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model = Model(provider="openai", id="gpt-test", api="openai-completions")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    with pytest.raises(RuntimeError):
        complete_simple(model, context)


def test_openai_provider_retries_retryable_errors() -> None:
    reset_api_providers()
    calls = {"count": 0}

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        del url, headers, payload
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPRequestError(
                message="rate limit",
                status=429,
                headers={"Retry-After": "0"},
            )
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": "retry-ok"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    model = Model(provider="openai", id="gpt-test", api="openai-completions")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    result = complete(model, context, OpenAICompletionsOptions(api_key="k", http_post=fake_post))
    assert calls["count"] == 2
    assert result.stop_reason == "stop"
    assert result.content[0]["text"] == "retry-ok"


def test_openai_provider_retry_delay_cap_surfaces_error() -> None:
    reset_api_providers()

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        del url, headers, payload
        raise HTTPRequestError(
            message="rate limit",
            status=429,
            headers={"Retry-After": "120"},
        )

    model = Model(provider="openai", id="gpt-test", api="openai-completions")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hello", timestamp=1)], tools=[])
    result = complete(
        model,
        context,
        OpenAICompletionsOptions(api_key="k", http_post=fake_post, max_retry_delay_ms=1000),
    )
    assert result.stop_reason == "error"
    assert result.error_message is not None
    assert "Server requested" in result.error_message
