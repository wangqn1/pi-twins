from __future__ import annotations

import json
from dataclasses import dataclass
from time import time
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen

from ai import (
    AssistantMessage,
    AssistantMessageEventStream,
    LLMContext,
    Model,
    SimpleStreamOptions,
    Usage,
    UsageCost,
)

ProxyTransport = Callable[[str, dict[str, str], dict[str, Any]], Iterable[str]]


@dataclass
class ProxyStreamOptions(SimpleStreamOptions):
    auth_token: str = ""
    proxy_url: str = ""
    http_stream: ProxyTransport | None = None


def stream_proxy(model: Model, context: LLMContext, options: ProxyStreamOptions) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()
    partial = AssistantMessage(
        content=[],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(),
        stop_reason="stop",
        timestamp=int(time() * 1000),
    )

    try:
        final_message: AssistantMessage | None = None
        for event in _read_proxy_events(model, context, options):
            processed = process_proxy_event(event, partial)
            if processed is not None:
                stream.push(processed)
                if processed["type"] == "done":
                    final_message = processed["message"]
                elif processed["type"] == "error":
                    final_message = processed["error"]
        stream.end(final_message or partial)
    except Exception as exc:  # noqa: BLE001
        partial.stop_reason = "aborted" if getattr(options.signal, "aborted", False) else "error"
        partial.error_message = str(exc)
        stream.push({"type": "error", "reason": partial.stop_reason, "error": partial})
        stream.end(partial)

    return stream


def process_proxy_event(proxy_event: dict[str, Any], partial: AssistantMessage) -> dict[str, Any] | None:
    event_type = proxy_event.get("type")
    if event_type == "start":
        return {"type": "start", "partial": partial}

    if event_type == "text_start":
        _ensure_content_index(partial.content, proxy_event["contentIndex"])
        partial.content[proxy_event["contentIndex"]] = {"type": "text", "text": ""}
        return {"type": "text_start", "contentIndex": proxy_event["contentIndex"], "partial": partial}

    if event_type == "text_delta":
        content = partial.content[proxy_event["contentIndex"]]
        if content["type"] != "text":
            raise RuntimeError("Received text_delta for non-text content")
        content["text"] += proxy_event["delta"]
        return {
            "type": "text_delta",
            "contentIndex": proxy_event["contentIndex"],
            "delta": proxy_event["delta"],
            "partial": partial,
        }

    if event_type == "text_end":
        content = partial.content[proxy_event["contentIndex"]]
        if content["type"] != "text":
            raise RuntimeError("Received text_end for non-text content")
        if "contentSignature" in proxy_event:
            content["textSignature"] = proxy_event["contentSignature"]
        return {
            "type": "text_end",
            "contentIndex": proxy_event["contentIndex"],
            "content": content["text"],
            "partial": partial,
        }

    if event_type == "thinking_start":
        _ensure_content_index(partial.content, proxy_event["contentIndex"])
        partial.content[proxy_event["contentIndex"]] = {"type": "thinking", "thinking": ""}
        return {"type": "thinking_start", "contentIndex": proxy_event["contentIndex"], "partial": partial}

    if event_type == "thinking_delta":
        content = partial.content[proxy_event["contentIndex"]]
        if content["type"] != "thinking":
            raise RuntimeError("Received thinking_delta for non-thinking content")
        content["thinking"] += proxy_event["delta"]
        return {
            "type": "thinking_delta",
            "contentIndex": proxy_event["contentIndex"],
            "delta": proxy_event["delta"],
            "partial": partial,
        }

    if event_type == "thinking_end":
        content = partial.content[proxy_event["contentIndex"]]
        if content["type"] != "thinking":
            raise RuntimeError("Received thinking_end for non-thinking content")
        if "contentSignature" in proxy_event:
            content["thinkingSignature"] = proxy_event["contentSignature"]
        return {
            "type": "thinking_end",
            "contentIndex": proxy_event["contentIndex"],
            "content": content["thinking"],
            "partial": partial,
        }

    if event_type == "toolcall_start":
        _ensure_content_index(partial.content, proxy_event["contentIndex"])
        partial.content[proxy_event["contentIndex"]] = {
            "type": "toolCall",
            "id": proxy_event["id"],
            "name": proxy_event["toolName"],
            "arguments": {},
            "_partial_json": "",
        }
        return {"type": "toolcall_start", "contentIndex": proxy_event["contentIndex"], "partial": partial}

    if event_type == "toolcall_delta":
        content = partial.content[proxy_event["contentIndex"]]
        if content["type"] != "toolCall":
            raise RuntimeError("Received toolcall_delta for non-toolCall content")
        content["_partial_json"] += proxy_event["delta"]
        content["arguments"] = _parse_partial_json(content["_partial_json"])
        partial.content[proxy_event["contentIndex"]] = dict(content)
        return {
            "type": "toolcall_delta",
            "contentIndex": proxy_event["contentIndex"],
            "delta": proxy_event["delta"],
            "partial": partial,
        }

    if event_type == "toolcall_end":
        content = partial.content[proxy_event["contentIndex"]]
        if content["type"] != "toolCall":
            return None
        content.pop("_partial_json", None)
        return {
            "type": "toolcall_end",
            "contentIndex": proxy_event["contentIndex"],
            "toolCall": content,
            "partial": partial,
        }

    if event_type == "done":
        partial.stop_reason = proxy_event["reason"]
        partial.usage = _coerce_usage(proxy_event["usage"])
        return {"type": "done", "reason": proxy_event["reason"], "message": partial}

    if event_type == "error":
        partial.stop_reason = proxy_event["reason"]
        partial.error_message = proxy_event.get("errorMessage")
        partial.usage = _coerce_usage(proxy_event["usage"])
        return {"type": "error", "reason": proxy_event["reason"], "error": partial}

    return None


