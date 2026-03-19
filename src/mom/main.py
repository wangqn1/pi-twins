from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .download import download_channel
from .events import create_events_watcher
from .runner import MomRunner, get_or_create_runner
from .sandbox import SandboxConfig, parse_sandbox_arg, validate_sandbox
from .slack import ChannelInfo, MomHandler, SlackBot, SlackChannel, SlackContext, SlackEvent, SlackUser, UserInfo
from .store import ChannelStore, ChannelStoreConfig

MAX_MAIN_LENGTH = 35_000
MAX_THREAD_LENGTH = 20_000
TRUNCATION_NOTE = "\n\n_(message truncated, ask me to elaborate on specific parts)_"
WORKING_INDICATOR = " ..."


@dataclass
class ChannelState:
    running: bool
    runner: MomRunner
    store: ChannelStore
    stop_requested: bool = False
    stop_message_ts: str | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pi-mono-py mom", description="Run mom runtime")
    parser.add_argument("working_directory", nargs="?")
    parser.add_argument("--sandbox", default="host")
    parser.add_argument("--download")
    return parser.parse_args(argv)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - len(TRUNCATION_NOTE)] + TRUNCATION_NOTE


def create_slack_context(event: SlackEvent, slack: SlackBot, state: ChannelState, is_event: bool = False) -> SlackContext:
    message_ts: list[str | None] = [None]
    thread_messages: list[str] = []
    accumulated = [""]
    is_working = [False]
    event_filename = event.text.split(":", 2)[1] if is_event and event.text.startswith("[EVENT:") and ":" in event.text else None
    user = slack.get_user(event.user)

    def respond(text: str, should_log: bool = True) -> None:
        accumulated[0] = _truncate(text if not accumulated[0] else f"{accumulated[0]}\n{text}", MAX_MAIN_LENGTH)
        display = accumulated[0] + (WORKING_INDICATOR if is_working[0] else "")
        if message_ts[0] is None:
            message_ts[0] = slack.post_message(event.channel, display)
        else:
            slack.update_message(event.channel, message_ts[0], display)
        if should_log and message_ts[0] is not None:
            slack.log_bot_response(event.channel, text, message_ts[0])

    def replace_message(text: str) -> None:
        accumulated[0] = _truncate(text, MAX_MAIN_LENGTH)
        display = accumulated[0] + (WORKING_INDICATOR if is_working[0] else "")
        if message_ts[0] is None:
            message_ts[0] = slack.post_message(event.channel, display)
        else:
            slack.update_message(event.channel, message_ts[0], display)

    def respond_in_thread(text: str) -> None:
        if message_ts[0] is None:
            message_ts[0] = slack.post_message(event.channel, accumulated[0] + (WORKING_INDICATOR if is_working[0] else ""))
        thread_messages.append(slack.post_in_thread(event.channel, str(message_ts[0]), _truncate(text, MAX_THREAD_LENGTH)))

    def set_typing(is_typing: bool) -> None:
        if is_typing and message_ts[0] is None:
            accumulated[0] = f"_Starting event: {event_filename}_" if event_filename else "_Thinking_"
            message_ts[0] = slack.post_message(event.channel, accumulated[0] + WORKING_INDICATOR)

    def upload_file(file_path: str, title: str | None = None) -> None:
        slack.upload_file(event.channel, file_path, title)

    def set_working(working: bool) -> None:
        is_working[0] = working
        if message_ts[0] is not None:
            slack.update_message(event.channel, message_ts[0], accumulated[0] + (WORKING_INDICATOR if working else ""))

    def delete_message() -> None:
        for ts in reversed(thread_messages):
            slack.delete_message(event.channel, ts)
        if message_ts[0] is not None:
            slack.delete_message(event.channel, message_ts[0])
            message_ts[0] = None

    message = type(
        "SlackMessage",
        (),
        {
            "text": event.text,
            "raw_text": event.text,
            "user": event.user,
            "user_name": user.user_name if user else None,
            "channel": event.channel,
            "ts": event.ts,
            "attachments": [{"local": getattr(item, "local", item.get("local"))} for item in (event.attachments or [])],
            "timestamp": int(float(event.ts) * 1000),
        },
    )()

    return SlackContext(
        message=message,
        channel_name=slack.get_channel(event.channel).name if slack.get_channel(event.channel) else None,
        channels=[ChannelInfo(id=channel.id, name=channel.name) for channel in slack.get_all_channels()],
        users=[UserInfo(id=user.id, user_name=user.user_name, display_name=user.display_name) for user in slack.get_all_users()],
        respond=respond,
        replace_message=replace_message,
        respond_in_thread=respond_in_thread,
        set_typing=set_typing,
        upload_file=upload_file,
        set_working=set_working,
        delete_message=delete_message,
    )


