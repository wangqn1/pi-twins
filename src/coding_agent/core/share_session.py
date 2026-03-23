# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def export_share_bundle(
    *,
    session_file: str,
    header: dict[str, Any] | None,
    entries: list[dict[str, Any]],
    output_path: str | None = None,
    html_path: str | None = None,
) -> str:
    source = Path(session_file)
    if not source.exists():
        raise ValueError(f"Session file not found: {session_file}")

    destination = Path(output_path) if output_path else source.with_suffix(".share.json")
    payload = {
        "type": "pi-share-bundle",
        "version": 1,
        "exportedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sessionFile": source.as_posix(),
        "sessionId": (header or {}).get("id"),
        "cwd": (header or {}).get("cwd"),
        "htmlPreviewPath": html_path,
        "stats": _share_stats(entries),
        "header": header,
        "entries": entries,
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination.as_posix()


def _share_stats(entries: list[dict[str, Any]]) -> dict[str, int]:
    user_messages = 0
    assistant_messages = 0
    tool_results = 0
    custom_entries = 0
    for entry in entries:
        entry_type = str(entry.get("type", ""))
        if entry_type == "message":
            role = (entry.get("message") or {}).get("role")
            if role == "user":
                user_messages += 1
            elif role == "assistant":
                assistant_messages += 1
            elif role == "toolResult":
                tool_results += 1
        elif entry_type.startswith("custom"):
            custom_entries += 1
    return {
        "entries": len(entries),
        "userMessages": user_messages,
        "assistantMessages": assistant_messages,
        "toolResults": tool_results,
        "customEntries": custom_entries,
    }
