from __future__ import annotations

import json
import time
from pathlib import Path

from coding_agent.core.session_manager import SessionManager
from mom import (
    ChannelStore,
    ChannelStoreConfig,
    LoggedMessage,
    MomWorkspace,
    create_events_watcher,
    create_mom_settings_manager,
    next_cron_occurrence,
    sync_log_to_session_manager,
)


def test_mom_workspace_paths(tmp_path: Path) -> None:
    workspace = MomWorkspace(tmp_path.as_posix())
    assert workspace.global_memory_path() == str(tmp_path / "MEMORY.md")
    assert workspace.settings_path() == str(tmp_path / "settings.json")
    assert workspace.channel_log_path("C123") == str(tmp_path / "C123" / "log.jsonl")
    assert workspace.channel_attachments_dir("C123") == str(tmp_path / "C123" / "attachments")


def test_channel_store_logs_and_dedupes_messages(tmp_path: Path) -> None:
    store = ChannelStore(ChannelStoreConfig(working_dir=tmp_path.as_posix(), bot_token="xoxb"))
    message = LoggedMessage(
        date="2026-03-12T10:00:00.000Z",
        ts="123.456",
        user="U1",
        user_name="alice",
        text="hello",
    )
    assert store.log_message("C1", message) is True
    assert store.log_message("C1", message) is False
    payload = json.loads((tmp_path / "C1" / "log.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert payload["userName"] == "alice"
    assert store.get_last_timestamp("C1") == "123.456"


def test_channel_store_processes_attachments_and_downloads(tmp_path: Path) -> None:
    downloads: list[tuple[str, str, str]] = []

    def fake_download(local_rel: str, url: str, bot_token: str) -> None:
        downloads.append((local_rel, url, bot_token))

    store = ChannelStore(ChannelStoreConfig(working_dir=tmp_path.as_posix(), bot_token="xoxb", download_fn=fake_download))
    attachments = store.process_attachments(
        "C1",
        [{"name": "hello world.png", "url_private": "https://example.com/file.png"}],
        "123.456",
    )
    store.wait_for_downloads(timeout=1.0)
    assert attachments[0].local.endswith("123456_hello_world.png")
    assert downloads == [(attachments[0].local, "https://example.com/file.png", "xoxb")]


def test_sync_log_to_session_manager_adds_missing_user_messages(tmp_path: Path) -> None:
    channel_dir = tmp_path / "C1"
    channel_dir.mkdir()
    (channel_dir / "log.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "date": "2026-03-12T10:00:00.000Z",
                        "ts": "1.0",
                        "user": "U1",
                        "userName": "alice",
                        "text": "hello",
                        "attachments": [],
                        "isBot": False,
                    }
                ),
                json.dumps(
                    {
                        "date": "2026-03-12T10:01:00.000Z",
                        "ts": "2.0",
                        "user": "bot",
                        "text": "hi",
                        "attachments": [],
                        "isBot": True,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    session = SessionManager.in_memory(tmp_path.as_posix())
    count = sync_log_to_session_manager(session, channel_dir.as_posix())
    assert count == 1
    messages = [entry["message"] for entry in session.get_entries() if entry["type"] == "message"]
    assert messages[0]["content"][0]["text"] == "[alice]: hello"


def test_mom_settings_manager_roundtrip(tmp_path: Path) -> None:
    manager = create_mom_settings_manager(tmp_path.as_posix())
    manager.save({"retry": {"enabled": True}})
    assert manager.load() == {"retry": {"enabled": True}}
    updated = manager.update(lambda current: {**current, "compaction": {"enabled": True}})
    assert updated["compaction"]["enabled"] is True


class _FakeSlack:
    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    def enqueue_event(self, event: dict[str, str]) -> bool:
        self.events.append(event)
        return True


def test_events_watcher_immediate_event_executes_and_deletes(tmp_path: Path) -> None:
    slack = _FakeSlack()
    watcher = create_events_watcher(tmp_path.as_posix(), slack)
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    event_file = events_dir / "wake.json"
    event_file.write_text(json.dumps({"type": "immediate", "channelId": "C1", "text": "wake up"}), encoding="utf-8")
    watcher.scan_once()
    assert len(slack.events) == 1
    assert "wake up" in slack.events[0]["text"]
    assert not event_file.exists()


def test_events_watcher_past_one_shot_is_deleted_without_enqueue(tmp_path: Path) -> None:
    slack = _FakeSlack()
    watcher = create_events_watcher(tmp_path.as_posix(), slack)
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    event_file = events_dir / "past.json"
    event_file.write_text(
        json.dumps({"type": "one-shot", "channelId": "C1", "text": "past", "at": "2020-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    watcher.scan_once()
    assert slack.events == []
    assert not event_file.exists()


def test_next_cron_occurrence_supports_basic_schedule() -> None:
    now = 1767225600.0  # 2026-01-01T00:00:00Z
    next_run = next_cron_occurrence("15 9 * * 1-5", "UTC", now=now)
    assert next_run > now
    assert int(next_run - now) % 60 == 0
