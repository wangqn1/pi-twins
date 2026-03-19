from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import time
from typing import Any, Callable, Protocol

from .store import ChannelStore, LoggedMessage


@dataclass
class SlackEvent:
    type: str
    channel: str
    ts: str
    user: str
    text: str
    files: list[dict[str, Any]] | None = None
    attachments: list[Any] | None = None


@dataclass
class SlackUser:
    id: str
    user_name: str
    display_name: str


@dataclass
class SlackChannel:
    id: str
    name: str


@dataclass
class ChannelInfo:
    id: str
    name: str


@dataclass
class UserInfo:
    id: str
    user_name: str
    display_name: str


@dataclass
class SlackContext:
    message: Any
    channel_name: str | None
    channels: list[ChannelInfo]
    users: list[UserInfo]
    respond: Callable[[str, bool], None]
    replace_message: Callable[[str], None]
    respond_in_thread: Callable[[str], None]
    set_typing: Callable[[bool], None]
    upload_file: Callable[[str, str | None], None]
    set_working: Callable[[bool], None]
    delete_message: Callable[[], None]


class MomHandler(Protocol):
    def is_running(self, channel_id: str) -> bool: ...

    def handle_event(self, event: SlackEvent, slack: "SlackBot", is_event: bool = False) -> None: ...

    def handle_stop(self, channel_id: str, slack: "SlackBot") -> None: ...


