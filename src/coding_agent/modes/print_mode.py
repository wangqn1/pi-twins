# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, TextIO

from ..core.agent_session import AgentSession


def run_print_mode(
    session: AgentSession,
    *,
    mode: str,
    messages: list[str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if mode not in {"text", "json"}:
        raise ValueError(f"Unsupported print mode: {mode}")

    unsubscribe = None
    if mode == "json":
        header = session.session_manager.get_header()
        if header is not None:
            stdout.write(json.dumps(_json_value(header), ensure_ascii=False) + "\n")

        def on_event(event: dict[str, Any]) -> None:
            stdout.write(json.dumps(_json_value(event), ensure_ascii=False) + "\n")

        unsubscribe = session.subscribe(on_event)

    try:
        for message in messages:
            session.prompt(message)
    finally:
        if unsubscribe is not None:
            unsubscribe()

    if mode == "text":
        last = next((message for message in reversed(session.state.messages) if getattr(message, "role", None) == "assistant"), None)
        if last is None:
            stderr.write("No assistant response\n")
            return 1
        stop_reason = getattr(last, "stop_reason", None) or getattr(last, "stopReason", None)
        if stop_reason in {"error", "aborted"}:
            error_message = getattr(last, "error_message", None) or getattr(last, "errorMessage", None) or stop_reason
            stderr.write(f"{error_message}\n")
            return 1
        content = getattr(last, "content", [])
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                stdout.write(f"{block.get('text', '')}\n")
    return 0


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value
