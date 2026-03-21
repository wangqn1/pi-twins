from __future__ import annotations

import json
from dataclasses import dataclass
from time import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai.env_api_keys import get_env_api_key
from ai.event_stream import AssistantMessageEventStream, emit_assistant_message_events
from ai.models import calculate_cost
from ai.types import (
    AssistantMessage,
    AssistantStopReason,
    LLMContext,
    Model,
    SimpleStreamOptions,
    StreamOptions,
    Usage,
    text_block,
    thinking_block,
    tool_call_block,
)

from .simple_options import build_base_options
from .retry import HTTPRequestError, request_with_retry


@dataclass
class AnthropicOptions(StreamOptions):
    thinking_enabled: bool | None = None
    thinking_budget_tokens: int | None = None
    effort: str | None = None
    interleaved_thinking: bool | None = None
    tool_choice: str | dict[str, Any] | None = None


def _map_stop_reason(value: str | None) -> AssistantStopReason:
    if value in {"end_turn", "stop_sequence"}:
        return "stop"
    if value == "max_tokens":
        return "length"
    if value == "tool_use":
        return "toolUse"
    return "stop"


def _resolve_url(model: Model) -> str:
    if model.base_url:
        if model.base_url.endswith("/messages"):
            return model.base_url
        return model.base_url.rstrip("/") + "/messages"
    return "https://api.anthropic.com/v1/messages"


def _request_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, method="POST")
    for key, value in headers.items():
        request.add_header(key, value)

    try:
        with urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPRequestError(
            message=f"Anthropic request failed with HTTP {exc.code}: {detail or exc.reason}",
            status=int(exc.code),
            headers={k: str(v) for k, v in exc.headers.items()},
        ) from exc
    except URLError as exc:
        raise HTTPRequestError(
            message=f"Anthropic request failed: {exc.reason}",
            network_error=True,
        ) from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Anthropic response is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("Anthropic response root must be an object")
    return decoded


def _request_sse(url: str, headers: dict[str, str], payload: dict[str, Any]) -> list[str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, method="POST")
    for key, value in headers.items():
        request.add_header(key, value)

    try:
        with urlopen(request, timeout=120) as response:
            return [raw.decode("utf-8") for raw in response]
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPRequestError(
            message=f"Anthropic request failed with HTTP {exc.code}: {detail or exc.reason}",
            status=int(exc.code),
            headers={k: str(v) for k, v in exc.headers.items()},
        ) from exc
    except URLError as exc:
        raise HTTPRequestError(
            message=f"Anthropic request failed: {exc.reason}",
            network_error=True,
        ) from exc


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        items: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                items.append(str(block.get("text", "")))
        return "\n".join(items)
    return str(content)


def _image_block_from_anthropic_source(source: Any) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    source_type = str(source.get("type", ""))
    if source_type == "base64":
        data = source.get("data")
        mime_type = source.get("media_type") or source.get("mediaType") or "image/png"
        if data:
            return {"type": "image", "data": str(data), "mimeType": str(mime_type)}
        return None
    url = source.get("url")
    if isinstance(url, str) and url:
        return {"type": "image", "url": url}
    return None


def _serialize_anthropic_user_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    serialized: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            serialized.append({"type": "text", "text": str(block.get("text", ""))})
        elif block_type == "image":
            data = block.get("data")
            mime_type = block.get("mimeType") or block.get("mime_type") or "image/png"
            if data:
                serialized.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": str(mime_type),
                            "data": str(data),
                        },
                    }
                )

    if not serialized:
        return _text_from_content(content)
    return serialized


def _serialize_anthropic_tool_result_content(content: Any) -> str | list[dict[str, Any]]:
    serialized = _serialize_anthropic_user_content(content)
    if isinstance(serialized, list):
        return serialized
    return str(serialized)


