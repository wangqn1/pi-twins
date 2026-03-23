# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import json
from dataclasses import dataclass
from time import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai.env_api_keys import get_env_api_key
from ai.event_stream import AssistantMessageEventStream, emit_assistant_message_events
from ai.models import calculate_cost, supports_xhigh
from ai.types import (
    AssistantMessage,
    AssistantStopReason,
    LLMContext,
    Model,
    SimpleStreamOptions,
    StreamOptions,
    ToolResultMessage,
    Usage,
    text_block,
    tool_call_block,
)

from .simple_options import build_base_options, clamp_reasoning
from .retry import HTTPRequestError, request_with_retry


@dataclass
class OpenAICompletionsOptions(StreamOptions):
    tool_choice: str | dict[str, Any] | None = None
    reasoning_effort: str | None = None


def _map_stop_reason(value: str | None) -> AssistantStopReason:
    if value == "stop":
        return "stop"
    if value in {"length", "max_tokens"}:
        return "length"
    if value in {"tool_calls", "function_call"}:
        return "toolUse"
    return "stop"


def _resolve_url(model: Model) -> str:
    if model.base_url:
        if model.base_url.endswith("/chat/completions"):
            return model.base_url
        return model.base_url.rstrip("/") + "/chat/completions"
    return "https://api.openai.com/v1/chat/completions"


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
            message=f"OpenAI request failed with HTTP {exc.code}: {detail or exc.reason}",
            status=int(exc.code),
            headers={k: str(v) for k, v in exc.headers.items()},
        ) from exc
    except URLError as exc:
        raise HTTPRequestError(
            message=f"OpenAI request failed: {exc.reason}",
            network_error=True,
        ) from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI response is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("OpenAI response root must be an object")
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
            message=f"OpenAI request failed with HTTP {exc.code}: {detail or exc.reason}",
            status=int(exc.code),
            headers={k: str(v) for k, v in exc.headers.items()},
        ) from exc
    except URLError as exc:
        raise HTTPRequestError(
            message=f"OpenAI request failed: {exc.reason}",
            network_error=True,
        ) from exc


def _extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content)


def _image_block_from_url(url: Any) -> dict[str, Any] | None:
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("data:"):
        header, separator, data = url.partition(",")
        if not separator or not data:
            return None
        mime_type = header[5:]
        if ";base64" in mime_type:
            mime_type = mime_type.split(";base64", 1)[0]
        return {"type": "image", "data": data, "mimeType": mime_type or "image/png"}
    return {"type": "image", "url": url}


def _image_block_from_openai_part(part: dict[str, Any]) -> dict[str, Any] | None:
    part_type = str(part.get("type", ""))
    if part_type in {"image_url", "output_image"}:
        image_url = part.get("image_url") or part.get("imageUrl") or part.get("url")
        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        return _image_block_from_url(image_url)
    if part_type == "image":
        data = part.get("data")
        mime_type = part.get("mimeType") or part.get("mime_type") or "image/png"
        if data:
            return {"type": "image", "data": str(data), "mimeType": str(mime_type)}
        image_url = part.get("url") or part.get("image_url") or part.get("imageUrl")
        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        return _image_block_from_url(image_url)
    return None


def _append_openai_assistant_content_blocks(content_blocks: list[dict[str, Any]], content: Any) -> None:
    if isinstance(content, str):
        if content:
            content_blocks.append(text_block(content))
        return
    if not isinstance(content, list):
        text = str(content) if content is not None else ""
        if text:
            content_blocks.append(text_block(text))
        return

    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type", ""))
        if part_type in {"text", "output_text"}:
            text = part.get("text")
            if isinstance(text, str) and text:
                content_blocks.append(text_block(text))
            continue
        image_block = _image_block_from_openai_part(part)
        if image_block is not None:
            content_blocks.append(image_block)


def _serialize_openai_user_content(content: Any) -> str | list[dict[str, Any]]:
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
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{str(data)}"},
                    }
                )

    if not serialized:
        return _extract_text_from_content(content)
    return serialized


