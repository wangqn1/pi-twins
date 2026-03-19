from __future__ import annotations

from agent import ProxyStreamOptions, process_proxy_event, stream_proxy
from ai import AssistantMessage, LLMContext, Model, Usage, UserMessage


def test_process_proxy_event_reconstructs_tool_call_arguments() -> None:
    partial = AssistantMessage(
        content=[],
        api="mock",
        provider="mock",
        model="echo",
        usage=Usage(),
        stop_reason="stop",
        timestamp=1,
    )

    process_proxy_event({"type": "toolcall_start", "contentIndex": 0, "id": "call_1", "toolName": "read"}, partial)
    process_proxy_event({"type": "toolcall_delta", "contentIndex": 0, "delta": '{"path":"README.md"}'}, partial)
    process_proxy_event({"type": "toolcall_end", "contentIndex": 0}, partial)

    assert partial.content[0]["type"] == "toolCall"
    assert partial.content[0]["arguments"] == {"path": "README.md"}


def test_stream_proxy_reconstructs_message_from_sse_events() -> None:
    def fake_stream(url, headers, payload):  # noqa: ANN001
        assert url == "https://proxy.example/api/stream"
        assert headers["Authorization"] == "Bearer token-1"
        assert payload["options"]["reasoning"] == "high"
        return [
            'data: {"type":"start"}\n',
            'data: {"type":"text_start","contentIndex":0}\n',
            'data: {"type":"text_delta","contentIndex":0,"delta":"hello"}\n',
            'data: {"type":"text_end","contentIndex":0}\n',
            'data: {"type":"done","reason":"stop","usage":{"input":1,"output":1,"cache_read":0,"cache_write":0,"total_tokens":2,"cost":{"total":0}}}\n',
        ]

    model = Model(provider="mock", id="echo", api="mock")
    context = LLMContext(system_prompt="", messages=[UserMessage(content="hi", timestamp=1)], tools=[])
    stream = stream_proxy(
        model,
        context,
        ProxyStreamOptions(
            auth_token="token-1",
            proxy_url="https://proxy.example",
            reasoning="high",
            http_stream=fake_stream,
        ),
    )

    result = stream.result()
    assert result.content[0]["text"] == "hello"
    assert result.stop_reason == "stop"
