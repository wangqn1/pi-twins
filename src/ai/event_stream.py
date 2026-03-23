# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass, field
import json
from threading import Event
from typing import Any, Iterator

from .types import AssistantMessage, AssistantMessageEvent


@dataclass
class AssistantMessageEventStream:
    _events: list[AssistantMessageEvent] = field(default_factory=list)
    _ended: Event = field(default_factory=Event)
    _result: AssistantMessage | None = None

    def push(self, event: AssistantMessageEvent) -> None:
        self._events.append(event)
        event_type = event.get("type")
        if event_type == "done":
            message = event.get("message")
            if isinstance(message, AssistantMessage):
                self._result = message
        elif event_type == "error":
            message = event.get("error")
            if isinstance(message, AssistantMessage):
                self._result = message

    def end(self, message: AssistantMessage | None = None) -> None:
        if message is not None:
            self._result = message
        self._ended.set()

    def result(self) -> AssistantMessage:
        self._ended.wait()
        if self._result is None:
            raise RuntimeError("No result produced by event stream")
        return self._result

    def __iter__(self) -> Iterator[AssistantMessageEvent]:
        return iter(self._events)


def emit_assistant_message_events(
    stream: AssistantMessageEventStream,
    partial: AssistantMessage,
    final_message: AssistantMessage,
    *,
    include_start: bool = True,
) -> AssistantMessage:
    partial.api = final_message.api
    partial.provider = final_message.provider
    partial.model = final_message.model
    partial.timestamp = final_message.timestamp
    partial.usage = final_message.usage
    partial.stop_reason = final_message.stop_reason
    partial.error_message = final_message.error_message

    if include_start:
        stream.push({"type": "start", "partial": partial})

    partial.content = []
    for index, block in enumerate(final_message.content):
        block_type = block.get("type")
        if block_type == "text":
            current = {"type": "text", "text": ""}
            partial.content.append(current)
            stream.push({"type": "text_start", "contentIndex": index, "partial": partial})
            text = str(block.get("text", ""))
            current["text"] = text
            if text:
                stream.push({"type": "text_delta", "contentIndex": index, "delta": text, "partial": partial})
            if "textSignature" in block:
                current["textSignature"] = block["textSignature"]
            stream.push({"type": "text_end", "contentIndex": index, "content": text, "partial": partial})
            continue

        if block_type == "thinking":
            current = {"type": "thinking", "thinking": ""}
            if "redacted" in block:
                current["redacted"] = block["redacted"]
            partial.content.append(current)
            stream.push({"type": "thinking_start", "contentIndex": index, "partial": partial})
            thinking = str(block.get("thinking", ""))
            current["thinking"] = thinking
            if thinking:
                stream.push({"type": "thinking_delta", "contentIndex": index, "delta": thinking, "partial": partial})
            if "thinkingSignature" in block:
                current["thinkingSignature"] = block["thinkingSignature"]
            stream.push({"type": "thinking_end", "contentIndex": index, "content": thinking, "partial": partial})
            continue

        if block_type == "toolCall":
            current = {
                "type": "toolCall",
                "id": str(block.get("id", "")),
                "name": str(block.get("name", "")),
                "arguments": {},
            }
            partial.content.append(current)
            stream.push({"type": "toolcall_start", "contentIndex": index, "partial": partial})
            arguments = block.get("arguments", {})
            raw_arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
            current["arguments"] = arguments if isinstance(arguments, dict) else {}
            if raw_arguments and raw_arguments != "{}":
                stream.push({"type": "toolcall_delta", "contentIndex": index, "delta": raw_arguments, "partial": partial})
            stream.push({"type": "toolcall_end", "contentIndex": index, "toolCall": current, "partial": partial})
            continue

        partial.content.append(dict(block))

    if final_message.stop_reason in {"error", "aborted"}:
        stream.push({"type": "error", "reason": final_message.stop_reason, "error": partial})
    else:
        stream.push({"type": "done", "reason": final_message.stop_reason, "message": partial})
    stream.end(partial)
    return partial
