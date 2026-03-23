# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from typing import TextIO

from ...core.agent_session import AgentSession


def run_interactive_mode(
    session: AgentSession,
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    stdout.write("pi interactive mode\n")
    stdout.write("Type /quit to exit.\n")

    while True:
        stdout.write("pi> ")
        line = stdin.readline()
        if line == "":
            stdout.write("\n")
            return 0

        text = line.strip()
        if not text:
            continue
        if text in {"/quit", "/exit"}:
            stdout.write("Bye.\n")
            return 0

        before_count = len(session.state.messages)
        session.prompt(text)
        _render_new_assistant_messages(session, before_count, stdout)


def _render_new_assistant_messages(session: AgentSession, before_count: int, stdout: TextIO) -> None:
    new_messages = session.state.messages[before_count:]
    for message in new_messages:
        if getattr(message, "role", None) != "assistant":
            continue
        stop_reason = getattr(message, "stop_reason", None) or getattr(message, "stopReason", None)
        if stop_reason in {"error", "aborted"}:
            error_message = getattr(message, "error_message", None) or getattr(message, "errorMessage", None) or stop_reason
            stdout.write(f"{error_message}\n")
            continue
        content = getattr(message, "content", [])
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                stdout.write(f"{block.get('text', '')}\n")
