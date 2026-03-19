from __future__ import annotations

import json
from io import StringIO

from mom import download_channel, format_message, main


class _FakeSlackHistoryClient:
    def conversations_info(self, channel: str) -> dict[str, object]:
        assert channel == "C1"
        return {"ok": True, "channel": {"name": "general"}}

    def conversations_history(self, channel: str, *, limit: int, cursor: str | None = None) -> dict[str, object]:
        assert channel == "C1"
        assert limit == 200
        assert cursor is None
        return {
            "ok": True,
            "messages": [
                {"ts": "1700000010.000000", "user": "U2", "text": "second"},
                {"ts": "1700000000.000000", "user": "U1", "text": "first", "reply_count": 1},
            ],
        }

    def conversations_replies(self, channel: str, *, ts: str, limit: int, cursor: str | None = None) -> dict[str, object]:
        assert channel == "C1"
        assert ts == "1700000000.000000"
        assert limit == 200
        assert cursor is None
        return {
            "ok": True,
            "messages": [
                {"ts": "1700000000.000000", "user": "U1", "text": "first"},
                {"ts": "1700000005.000000", "user": "U3", "text": "reply line 1\nreply line 2"},
            ],
        }


def test_format_message_indents_multiline_content() -> None:
    rendered = format_message("1700000000.000000", "U1", "hello\nworld", "  ")
    lines = rendered.splitlines()
    assert lines[0].startswith("  [")
    assert lines[1].startswith("  ")
    assert "world" in lines[1]


def test_download_channel_outputs_history_and_threads() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = download_channel("C1", "token", client=_FakeSlackHistoryClient(), out=stdout, err=stderr)

    output = stdout.getvalue()
    assert "U1: first" in output
    assert "U3: reply line 1" in output
    assert "\n  [" in output
    assert "U2: second" in output

    progress = stderr.getvalue()
    assert "Downloading history for #general (C1)" in progress
    assert "Done! 2 messages, 1 thread replies" in progress
    assert result["messageCount"] == 2
    assert result["replyCount"] == 1


def test_mom_main_download_requires_token(monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.delenv("MOM_SLACK_BOT_TOKEN", raising=False)
    assert main(["--download", "C1"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "Missing env: MOM_SLACK_BOT_TOKEN"


def test_mom_main_download_uses_injected_downloader(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("MOM_SLACK_BOT_TOKEN", "secret-token")
    captured: dict[str, str] = {}

    def fake_download(channel_id: str, bot_token: str) -> dict[str, object]:
        captured["channel_id"] = channel_id
        captured["bot_token"] = bot_token
        return {"ok": True}

    assert main(["--download", "C1"], download_channel_fn=fake_download) == 0
    assert captured == {"channel_id": "C1", "bot_token": "secret-token"}