def _read_proxy_events(model: Model, context: LLMContext, options: ProxyStreamOptions) -> Iterable[dict[str, Any]]:
    payload = {
        "model": model.to_dict(),
        "context": {
            "systemPrompt": context.system_prompt,
            "messages": [_serialize_message(message) for message in context.messages],
            "tools": list(context.tools),
        },
        "options": {
            "temperature": options.temperature,
            "maxTokens": options.max_tokens,
            "reasoning": options.reasoning,
        },
    }
    headers = {
        "Authorization": f"Bearer {options.auth_token}",
        "Content-Type": "application/json",
    }
    if options.http_stream is not None:
        lines = options.http_stream(options.proxy_url.rstrip("/") + "/api/stream", headers, payload)
    else:
        lines = _default_proxy_transport(options.proxy_url.rstrip("/") + "/api/stream", headers, payload)
    for line in lines:
        value = line.strip()
        if not value.startswith("data: "):
            continue
        yield json.loads(value[6:].strip())


def _default_proxy_transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> Iterable[str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, method="POST")
    for key, value in headers.items():
        request.add_header(key, value)
    with urlopen(request, timeout=120) as response:
        for raw_line in response:
            yield raw_line.decode("utf-8")


def _serialize_message(message: Any) -> dict[str, Any]:
    if hasattr(message, "to_dict"):
        return message.to_dict()
    if isinstance(message, dict):
        return dict(message)
    return {"role": getattr(message, "role", "unknown")}


def _parse_partial_json(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _coerce_usage(value: Any) -> Usage:
    if isinstance(value, Usage):
        return value
    if not isinstance(value, dict):
        return Usage()
    cost = value.get("cost", {})
    return Usage(
        input=int(value.get("input", 0)),
        output=int(value.get("output", 0)),
        cache_read=int(value.get("cacheRead", value.get("cache_read", 0))),
        cache_write=int(value.get("cacheWrite", value.get("cache_write", 0))),
        total_tokens=int(value.get("totalTokens", value.get("total_tokens", 0))),
        cost=UsageCost(total=float(cost.get("total", 0))),
    )


def _ensure_content_index(content: list[dict[str, Any]], index: int) -> None:
    while len(content) <= index:
        content.append({})