def create_handler(
    working_dir: str,
    sandbox: SandboxConfig,
    *,
    runner_factory: Callable[[str, str], MomRunner] | None = None,
    bot_token: str | None = None,
) -> tuple[MomHandler, Callable[[str], ChannelState]]:
    channel_states: dict[str, ChannelState] = {}
    resolved_bot_token = bot_token or os.environ.get("MOM_SLACK_BOT_TOKEN") or "dummy"

    def get_state(channel_id: str) -> ChannelState:
        state = channel_states.get(channel_id)
        if state is None:
            channel_dir = str(Path(working_dir) / channel_id)
            runner = runner_factory(channel_id, channel_dir) if runner_factory is not None else get_or_create_runner(sandbox, channel_id, channel_dir)
            state = ChannelState(
                running=False,
                runner=runner,
                store=ChannelStore(ChannelStoreConfig(working_dir=working_dir, bot_token=resolved_bot_token)),
            )
            channel_states[channel_id] = state
        return state

    class _Handler:
        def is_running(self, channel_id: str) -> bool:
            return get_state(channel_id).running

        def handle_stop(self, channel_id: str, slack: SlackBot) -> None:
            state = get_state(channel_id)
            if state.running:
                state.stop_requested = True
                state.runner.abort()
                state.stop_message_ts = slack.post_message(channel_id, "_Stopping..._")
            else:
                slack.post_message(channel_id, "_Nothing running_")

        def handle_event(self, event: SlackEvent, slack: SlackBot, is_event: bool = False) -> None:
            state = get_state(event.channel)
            state.running = True
            state.stop_requested = False
            ctx = None
            try:
                ctx = create_slack_context(event, slack, state, is_event=is_event)
                ctx.set_typing(True)
                ctx.set_working(True)
                result = state.runner.run(ctx, state.store)
                if result.get("stopReason") == "aborted" and state.stop_requested:
                    if state.stop_message_ts:
                        slack.update_message(event.channel, state.stop_message_ts, "_Stopped_")
                        state.stop_message_ts = None
                    else:
                        slack.post_message(event.channel, "_Stopped_")
            finally:
                if ctx is not None:
                    ctx.set_working(False)
                state.running = False

    return _Handler(), get_state


@dataclass
class MomApplication:
    working_dir: str
    sandbox: SandboxConfig
    bot: SlackBot
    events_watcher: Any
    get_state: Callable[[str], ChannelState]

    def start(self) -> None:
        Path(self.working_dir).mkdir(parents=True, exist_ok=True)
        self.events_watcher.start()
        self.bot.start()

    def stop(self) -> None:
        self.events_watcher.stop()


def build_application(
    working_dir: str,
    sandbox: SandboxConfig,
    *,
    bot: SlackBot | None = None,
    runner_factory: Callable[[str, str], MomRunner] | None = None,
    bot_token: str | None = None,
) -> MomApplication:
    resolved_bot_token = bot_token or os.environ.get("MOM_SLACK_BOT_TOKEN") or "dummy"
    shared_store = ChannelStore(ChannelStoreConfig(working_dir=working_dir, bot_token=resolved_bot_token))
    handler, get_state = create_handler(working_dir, sandbox, runner_factory=runner_factory, bot_token=resolved_bot_token)
    slack = bot or SlackBot(handler, shared_store)
    events_watcher = create_events_watcher(working_dir, slack)
    return MomApplication(working_dir=working_dir, sandbox=sandbox, bot=slack, events_watcher=events_watcher, get_state=get_state)


def main(
    argv: list[str] | None = None,
    *,
    download_channel_fn: Callable[[str, str], dict[str, Any]] | None = None,
) -> int:
    args = parse_args(argv)
    if args.download:
        bot_token = os.environ.get("MOM_SLACK_BOT_TOKEN")
        if not bot_token:
            print(json.dumps({"ok": False, "error": "Missing env: MOM_SLACK_BOT_TOKEN"}, ensure_ascii=False, indent=2))
            return 1
        downloader = download_channel_fn or download_channel
        downloader(args.download, bot_token)
        return 0
    if not args.working_directory:
        print(json.dumps({"ok": False, "error": "working directory is required"}, ensure_ascii=False, indent=2))
        return 1
    sandbox = parse_sandbox_arg(args.sandbox)
    validate_sandbox(sandbox)
    app = build_application(str(Path(args.working_directory).resolve()), sandbox)
    app.start()
    print(
        json.dumps(
            {
                "ok": True,
                "workingDirectory": app.working_dir,
                "sandbox": {"type": app.sandbox.type, "container": app.sandbox.container},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0