def _serialize_messages(context: LLMContext) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for message in context.messages:
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if role == "user":
            content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
            serialized.append({"role": "user", "content": _serialize_anthropic_user_content(content)})
            continue
        if role == "assistant":
            blocks = message.get("content") if isinstance(message, dict) else getattr(message, "content", [])
            content_blocks: list[dict[str, Any]] = []
            if isinstance(blocks, list):
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        content_blocks.append({"type": "text", "text": str(block.get("text", ""))})
                    elif block.get("type") == "thinking":
                        content_blocks.append({"type": "thinking", "thinking": str(block.get("thinking", ""))})
                    elif block.get("type") == "toolCall":
                        content_blocks.append(
                            {
                                "type": "tool_use",
                                "id": str(block.get("id", "")),
                                "name": str(block.get("name", "")),
                                "input": block.get("arguments", {}),
                            }
                        )
            serialized.append({"role": "assistant", "content": content_blocks or [{"type": "text", "text": ""}]})
            continue
        if role == "toolResult":
            tool_call_id = message.get("toolCallId") if isinstance(message, dict) else getattr(message, "tool_call_id", "")
            is_error = bool(message.get("isError")) if isinstance(message, dict) else bool(getattr(message, "is_error", False))
            content = message.get("content") if isinstance(message, dict) else getattr(message, "content", [])
            serialized.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(tool_call_id),
                            "content": _serialize_anthropic_tool_result_content(content),
                            "is_error": is_error,
                        }
                    ],
                }
            )
    return serialized


def _serialize_tools(context: LLMContext) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for tool in context.tools:
        if isinstance(tool, dict):
            name = tool.get("name")
            description = tool.get("description", "")
            schema = tool.get("parameters", tool.get("input_schema", {}))
        else:
            name = getattr(tool, "name", None)
            description = getattr(tool, "description", "")
            schema = getattr(tool, "parameters", getattr(tool, "input_schema", {}))
        if not name:
            continue
        payload.append(
            {
                "name": str(name),
                "description": str(description),
                "input_schema": schema if isinstance(schema, dict) else {},
            }
        )
    return payload


def _usage_from_response(response: dict[str, Any], model: Model) -> Usage:
    usage_payload = response.get("usage", {})
    if not isinstance(usage_payload, dict):
        usage_payload = {}

    usage = Usage(
        input=int(usage_payload.get("input_tokens", 0) or 0),
        output=int(usage_payload.get("output_tokens", 0) or 0),
        cache_read=int(usage_payload.get("cache_read_input_tokens", 0) or 0),
        cache_write=int(usage_payload.get("cache_creation_input_tokens", 0) or 0),
    )
    usage.total_tokens = usage.input + usage.output + usage.cache_read + usage.cache_write
    calculate_cost(model, usage)
    return usage


def _assistant_from_response(response: dict[str, Any], model: Model) -> AssistantMessage:
    content = response.get("content", [])
    if not isinstance(content, list):
        content = []

    blocks: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            blocks.append(text_block(str(block.get("text", ""))))
        elif block_type == "image":
            image_block = _image_block_from_anthropic_source(block.get("source", {}))
            if image_block is not None:
                blocks.append(image_block)
        elif block_type == "thinking":
            blocks.append(thinking_block(str(block.get("thinking", ""))))
        elif block_type == "tool_use":
            blocks.append(
                tool_call_block(
                    tool_call_id=str(block.get("id", "")),
                    name=str(block.get("name", "")),
                    arguments=block.get("input", {}) if isinstance(block.get("input"), dict) else {},
                )
            )

    stop_reason = response.get("stop_reason") if isinstance(response.get("stop_reason"), str) else None
    return AssistantMessage(
        content=blocks,
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=_usage_from_response(response, model),
        stop_reason=_map_stop_reason(stop_reason),
        timestamp=int(time() * 1000),
    )