def _tool_result_text(message: ToolResultMessage | dict[str, Any]) -> str:
    content = message.get("content") if isinstance(message, dict) else message.content
    if isinstance(content, list):
        text = [str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text"]
        return "\n".join(text)
    return str(content)


def _serialize_messages(context: LLMContext) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    if context.system_prompt:
        serialized.append({"role": "system", "content": context.system_prompt})

    for message in context.messages:
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if role == "user":
            content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
            serialized.append({"role": "user", "content": _serialize_openai_user_content(content)})
            continue
        if role == "assistant":
            blocks = message.get("content") if isinstance(message, dict) else getattr(message, "content", [])
            content_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            if isinstance(blocks, list):
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        content_parts.append(str(block.get("text", "")))
                    elif block.get("type") == "toolCall":
                        tool_calls.append(
                            {
                                "id": str(block.get("id", "")),
                                "type": "function",
                                "function": {
                                    "name": str(block.get("name", "")),
                                    "arguments": json.dumps(block.get("arguments", {}), ensure_ascii=False),
                                },
                            }
                        )
            item: dict[str, Any] = {"role": "assistant", "content": "\n".join(part for part in content_parts if part)}
            if tool_calls:
                item["tool_calls"] = tool_calls
            serialized.append(item)
            continue
        if role == "toolResult":
            tool_call_id = message.get("toolCallId") if isinstance(message, dict) else getattr(message, "tool_call_id", "")
            serialized.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tool_call_id),
                    "content": _tool_result_text(message),
                }
            )

    return serialized


def _serialize_tools(context: LLMContext) -> list[dict[str, Any]]:
    tools_payload: list[dict[str, Any]] = []
    for tool in context.tools:
        if isinstance(tool, dict):
            name = tool.get("name")
            description = tool.get("description", "")
            parameters = tool.get("parameters", tool.get("input_schema", {}))
        else:
            name = getattr(tool, "name", None)
            description = getattr(tool, "description", "")
            parameters = getattr(tool, "parameters", getattr(tool, "input_schema", {}))
        if not name:
            continue
        tools_payload.append(
            {
                "type": "function",
                "function": {
                    "name": str(name),
                    "description": str(description),
                    "parameters": parameters if isinstance(parameters, dict) else {},
                },
            }
        )
    return tools_payload


def _usage_from_response(response: dict[str, Any], model: Model) -> Usage:
    usage_payload = response.get("usage", {})
    if not isinstance(usage_payload, dict):
        usage_payload = {}

    cached_tokens = 0
    prompt_details = usage_payload.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        cached_tokens = int(prompt_details.get("cached_tokens", 0) or 0)

    prompt_tokens = int(usage_payload.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage_payload.get("completion_tokens", 0) or 0)
    input_tokens = max(prompt_tokens - cached_tokens, 0)
    total = input_tokens + completion_tokens + cached_tokens

    usage = Usage(
        input=input_tokens,
        output=completion_tokens,
        cache_read=cached_tokens,
        cache_write=0,
        total_tokens=total,
    )
    calculate_cost(model, usage)
    return usage


def _assistant_from_response(response: dict[str, Any], model: Model) -> AssistantMessage:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenAI response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("OpenAI response first choice is invalid")

    message = first.get("message", {})
    if not isinstance(message, dict):
        message = {}

    content_blocks: list[dict[str, Any]] = []
    _append_openai_assistant_content_blocks(content_blocks, message.get("content"))

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function_block = tool_call.get("function", {})
            if not isinstance(function_block, dict):
                function_block = {}
            args_raw = function_block.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw if isinstance(args_raw, dict) else {})
            except json.JSONDecodeError:
                args = {}
            content_blocks.append(
                tool_call_block(
                    tool_call_id=str(tool_call.get("id", "")),
                    name=str(function_block.get("name", "")),
                    arguments=args,
                )
            )

    finish_reason = first.get("finish_reason") if isinstance(first.get("finish_reason"), str) else None
    return AssistantMessage(
        content=content_blocks,
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=_usage_from_response(response, model),
        stop_reason=_map_stop_reason(finish_reason),
        timestamp=int(time() * 1000),
    )