class SlackSyncClient(Protocol):
    def users_list(self, *, limit: int, cursor: str | None = None) -> dict[str, Any]: ...

    def conversations_list(
        self,
        *,
        types: str,
        limit: int,
        cursor: str | None = None,
        exclude_archived: bool | None = None,
    ) -> dict[str, Any]: ...

    def conversations_history(
        self,
        *,
        channel: str,
        oldest: str | None = None,
        inclusive: bool = False,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> dict[str, Any]: ...


class ChannelQueue:
    def __init__(self) -> None:
        self._queue: list[Callable[[], None]] = []
        self._processing = False
        self._lock = threading.Lock()

    def enqueue(self, work: Callable[[], None]) -> None:
        with self._lock:
            self._queue.append(work)
        self._process_next()

    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    def _process_next(self) -> None:
        with self._lock:
            if self._processing or not self._queue:
                return
            self._processing = True
            work = self._queue.pop(0)
        try:
            work()
        finally:
            with self._lock:
                self._processing = False
            self._process_next()


class SlackBot:
    def __init__(
        self,
        handler: MomHandler,
        store: ChannelStore,
        *,
        bot_user_id: str | None = None,
        startup_ts: str | None = None,
    ) -> None:
        self.handler = handler
        self.store = store
        self.bot_user_id = bot_user_id
        self.startup_ts = startup_ts
        self.users: dict[str, SlackUser] = {}
        self.channels: dict[str, SlackChannel] = {}
        self.queues: dict[str, ChannelQueue] = {}
        self.messages: dict[str, dict[str, str]] = defaultdict(dict)
        self.thread_messages: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
        self.uploads: list[tuple[str, str, str | None]] = []

    def start(self) -> None:
        if self.startup_ts is None:
            self.startup_ts = f"{time():.6f}"

    def add_user(self, user: SlackUser) -> None:
        self.users[user.id] = user

    def add_channel(self, channel: SlackChannel) -> None:
        self.channels[channel.id] = channel

    def get_user(self, user_id: str) -> SlackUser | None:
        return self.users.get(user_id)

    def get_channel(self, channel_id: str) -> SlackChannel | None:
        return self.channels.get(channel_id)

    def get_all_users(self) -> list[SlackUser]:
        return list(self.users.values())

    def get_all_channels(self) -> list[SlackChannel]:
        return list(self.channels.values())

    def set_bot_user_id(self, user_id: str | None) -> None:
        self.bot_user_id = user_id

    def set_startup_ts(self, ts: str | None) -> None:
        self.startup_ts = ts

    def post_message(self, channel: str, text: str) -> str:
        ts = f"{time():.6f}"
        self.messages[channel][ts] = text
        return ts

    def update_message(self, channel: str, ts: str, text: str) -> None:
        self.messages[channel][ts] = text

    def delete_message(self, channel: str, ts: str) -> None:
        self.messages[channel].pop(ts, None)
        self.thread_messages[channel].pop(ts, None)

    def post_in_thread(self, channel: str, thread_ts: str, text: str) -> str:
        ts = f"{time():.6f}"
        self.thread_messages[channel][ts] = (thread_ts, text)
        return ts

    def upload_file(self, channel: str, file_path: str, title: str | None = None) -> None:
        self.uploads.append((channel, file_path, title))

    def log_to_file(self, channel: str, entry: dict[str, Any]) -> None:
        attachments = [
            attachment if hasattr(attachment, "__dict__") else attachment
            for attachment in entry.get("attachments", [])
        ]
        payload = LoggedMessage(
            date=str(entry.get("date", "")),
            ts=str(entry.get("ts", "")),
            user=str(entry.get("user", "")),
            user_name=entry.get("userName"),
            display_name=entry.get("displayName"),
            text=str(entry.get("text", "")),
            attachments=attachments,
            is_bot=bool(entry.get("isBot", False)),
        )
        self.store.log_message(channel, payload)

    def log_bot_response(self, channel: str, text: str, ts: str) -> None:
        self.store.log_bot_response(channel, text, ts)

    def enqueue_event(self, event: SlackEvent | dict[str, Any]) -> bool:
        slack_event = event if isinstance(event, SlackEvent) else self._coerce_event(event)
        queue = self._get_queue(slack_event.channel)
        if queue.size() >= 5:
            return False
        queue.enqueue(lambda: self.handler.handle_event(slack_event, self, True))
        return True

    def emit_event(self, event: SlackEvent) -> None:
        self._log_and_maybe_dispatch(event, busy_message="_Already working. Say `stop` to cancel._", allow_old=False)

    def emit_app_mention(self, payload: dict[str, Any]) -> None:
        channel = str(payload["channel"])
        event = SlackEvent(
            type="mention",
            channel=channel,
            ts=str(payload["ts"]),
            user=str(payload["user"]),
            text=self._normalize_text(str(payload.get("text", ""))),
            files=payload.get("files") if isinstance(payload.get("files"), list) else None,
        )
        self._log_and_maybe_dispatch(event, busy_message="_Already working. Say `@mom stop` to cancel._", allow_old=True)

    def emit_message(self, payload: dict[str, Any]) -> None:
        if payload.get("bot_id"):
            return
        user_id = payload.get("user")
        if not isinstance(user_id, str) or not user_id:
            return
        if self.bot_user_id and user_id == self.bot_user_id:
            return
        subtype = payload.get("subtype")
        if subtype is not None and subtype != "file_share":
            return
        files = payload.get("files") if isinstance(payload.get("files"), list) else None
        text = str(payload.get("text", "") or "")
        if not text and not files:
            return

        channel = str(payload["channel"])
        is_dm = payload.get("channel_type") == "im" or channel.startswith("D")
        if not is_dm and self.bot_user_id and f"<@{self.bot_user_id}>" in text:
            return

        event = SlackEvent(
            type="dm" if is_dm else "mention",
            channel=channel,
            ts=str(payload["ts"]),
            user=user_id,
            text=self._normalize_text(text),
            files=files,
        )
        self._log_and_maybe_dispatch(
            event,
            busy_message="_Already working. Say `stop` to cancel._",
            allow_old=True,
            only_trigger=is_dm,
        )

    def fetch_users(self, client: SlackSyncClient) -> int:
        count = 0
        cursor: str | None = None
        while True:
            result = client.users_list(limit=200, cursor=cursor)
            members = result.get("members")
            for member in members if isinstance(members, list) else []:
                if not isinstance(member, dict) or member.get("deleted"):
                    continue
                user_id = member.get("id")
                user_name = member.get("name")
                if not isinstance(user_id, str) or not isinstance(user_name, str):
                    continue
                display_name = str(member.get("real_name") or user_name)
                self.users[user_id] = SlackUser(id=user_id, user_name=user_name, display_name=display_name)
                count += 1
            cursor = self._next_cursor(result)
            if not cursor:
                return count

    def fetch_channels(self, client: SlackSyncClient) -> int:
        count = 0
        cursor: str | None = None
        while True:
            result = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
            )
            channels = result.get("channels")
            for channel in channels if isinstance(channels, list) else []:
                if not isinstance(channel, dict) or not channel.get("is_member"):
                    continue
                channel_id = channel.get("id")
                name = channel.get("name")
                if not isinstance(channel_id, str) or not isinstance(name, str):
                    continue
                self.channels[channel_id] = SlackChannel(id=channel_id, name=name)
                count += 1
            cursor = self._next_cursor(result)
            if not cursor:
                break

        cursor = None
        while True:
            result = client.conversations_list(types="im", limit=200, cursor=cursor)
            channels = result.get("channels")
            for channel in channels if isinstance(channels, list) else []:
                if not isinstance(channel, dict):
                    continue
                channel_id = channel.get("id")
                user_id = channel.get("user")
                if not isinstance(channel_id, str):
                    continue
                user = self.users.get(user_id) if isinstance(user_id, str) else None
                name = f"DM:{user.user_name}" if user else f"DM:{channel_id}"
                self.channels[channel_id] = SlackChannel(id=channel_id, name=name)
                count += 1
            cursor = self._next_cursor(result)
            if not cursor:
                return count

    def get_existing_timestamps(self, channel_id: str) -> set[str]:
        log_path = Path(self.store.get_channel_dir(channel_id)) / "log.jsonl"
        timestamps: set[str] = set()
        if not log_path.exists():
            return timestamps
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = payload.get("ts") if isinstance(payload, dict) else None
            if ts is not None:
                timestamps.add(str(ts))
        return timestamps

    def backfill_channel(self, client: SlackSyncClient, channel_id: str) -> int:
        existing_ts = self.get_existing_timestamps(channel_id)
        latest_ts = max(existing_ts, key=float) if existing_ts else None
        all_messages: list[dict[str, Any]] = []
        cursor: str | None = None
        page_count = 0
        while True:
            result = client.conversations_history(
                channel=channel_id,
                oldest=latest_ts,
                inclusive=False,
                limit=1000,
                cursor=cursor,
            )
            messages = result.get("messages")
            if isinstance(messages, list):
                all_messages.extend(message for message in messages if isinstance(message, dict))
            cursor = self._next_cursor(result)
            page_count += 1
            if not cursor or page_count >= 3:
                break

        relevant_messages: list[dict[str, Any]] = []
        for message in all_messages:
            ts = message.get("ts")
            if not isinstance(ts, str) or ts in existing_ts:
                continue
            user_id = message.get("user")
            is_mom_message = self.bot_user_id is not None and user_id == self.bot_user_id
            if is_mom_message:
                relevant_messages.append(message)
                continue
            if message.get("bot_id"):
                continue
            subtype = message.get("subtype")
            if subtype is not None and subtype != "file_share":
                continue
            if not isinstance(user_id, str):
                continue
            files = message.get("files")
            if not message.get("text") and not isinstance(files, list):
                continue
            relevant_messages.append(message)

        relevant_messages.reverse()
        for message in relevant_messages:
            ts = str(message["ts"])
            user_id = message.get("user")
            is_mom_message = self.bot_user_id is not None and user_id == self.bot_user_id
            files = message.get("files") if isinstance(message.get("files"), list) else []
            attachments = self.store.process_attachments(channel_id, files, ts) if files else []
            text = self._normalize_text(str(message.get("text", "") or ""))
            user = self.users.get(user_id) if isinstance(user_id, str) else None
            self.log_to_file(
                channel_id,
                {
                    "date": time_iso_from_slack_ts(ts),
                    "ts": ts,
                    "user": "bot" if is_mom_message else str(user_id),
                    "userName": None if is_mom_message else (user.user_name if user else None),
                    "displayName": None if is_mom_message else (user.display_name if user else None),
                    "text": text,
                    "attachments": attachments,
                    "isBot": is_mom_message,
                },
            )
        return len(relevant_messages)

    def backfill_all_channels(self, client: SlackSyncClient) -> int:
        total = 0
        for channel_id in sorted(self.channels):
            log_path = Path(self.store.get_channel_dir(channel_id)) / "log.jsonl"
            if not log_path.exists():
                continue
            total += self.backfill_channel(client, channel_id)
        return total

    def _log_and_maybe_dispatch(
        self,
        event: SlackEvent,
        *,
        busy_message: str,
        allow_old: bool,
        only_trigger: bool = True,
    ) -> None:
        event.attachments = self.log_user_message(event)
        if allow_old and self._is_old_message(event.ts):
            return
        if not only_trigger:
            return
        if event.text.strip().lower() == "stop":
            if self.handler.is_running(event.channel):
                self.handler.handle_stop(event.channel, self)
            else:
                self.post_message(event.channel, "_Nothing running_")
            return
        if self.handler.is_running(event.channel):
            self.post_message(event.channel, busy_message)
            return
        self._get_queue(event.channel).enqueue(lambda: self.handler.handle_event(event, self, False))

    def log_user_message(self, event: SlackEvent) -> list[Any]:
        user = self.users.get(event.user)
        attachments = self.store.process_attachments(event.channel, event.files or [], event.ts) if event.files else []
        self.log_to_file(
            event.channel,
            {
                "date": time_iso_from_slack_ts(event.ts),
                "ts": event.ts,
                "user": event.user,
                "userName": user.user_name if user else None,
                "displayName": user.display_name if user else None,
                "text": event.text,
                "attachments": attachments,
                "isBot": False,
            },
        )
        return attachments

    def _is_old_message(self, ts: str) -> bool:
        return self.startup_ts is not None and float(ts) < float(self.startup_ts)

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    def _next_cursor(self, payload: dict[str, Any]) -> str | None:
        metadata = payload.get("response_metadata")
        if isinstance(metadata, dict):
            cursor = metadata.get("next_cursor")
            if isinstance(cursor, str) and cursor:
                return cursor
        return None

    def _coerce_event(self, payload: dict[str, Any]) -> SlackEvent:
        return SlackEvent(
            type=str(payload.get("type", "mention")),
            channel=str(payload["channel"]),
            ts=str(payload["ts"]),
            user=str(payload["user"]),
            text=str(payload["text"]),
            files=payload.get("files"),
            attachments=payload.get("attachments"),
        )

    def _get_queue(self, channel_id: str) -> ChannelQueue:
        queue = self.queues.get(channel_id)
        if queue is None:
            queue = ChannelQueue()
            self.queues[channel_id] = queue
        return queue


def time_iso_from_slack_ts(ts: str) -> str:
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