def _iter_sse_events(lines: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_name: str | None = None
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_lines
        if event_name is None:
            data_lines = []
            return
        payload_text = "\n".join(data_lines).strip()
        payload: dict[str, Any] = {}
        if payload_text:
            decoded = json.loads(payload_text)
            if isinstance(decoded, dict):
                payload = decoded
        payload["type"] = event_name
        events.append(payload)
        event_name = None
        data_lines = []

    for raw in lines:
        line = raw.rstrip("\n")
        if not line:
            flush()
            continue
        if line.startswith("event: "):
            event_name = line[7:].strip()
        elif line.startswith("data: "):
            data_lines.append(line[6:])
    flush()
    return events


def _stream_anthropic_from_sse(
    stream: AssistantMessageEventStream,
    output: AssistantMessage,
    lines: list[str],
    model: Model,
    signal: Any,
) -> None:
    stream.push({"type": "start", "partial": output})
    block_map: dict[int, tuple[int, dict[str, Any]]] = {}

    for event in _iter_sse_events(lines):
        if signal is not None and getattr(signal, "aborted", False):
            raise RuntimeError("Request was aborted")

        event_type = event.get("type")
        if event_type == "message_start":
            message = event.get("message", {})
            usage = message.get("usage", {}) if isinstance(message, dict) else {}
            if isinstance(usage, dict):
                output.usage = Usage(
                    input=int(usage.get("input_tokens", 0) or 0),
                    output=int(usage.get("output_tokens", 0) or 0),
                    cache_read=int(usage.get("cache_read_input_tokens", 0) or 0),
                    cache_write=int(usage.get("cache_creation_input_tokens", 0) or 0),
                )
                output.usage.total_tokens = (
                    output.usage.input + output.usage.output + output.usage.cache_read + output.usage.cache_write
                )
                calculate_cost(model, output.usage)
            continue

        if event_type == "content_block_start":
            content_block = event.get("content_block", {})
            if not isinstance(content_block, dict):
                continue
            index = int(event.get("index", len(block_map)))
            block_type = content_block.get("type")
            if block_type == "text":
                block = {"type": "text", "text": ""}
                output.content.append(block)
                content_index = len(output.content) - 1
                block_map[index] = (content_index, block)
                stream.push({"type": "text_start", "contentIndex": content_index, "partial": output})
            elif block_type == "thinking":
                block = {"type": "thinking", "thinking": "", "thinkingSignature": ""}
                output.content.append(block)
                content_index = len(output.content) - 1
                block_map[index] = (content_index, block)
                stream.push({"type": "thinking_start", "contentIndex": content_index, "partial": output})
            elif block_type == "redacted_thinking":
                block = {
                    "type": "thinking",
                    "thinking": "[Reasoning redacted]",
                    "thinkingSignature": str(content_block.get("data", "")),
                    "redacted": True,
                }
                output.content.append(block)
                content_index = len(output.content) - 1
                block_map[index] = (content_index, block)
                stream.push({"type": "thinking_start", "contentIndex": content_index, "partial": output})
            elif block_type == "tool_use":
                block = {
                    "type": "toolCall",
                    "id": str(content_block.get("id", "")),
                    "name": str(content_block.get("name", "")),
                    "arguments": content_block.get("input", {}) if isinstance(content_block.get("input"), dict) else {},
                    "_partial_json": "",
                }
                output.content.append(block)
                content_index = len(output.content) - 1
                block_map[index] = (content_index, block)
                stream.push({"type": "toolcall_start", "contentIndex": content_index, "partial": output})
            elif block_type == "image":
                image_block = _image_block_from_anthropic_source(content_block.get("source", {}))
                if image_block is not None:
                    output.content.append(image_block)
            continue

        if event_type == "content_block_delta":
            index = int(event.get("index", -1))
            if index not in block_map:
                continue
            content_index, block = block_map[index]
            delta = event.get("delta", {})
            if not isinstance(delta, dict):
                continue
            delta_type = delta.get("type")
            if delta_type == "text_delta" and block.get("type") == "text":
                text = str(delta.get("text", ""))
                block["text"] += text
                stream.push({"type": "text_delta", "contentIndex": content_index, "delta": text, "partial": output})
            elif delta_type == "thinking_delta" and block.get("type") == "thinking":
                thinking = str(delta.get("thinking", ""))
                block["thinking"] += thinking
                stream.push(
                    {"type": "thinking_delta", "contentIndex": content_index, "delta": thinking, "partial": output}
                )
            elif delta_type == "input_json_delta" and block.get("type") == "toolCall":
                partial_json = str(delta.get("partial_json", ""))
                block["_partial_json"] += partial_json
                try:
                    parsed = json.loads(block["_partial_json"])
                except json.JSONDecodeError:
                    parsed = {}
                if isinstance(parsed, dict):
                    block["arguments"] = parsed
                stream.push(
                    {"type": "toolcall_delta", "contentIndex": content_index, "delta": partial_json, "partial": output}
                )
            elif delta_type == "signature_delta" and block.get("type") == "thinking":
                block["thinkingSignature"] = f"{block.get('thinkingSignature', '')}{delta.get('signature', '')}"
            continue

        if event_type == "content_block_stop":
            index = int(event.get("index", -1))
            if index not in block_map:
                continue
            content_index, block = block_map[index]
            if block.get("type") == "text":
                stream.push({"type": "text_end", "contentIndex": content_index, "content": block.get("text", ""), "partial": output})
            elif block.get("type") == "thinking":
                stream.push(
                    {
                        "type": "thinking_end",
                        "contentIndex": content_index,
                        "content": block.get("thinking", ""),
                        "partial": output,
                    }
                )
            elif block.get("type") == "toolCall":
                block.pop("_partial_json", None)
                stream.push({"type": "toolcall_end", "contentIndex": content_index, "toolCall": block, "partial": output})
            continue

        if event_type == "message_delta":
            delta = event.get("delta", {})
            if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
                output.stop_reason = _map_stop_reason(delta["stop_reason"])
            usage = event.get("usage", {})
            if isinstance(usage, dict):
                if usage.get("input_tokens") is not None:
                    output.usage.input = int(usage.get("input_tokens", 0) or 0)
                if usage.get("output_tokens") is not None:
                    output.usage.output = int(usage.get("output_tokens", 0) or 0)
                if usage.get("cache_read_input_tokens") is not None:
                    output.usage.cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
                if usage.get("cache_creation_input_tokens") is not None:
                    output.usage.cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
                output.usage.total_tokens = (
                    output.usage.input + output.usage.output + output.usage.cache_read + output.usage.cache_write
                )
                calculate_cost(model, output.usage)

    if signal is not None and getattr(signal, "aborted", False):
        raise RuntimeError("Request was aborted")
    if output.stop_reason in {"aborted", "error"}:
        raise RuntimeError(output.error_message or "An unknown error occurred")
    stream.push({"type": "done", "reason": output.stop_reason, "message": output})
    stream.end(output)


def stream_anthropic(
    model: Model,
    context: LLMContext,
    options: AnthropicOptions | StreamOptions | None = None,
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()
    output = AssistantMessage(
        content=[],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(),
        stop_reason="stop",
        timestamp=int(time() * 1000),
    )

    try:
        option = options if isinstance(options, AnthropicOptions) else AnthropicOptions(**(options.__dict__ if options else {}))
        api_key = option.api_key or get_env_api_key(model.provider)
        if not api_key:
            raise RuntimeError(f"No API key for provider: {model.provider}")

        payload: dict[str, Any] = {
            "model": model.id,
            "messages": _serialize_messages(context),
            "max_tokens": option.max_tokens if option.max_tokens is not None else model.max_tokens,
        }
        if context.system_prompt:
            payload["system"] = context.system_prompt
        if option.temperature is not None:
            payload["temperature"] = option.temperature

        tools_payload = _serialize_tools(context)
        if tools_payload:
            payload["tools"] = tools_payload
        if option.tool_choice is not None:
            payload["tool_choice"] = option.tool_choice

        if option.on_payload is not None:
            maybe_payload = option.on_payload(payload, model)
            if isinstance(maybe_payload, dict):
                payload = maybe_payload

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            **dict(model.headers),
            **dict(option.headers),
        }
        use_streaming_transport = option.http_stream is not None or option.http_post is None
        if use_streaming_transport:
            payload["stream"] = True
            requester = option.http_stream or _request_sse
            response_lines = request_with_retry(
                lambda: list(requester(_resolve_url(model), headers, payload)),
                max_retries=3,
                base_delay_ms=2000,
                max_retry_delay_ms=option.max_retry_delay_ms if option.max_retry_delay_ms is not None else 60000,
            )
            _stream_anthropic_from_sse(stream, output, response_lines, model, option.signal)
        else:
            requester = option.http_post or _request_json
            response = request_with_retry(
                lambda: requester(_resolve_url(model), headers, payload),
                max_retries=3,
                base_delay_ms=2000,
                max_retry_delay_ms=option.max_retry_delay_ms if option.max_retry_delay_ms is not None else 60000,
            )
            final_message = _assistant_from_response(response, model)
            emit_assistant_message_events(stream, output, final_message)
    except Exception as exc:  # noqa: BLE001
        output.stop_reason = "error"
        output.error_message = str(exc)
        stream.push({"type": "start", "partial": output})
        stream.push({"type": "error", "reason": output.stop_reason, "error": output})
        stream.end(output)

    return stream


def stream_simple_anthropic(
    model: Model,
    context: LLMContext,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    api_key = (options.api_key if options is not None else None) or get_env_api_key(model.provider)
    if not api_key:
        raise RuntimeError(f"No API key for provider: {model.provider}")

    base = build_base_options(model, options, api_key)
    merged = AnthropicOptions(**base.__dict__)
    if options is not None and options.reasoning is not None:
        merged.thinking_enabled = True
    return stream_anthropic(model, context, merged)
