from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def _normalize_user_message_content(content: Any) -> str | None:
    if isinstance(content, str):
        normalized = content
    elif isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(str(part.get("text", "")))
        normalized = "\n".join(texts)
    else:
        return None

    normalized = normalized.replace("\r\n", "\n")
    normalized = normalized.removeprefix("[")
    if "] " in normalized and normalized[:4].isdigit():
        normalized = normalized.split("] ", 1)[1]
    attachments_idx = normalized.find("\n\n<slack_attachments>\n")
    if attachments_idx != -1:
        normalized = normalized[:attachments_idx]
    return normalized


def sync_log_to_session_manager(session_manager: Any, channel_dir: str, exclude_slack_ts: str | None = None) -> int:
    log_file = Path(channel_dir) / "log.jsonl"
    if not log_file.exists():
        return 0

    existing_messages: set[str] = set()
    for entry in session_manager.get_entries():
        if entry.get("type") != "message":
            continue
        message = entry.get("message", {})
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        normalized = _normalize_user_message_content(message.get("content"))
        if normalized:
            existing_messages.add(normalized)

    new_messages: list[tuple[int, dict[str, Any]]] = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        slack_ts = payload.get("ts")
        date = payload.get("date")
        if not slack_ts or not date or payload.get("isBot"):
            continue
        if exclude_slack_ts is not None and str(slack_ts) == exclude_slack_ts:
            continue

        text = f"[{payload.get('userName') or payload.get('user') or 'unknown'}]: {payload.get('text', '')}"
        if text in existing_messages:
            continue
        timestamp = int(Path("/").stat().st_mtime * 1000)
        try:
            from datetime import datetime

            timestamp = int(datetime.fromisoformat(str(date).replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:  # noqa: BLE001
            pass
        message = {"role": "user", "content": [{"type": "text", "text": text}], "timestamp": timestamp}
        new_messages.append((timestamp, message))
        existing_messages.add(text)

    new_messages.sort(key=lambda item: item[0])
    for _, message in new_messages:
        session_manager.append_message(message)
    return len(new_messages)


@dataclass
class MomSettingsManager:
    workspace_dir: str

    @property
    def settings_path(self) -> Path:
        return Path(self.workspace_dir) / "settings.json"

    def load(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return {}
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def save(self, settings: dict[str, Any]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def update(self, updater: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
        current = self.load()
        next_settings = updater(dict(current))
        if next_settings is None:
            return current
        self.save(next_settings)
        return next_settings


def create_mom_settings_manager(workspace_dir: str) -> MomSettingsManager:
    return MomSettingsManager(workspace_dir=workspace_dir)
