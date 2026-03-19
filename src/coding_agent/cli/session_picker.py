from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from ..core.session_manager import SessionManager


def select_session_path(
    *,
    cwd: str,
    session_dir: str | None,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> str | None:
    sessions = SessionManager.list(cwd, session_dir=session_dir)
    if not sessions:
        stderr.write("No sessions available to resume.\n")
        return None

    if not stdin.isatty():
        return str(sessions[0]["path"])

    stdout.write("Available sessions:\n")
    for index, session in enumerate(sessions, start=1):
        stdout.write(f"{index}. {_format_session(session)}\n")

    while True:
        stdout.write(f"Select session [1-{len(sessions)}] or q: ")
        choice = stdin.readline()
        if choice == "":
            stdout.write("\n")
            return None

        text = choice.strip().lower()
        if text in {"q", "quit", "exit"}:
            return None
        if text.isdigit():
            position = int(text)
            if 1 <= position <= len(sessions):
                return str(sessions[position - 1]["path"])
        stderr.write("Invalid selection.\n")


def _format_session(session: dict[str, object]) -> str:
    path = str(session.get("path", ""))
    session_id = str(session.get("id", ""))
    created = _format_created(str(session.get("created", "")))
    name = _read_session_name(path)
    parts = [name or Path(path).name]
    if created:
        parts.append(created)
    if session_id:
        parts.append(session_id)
    parts.append(path)
    return " | ".join(parts)


def _read_session_name(path: str) -> str | None:
    file = Path(path)
    if not file.exists():
        return None
    try:
        for raw_line in reversed(file.read_text(encoding="utf-8").splitlines()):
            if not raw_line.strip():
                continue
            entry = json.loads(raw_line)
            if isinstance(entry, dict) and entry.get("type") == "session_info" and entry.get("name"):
                return str(entry["name"]).strip() or None
    except Exception:  # noqa: BLE001
        return None
    return None


def _format_created(value: str) -> str:
    if not value:
        return ""
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
