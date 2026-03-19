from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, TextIO
from urllib.request import Request, urlopen


@dataclass
class SlackMessage:
    ts: str
    user: str | None = None
    text: str | None = None
    thread_ts: str | None = None
    reply_count: int | None = None
    files: list[dict[str, Any]] | None = None


class SlackHistoryClient(Protocol):
    def conversations_info(self, channel: str) -> dict[str, Any]: ...

    def conversations_history(self, channel: str, *, limit: int, cursor: str | None = None) -> dict[str, Any]: ...

    def conversations_replies(
        self,
        channel: str,
        *,
        ts: str,
        limit: int,
        cursor: str | None = None,
    ) -> dict[str, Any]: ...


def format_ts(ts: str) -> str:
    value = datetime.fromtimestamp(float(ts), timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_message(ts: str, user: str, text: str, indent: str = "") -> str:
    prefix = f"[{format_ts(ts)}] {user}: "
    lines = text.splitlines() or [""]
    first_line = f"{indent}{prefix}{lines[0]}"
    if len(lines) == 1:
        return first_line
    continuation_indent = indent + " " * len(prefix)
    return "\n".join([first_line, *[continuation_indent + line for line in lines[1:]]])


class SlackWebApiClient:
    def __init__(self, bot_token: str, base_url: str = "https://slack.com/api") -> None:
        self.bot_token = bot_token
        self.base_url = base_url.rstrip("/")

    def conversations_info(self, channel: str) -> dict[str, Any]:
        return self._request("conversations.info", {"channel": channel})

    def conversations_history(self, channel: str, *, limit: int, cursor: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"channel": channel, "limit": limit}
        if cursor:
            payload["cursor"] = cursor
        return self._request("conversations.history", payload)

    def conversations_replies(
        self,
        channel: str,
        *,
        ts: str,
        limit: int,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"channel": channel, "ts": ts, "limit": limit}
        if cursor:
            payload["cursor"] = cursor
        return self._request("conversations.replies", payload)

    def _request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}/{endpoint}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        with urlopen(request) as response:  # noqa: S310
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict) or not result.get("ok", False):
            raise RuntimeError(f"Slack API error for {endpoint}: {result.get('error', 'unknown error') if isinstance(result, dict) else result}")
        return result


def _coerce_messages(items: list[dict[str, Any]] | None) -> list[SlackMessage]:
    messages: list[SlackMessage] = []
    for item in items or []:
        ts = item.get("ts")
        if not isinstance(ts, str):
            continue
        reply_count = item.get("reply_count")
        messages.append(
            SlackMessage(
                ts=ts,
                user=item.get("user"),
                text=item.get("text"),
                thread_ts=item.get("thread_ts"),
                reply_count=int(reply_count) if isinstance(reply_count, (int, float)) else None,
                files=item.get("files") if isinstance(item.get("files"), list) else None,
            )
        )
    return messages


def download_channel(
    channel_id: str,
    bot_token: str,
    *,
    client: SlackHistoryClient | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> dict[str, Any]:
    client = client or SlackWebApiClient(bot_token)
    out = out or sys.stdout
    err = err or sys.stderr

    print(f"Fetching channel info for {channel_id}...", file=err)
    channel_name = channel_id
    try:
        info = client.conversations_info(channel_id)
        channel = info.get("channel")
        if isinstance(channel, dict) and isinstance(channel.get("name"), str) and channel["name"]:
            channel_name = channel["name"]
    except Exception:
        pass

    print(f"Downloading history for #{channel_name} ({channel_id})...", file=err)

    messages: list[SlackMessage] = []
    cursor: str | None = None
    while True:
        response = client.conversations_history(channel_id, limit=200, cursor=cursor)
        messages.extend(_coerce_messages(response.get("messages")))
        print(f"  Fetched {len(messages)} messages...", file=err)
        metadata = response.get("response_metadata")
        cursor = metadata.get("next_cursor") if isinstance(metadata, dict) else None
        if not cursor:
            break

    messages.reverse()
    thread_replies: dict[str, list[SlackMessage]] = {}
    threads_to_fetch = [message for message in messages if (message.reply_count or 0) > 0]
    print(f"Fetching {len(threads_to_fetch)} threads...", file=err)

    for index, parent in enumerate(threads_to_fetch, start=1):
        print(f"  Thread {index}/{len(threads_to_fetch)} ({parent.reply_count} replies)...", file=err)
        replies: list[SlackMessage] = []
        thread_cursor: str | None = None
        while True:
            response = client.conversations_replies(channel_id, ts=parent.ts, limit=200, cursor=thread_cursor)
            current_messages = _coerce_messages(response.get("messages"))
            replies.extend(current_messages[1:] if current_messages else [])
            metadata = response.get("response_metadata")
            thread_cursor = metadata.get("next_cursor") if isinstance(metadata, dict) else None
            if not thread_cursor:
                break
        thread_replies[parent.ts] = replies

    total_replies = 0
    for message in messages:
        print(format_message(message.ts, message.user or "unknown", message.text or ""), file=out)
        for reply in thread_replies.get(message.ts, []):
            print(format_message(reply.ts, reply.user or "unknown", reply.text or "", "  "), file=out)
            total_replies += 1

    print(f"Done! {len(messages)} messages, {total_replies} thread replies", file=err)
    return {
        "ok": True,
        "channelId": channel_id,
        "channelName": channel_name,
        "messageCount": len(messages),
        "replyCount": total_replies,
    }