def _iter_sse_payloads(lines: list[str]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    buffer: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if not line.startswith("data: "):
            continue
        data = line[6:].strip()
        if data == "[DONE]":
            break
        buffer.append(data)
    for entry in buffer:
        decoded = json.loads(entry)
        if isinstance(decoded, dict):
            payloads.append(decoded)
    return payloads


def _stream_openai_from_sse(
    stream: AssistantMessageEventStream,
    output: AssistantMessage,
    lines: list[str],
    model: Model,
    signal: Any,
) -> None:
    stream.push({"type": "start", "partial": output})
    current_block: dict[str, Any] | None = None
    tool_call_blocks: dict[int, tuple[int, dict[str, Any]]] = {}

    def block_index() -> int:
        return len(output.content) - 1

    def finish_current_block() -> None:
        nonlocal current_block
        if current_block is None:
            return
        index = block_index()
        if current_block.get("type") == "text":
            stream.push({"type": "text_end", "contentIndex": index, "content": current_block.get("text", ""), "partial": output})
        elif current_block.get("type") == "thinking":
            stream.push(
                {"type": "thinking_end", "contentIndex": index, "content": current_block.get("thinking", ""), "partial": output}
            )
        current_block = None

    for chunk in _iter_sse_payloads(lines):
        if signal is not None and getattr(signal, "aborted", False):
            raise RuntimeError("Request was aborted")

        usage_payload = chunk.get("usage")
        if isinstance(usage_payload, dict):
            output.usage = _usage_from_response({"usage": usage_payload}, model)

        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, dict):
            continue
        if isinstance(choice.get("finish_reason"), str):
            output.stop_reason = _map_stop_reason(choice["finish_reason"])

        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue

        text_delta = delta.get("content")
        if isinstance(text_delta, str) and text_delta:
            if current_block is None or current_block.get("type") != "text":
                finish_current_block()
                current_block = {"type": "text", "text": ""}
                output.content.append(current_block)
                stream.push({"type": "text_start", "contentIndex": block_index(), "partial": output})
            current_block["text"] += text_delta
            stream.push({"type": "text_delta", "contentIndex": block_index(), "delta": text_delta, "partial": output})
        elif isinstance(text_delta, list):
            finish_current_block()
            for part in text_delta:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type", ""))
                if part_type in {"text", "output_text"}:
                    text = part.get("text")
                    if not isinstance(text, str) or not text:
                        continue
                    output.content.append({"type": "text", "text": text})
                    content_index = len(output.content) - 1
                    stream.push({"type": "text_start", "contentIndex": content_index, "partial": output})
                    stream.push({"type": "text_delta", "contentIndex": content_index, "delta": text, "partial": output})
                    stream.push({"type": "text_end", "contentIndex": content_index, "content": text, "partial": output})
                    continue
                image_block = _image_block_from_openai_part(part)
                if image_block is not None:
                    output.content.append(image_block)

        reasoning_delta = None
        for field in ("reasoning_content", "reasoning", "reasoning_text"):
            value = delta.get(field)
            if isinstance(value, str) and value:
                reasoning_delta = value
                break
        if reasoning_delta is not None:
            if current_block is None or current_block.get("type") != "thinking":
                finish_current_block()
                current_block = {"type": "thinking", "thinking": ""}
                output.content.append(current_block)
                stream.push({"type": "thinking_start", "contentIndex": block_index(), "partial": output})
            current_block["thinking"] += reasoning_delta
            stream.push({"type": "thinking_delta", "contentIndex": block_index(), "delta": reasoning_delta, "partial": output})

        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            finish_current_block()
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                call_slot = tool_call.get("index")
                slot = int(call_slot) if isinstance(call_slot, int) else len(tool_call_blocks)
                existing = tool_call_blocks.get(slot)
                if existing is None:
                    block = {
                        "type": "toolCall",
                        "id": str(tool_call.get("id", "")),
                        "name": "",
                        "arguments": {},
                        "_partial_args": "",
                    }
                    output.content.append(block)
                    content_index = len(output.content) - 1
                    tool_call_blocks[slot] = (content_index, block)
                    stream.push({"type": "toolcall_start", "contentIndex": content_index, "partial": output})
                else:
                    content_index, block = existing

                if tool_call.get("id"):
                    block["id"] = str(tool_call["id"])
                function_payload = tool_call.get("function")
                if isinstance(function_payload, dict):
                    if function_payload.get("name"):
                        block["name"] = str(function_payload["name"])
                    arguments_delta = function_payload.get("arguments")
                    if isinstance(arguments_delta, str):
                        block["_partial_args"] += arguments_delta
                        try:
                            parsed = json.loads(block["_partial_args"])
                        except json.JSONDecodeError:
                            parsed = {}
                        if isinstance(parsed, dict):
                            block["arguments"] = parsed
                        stream.push(
                            {
                                "type": "toolcall_delta",
                                "contentIndex": content_index,
                                "delta": arguments_delta,
                                "partial": output,
                            }
                        )

    finish_current_block()
    for slot in sorted(tool_call_blocks):
        content_index, block = tool_call_blocks[slot]
        block.pop("_partial_args", None)
        stream.push({"type": "toolcall_end", "contentIndex": content_index, "toolCall": block, "partial": output})

    if signal is not None and getattr(signal, "aborted", False):
        raise RuntimeError("Request was aborted")
    if output.stop_reason in {"aborted", "error"}:
        raise RuntimeError(output.error_message or "An unknown error occurred")
    stream.push({"type": "done", "reason": output.stop_reason, "message": output})
    stream.end(output)


