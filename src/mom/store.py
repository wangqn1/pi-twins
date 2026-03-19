from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen


@dataclass
class Attachment:
    original: str
    local: str


@dataclass
class LoggedMessage:
    date: str
    ts: str
    user: str
    text: str
    attachments: list[Attachment] = field(default_factory=list)
    is_bot: bool = False
    user_name: str | None = None
    display_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "date": self.date,
            "ts": self.ts,
            "user": self.user,
            "text": self.text,
            "attachments": [attachment.__dict__ for attachment in self.attachments],
            "isBot": self.is_bot,
        }
        if self.user_name is not None:
            payload["userName"] = self.user_name
        if self.display_name is not None:
            payload["displayName"] = self.display_name
        return payload


@dataclass
class ChannelStoreConfig:
    working_dir: str
    bot_token: str
    download_fn: Callable[[str, str, str], None] | None = None
    cleanup_window_seconds: float = 60.0


class ChannelStore:
    def __init__(self, config: ChannelStoreConfig) -> None:
        self.working_dir = Path(config.working_dir)
        self.bot_token = config.bot_token
        self.download_fn = config.download_fn or self._download_attachment
        self.cleanup_window_seconds = config.cleanup_window_seconds
        self.pending_downloads: list[tuple[str, str]] = []
        self._download_lock = threading.Lock()
        self._download_thread: threading.Thread | None = None
        self._recently_logged: dict[str, float] = {}
        self.working_dir.mkdir(parents=True, exist_ok=True)

    def get_channel_dir(self, channel_id: str) -> str:
        channel_dir = self.working_dir / channel_id
        channel_dir.mkdir(parents=True, exist_ok=True)
        return str(channel_dir)

    def generate_local_filename(self, original_name: str, timestamp: str) -> str:
        ts_ms = int(float(timestamp) * 1000)
        sanitized = "".join(char if char.isalnum() or char in "._-" else "_" for char in original_name)
        return f"{ts_ms}_{sanitized}"

    def process_attachments(
        self,
        channel_id: str,
        files: list[dict[str, Any]],
        timestamp: str,
    ) -> list[Attachment]:
        attachments: list[Attachment] = []
        for file in files:
            url = file.get("url_private_download") or file.get("url_private")
            name = file.get("name")
            if not url or not name:
                continue
            filename = self.generate_local_filename(str(name), timestamp)
            local_rel = f"{channel_id}/attachments/{filename}"
            attachments.append(Attachment(original=str(name), local=local_rel))
            self.pending_downloads.append((local_rel, str(url)))
        self.process_download_queue()
        return attachments

    def log_message(self, channel_id: str, message: LoggedMessage) -> bool:
        self._cleanup_recently_logged()
        key = f"{channel_id}:{message.ts}"
        if key in self._recently_logged:
            return False
        self._recently_logged[key] = time.time()

        if not message.date:
            try:
                message.date = time_iso_from_ts(message.ts)
            except Exception:  # noqa: BLE001
                message.date = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

        log_path = Path(self.get_channel_dir(channel_id)) / "log.jsonl"
        line = json.dumps(message.to_dict(), ensure_ascii=False) + "\n"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        return True

    def log_bot_response(self, channel_id: str, text: str, ts: str) -> bool:
        return self.log_message(
            channel_id,
            LoggedMessage(
                date=time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                ts=ts,
                user="bot",
                text=text,
                attachments=[],
                is_bot=True,
            ),
        )

    def get_last_timestamp(self, channel_id: str) -> str | None:
        log_path = self.working_dir / channel_id / "log.jsonl"
        if not log_path.exists():
            return None
        try:
            lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if not lines:
                return None
            payload = json.loads(lines[-1])
            return str(payload.get("ts")) if payload.get("ts") is not None else None
        except Exception:  # noqa: BLE001
            return None

    def process_download_queue(self) -> None:
        with self._download_lock:
            if self._download_thread is not None and self._download_thread.is_alive():
                return
            if not self.pending_downloads:
                return
            self._download_thread = threading.Thread(target=self._run_download_queue, daemon=True)
            self._download_thread.start()

    def wait_for_downloads(self, timeout: float | None = None) -> None:
        thread = self._download_thread
        if thread is not None:
            thread.join(timeout=timeout)

    def _run_download_queue(self) -> None:
        while True:
            with self._download_lock:
                if not self.pending_downloads:
                    return
                local_rel, url = self.pending_downloads.pop(0)
            try:
                self.download_fn(local_rel, url, self.bot_token)
            except Exception:  # noqa: BLE001
                continue

    def _download_attachment(self, local_rel: str, url: str, bot_token: str) -> None:
        file_path = self.working_dir / local_rel
        file_path.parent.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"Authorization": f"Bearer {bot_token}"})
        with urlopen(request) as response:  # noqa: S310
            file_path.write_bytes(response.read())

    def _cleanup_recently_logged(self) -> None:
        now = time.time()
        threshold = now - self.cleanup_window_seconds
        expired = [key for key, seen_at in self._recently_logged.items() if seen_at < threshold]
        for key in expired:
            del self._recently_logged[key]


def time_iso_from_ts(ts: str) -> str:
    value = float(ts) * 1000 if "." in ts else float(ts)
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(value / 1000))
