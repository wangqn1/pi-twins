from __future__ import annotations

import json
from pathlib import Path

from ai import AssistantMessage, Model, ScriptedBackend, Usage, text_block
from mom import (
    MomRunner,
    MomRunnerConfig,
    SandboxConfig,
    SlackBot,
    SlackChannel,
    SlackEvent,
    SlackUser,
    build_application,
    create_slack_context,
    main,
    parse_args,
)
from mom.store import ChannelStore, ChannelStoreConfig


def _runner_factory(tmp_path: Path):
    def factory(channel_id: str, channel_dir: str) -> MomRunner:
        del channel_dir

        def responder(model, context, options):  # noqa: ANN001
            del options
            last = context.messages[-1]
            content = getattr(last, "content", [])
            text = next((block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"), "")
            return AssistantMessage(
                content=[text_block(f"reply:{text}")],
                api=model.api,
                provider=model.provider,
                model=model.id,
                usage=Usage(),
                stop_reason="stop",
                timestamp=1,
            )

        return MomRunner(
            MomRunnerConfig(
                sandbox=SandboxConfig(type="host"),
                workspace_dir=tmp_path.as_posix(),
                channel_id=channel_id,
                backend=ScriptedBackend(responder),
                model=Model(provider="mock", id="echo", api="mock"),
            )
        )

    return factory


def test_parse_args_for_mom_main() -> None:
    args = parse_args(["--sandbox", "docker:mom-box", "/tmp/work"])
    assert args.sandbox == "docker:mom-box"
    assert args.working_directory == "/tmp/work"


def test_slack_bot_emits_event_and_logs_busy_stop_flow(tmp_path: Path) -> None:
    app = build_application(tmp_path.as_posix(), SandboxConfig(type="host"), runner_factory=_runner_factory(tmp_path))
    bot = app.bot
    bot.add_user(SlackUser(id="U1", user_name="alice", display_name="Alice"))
    bot.add_channel(SlackChannel(id="C1", name="general"))

    bot.emit_event(SlackEvent(type="mention", channel="C1", ts="1000.0", user="U1", text="hello"))
    assert any("reply:[alice]: hello" in text for text in bot.messages["C1"].values())

    state = app.get_state("C1")
    state.running = True
    bot.emit_event(SlackEvent(type="mention", channel="C1", ts="1001.0", user="U1", text="second"))
    assert any("Already working" in text for text in bot.messages["C1"].values())

    bot.emit_event(SlackEvent(type="mention", channel="C1", ts="1002.0", user="U1", text="stop"))
    assert any("Stopping" in text for text in bot.messages["C1"].values())


def test_build_application_starts_and_stops(tmp_path: Path) -> None:
    app = build_application(tmp_path.as_posix(), SandboxConfig(type="host"), runner_factory=_runner_factory(tmp_path))
    app.start()
    assert (tmp_path / "events").exists()
    app.stop()


def test_mom_package_exports_main_callable() -> None:
    assert callable(main)


def test_create_slack_context_shows_event_status_and_cleans_up_threads(tmp_path: Path) -> None:
    app = build_application(tmp_path.as_posix(), SandboxConfig(type="host"), runner_factory=_runner_factory(tmp_path))
    bot = app.bot
    bot.add_user(SlackUser(id="EVENT", user_name="events", display_name="Events"))
    bot.add_channel(SlackChannel(id="C1", name="general"))
    state = app.get_state("C1")

    event = SlackEvent(
        type="mention",
        channel="C1",
        ts="1000.0",
        user="EVENT",
        text="[EVENT:test.json:immediate:immediate] rebuild indexes",
    )
    ctx = create_slack_context(event, bot, state, is_event=True)
    ctx.set_typing(True)
    first_message = next(iter(bot.messages["C1"].values()))
    assert "Starting event: test.json" in first_message

    ctx.respond("done")
    ctx.respond_in_thread("details")
    assert bot.thread_messages["C1"]

    ctx.delete_message()
    assert not bot.messages["C1"]
    assert not bot.thread_messages["C1"]


def test_mom_main_requires_working_directory() -> None:
    assert main([]) == 1


def test_mom_main_starts_application(tmp_path: Path, capsys) -> None:
    exit_code = main([tmp_path.as_posix()])
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["workingDirectory"] == tmp_path.resolve().as_posix()


def test_slack_bot_skips_old_mentions_but_still_logs_them(tmp_path: Path) -> None:
    app = build_application(tmp_path.as_posix(), SandboxConfig(type="host"), runner_factory=_runner_factory(tmp_path))
    bot = app.bot
    bot.set_startup_ts("2000.0")
    bot.set_bot_user_id("B1")
    bot.add_user(SlackUser(id="U1", user_name="alice", display_name="Alice"))
    bot.add_channel(SlackChannel(id="C1", name="general"))

    bot.emit_app_mention({"channel": "C1", "ts": "1000.0", "user": "U1", "text": "<@B1> hello old"})

    assert not bot.messages["C1"]
    log_text = (tmp_path / "C1" / "log.jsonl").read_text(encoding="utf-8")
    assert "hello old" in log_text


def test_slack_bot_message_flow_triggers_only_for_dm(tmp_path: Path) -> None:
    app = build_application(tmp_path.as_posix(), SandboxConfig(type="host"), runner_factory=_runner_factory(tmp_path))
    bot = app.bot
    bot.set_bot_user_id("B1")
    bot.set_startup_ts("1000.0")
    bot.add_user(SlackUser(id="U1", user_name="alice", display_name="Alice"))
    bot.add_channel(SlackChannel(id="D1", name="DM:alice"))
    bot.add_channel(SlackChannel(id="C1", name="general"))

    bot.emit_message({"channel": "C1", "channel_type": "channel", "ts": "1001.0", "user": "U1", "text": "plain chatter"})
    assert not bot.messages["C1"]
    assert "plain chatter" in (tmp_path / "C1" / "log.jsonl").read_text(encoding="utf-8")

    bot.emit_message({"channel": "D1", "channel_type": "im", "ts": "1002.0", "user": "U1", "text": "hello dm"})
    assert any("reply:[alice]: hello dm" in text for text in bot.messages["D1"].values())


class _FakeSyncClient:
    def users_list(self, *, limit: int, cursor: str | None = None) -> dict[str, object]:
        del limit, cursor
        return {"members": [{"id": "U1", "name": "alice", "real_name": "Alice"}]}

    def conversations_list(
        self,
        *,
        types: str,
        limit: int,
        cursor: str | None = None,
        exclude_archived: bool | None = None,
    ) -> dict[str, object]:
        del limit, cursor, exclude_archived
        if types == "public_channel,private_channel":
            return {"channels": [{"id": "C1", "name": "general", "is_member": True}]}
        if types == "im":
            return {"channels": [{"id": "D1", "user": "U1"}]}
        return {"channels": []}

    def conversations_history(
        self,
        *,
        channel: str,
        oldest: str | None = None,
        inclusive: bool = False,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> dict[str, object]:
        del inclusive, limit, cursor
        assert channel == "C1"
        assert oldest == "1000.0"
        return {
            "messages": [
                {"ts": "1002.0", "user": "B1", "text": "bot reply"},
                {"ts": "1001.0", "user": "U1", "text": "new user message"},
                {"ts": "1000.0", "user": "U1", "text": "already logged"},
                {"ts": "999.0", "bot_id": "OTHER", "text": "other bot"},
            ]
        }


def test_slack_bot_backfill_channel_only_appends_new_relevant_messages(tmp_path: Path) -> None:
    store = ChannelStore(ChannelStoreConfig(working_dir=tmp_path.as_posix(), bot_token="token"))

    class _Handler:
        def is_running(self, channel_id: str) -> bool:
            del channel_id
            return False

        def handle_event(self, event: SlackEvent, slack: SlackBot, is_event: bool = False) -> None:
            del event, slack, is_event

        def handle_stop(self, channel_id: str, slack: SlackBot) -> None:
            del channel_id, slack

    bot = SlackBot(_Handler(), store, bot_user_id="B1")
    bot.fetch_users(_FakeSyncClient())
    bot.fetch_channels(_FakeSyncClient())
    (tmp_path / "C1").mkdir()
    (tmp_path / "C1" / "log.jsonl").write_text(
        json.dumps({"date": "2026-01-01T00:00:00Z", "ts": "1000.0", "user": "U1", "text": "already logged", "attachments": [], "isBot": False})
        + "\n",
        encoding="utf-8",
    )

    count = bot.backfill_channel(_FakeSyncClient(), "C1")

    assert count == 2
    lines = [json.loads(line) for line in (tmp_path / "C1" / "log.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [line["ts"] for line in lines] == ["1000.0", "1001.0", "1002.0"]
    assert lines[-1]["isBot"] is True