def stream_openai_completions(
    model: Model,
    context: LLMContext,
    options: OpenAICompletionsOptions | StreamOptions | None = None,
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
        option = options if isinstance(options, OpenAICompletionsOptions) else OpenAICompletionsOptions(**(options.__dict__ if options else {}))
        api_key = option.api_key or get_env_api_key(model.provider)
        if not api_key:
            raise RuntimeError(f"No API key for provider: {model.provider}")

        payload: dict[str, Any] = {
            "model": model.id,
            "messages": _serialize_messages(context),
            "stream": False,
        }
        if option.temperature is not None:
            payload["temperature"] = option.temperature
        if option.max_tokens is not None:
            payload["max_tokens"] = option.max_tokens
        if option.reasoning_effort is not None:
            payload["reasoning_effort"] = option.reasoning_effort
        if option.tool_choice is not None:
            payload["tool_choice"] = option.tool_choice
        tools_payload = _serialize_tools(context)
        if tools_payload:
            payload["tools"] = tools_payload

        if option.on_payload is not None:
            maybe_payload = option.on_payload(payload, model)
            if maybe_payload is not None and isinstance(maybe_payload, dict):
                payload = maybe_payload

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **dict(model.headers),
            **dict(option.headers),
        }
        use_streaming_transport = option.http_stream is not None or option.http_post is None
        if use_streaming_transport:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
            requester = option.http_stream or _request_sse
            response_lines = request_with_retry(
                lambda: list(requester(_resolve_url(model), headers, payload)),
                max_retries=3,
                base_delay_ms=2000,
                max_retry_delay_ms=option.max_retry_delay_ms if option.max_retry_delay_ms is not None else 60000,
            )
            _stream_openai_from_sse(stream, output, response_lines, model, option.signal)
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


def stream_simple_openai_completions(
    model: Model,
    context: LLMContext,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    api_key = (options.api_key if options is not None else None) or get_env_api_key(model.provider)
    if not api_key:
        raise RuntimeError(f"No API key for provider: {model.provider}")

    base = build_base_options(model, options, api_key)
    reasoning = options.reasoning if options is not None else None
    reasoning_effort = reasoning if supports_xhigh(model) else clamp_reasoning(reasoning)
    full_options = OpenAICompletionsOptions(**base.__dict__, reasoning_effort=reasoning_effort)
    return stream_openai_completions(model, context, full_options)
