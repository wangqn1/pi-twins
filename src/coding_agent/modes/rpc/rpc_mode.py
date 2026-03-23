# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, TextIO

from ...core.agent_session import AgentSession
from ...core.slash_commands import build_slash_commands
from .rpc_types import RpcCommand


def run_rpc_mode(
    session: AgentSession,
    *,
    stdin: TextIO,
    stdout: TextIO,
) -> int:
    def emit(payload: dict[str, Any]) -> None:
        stdout.write(json.dumps(_json_value(payload), ensure_ascii=False) + "\n")

    def success(command: str, command_id: str | None = None, data: Any = None) -> None:
        payload: dict[str, Any] = {"type": "response", "command": command, "success": True}
        if command_id is not None:
            payload["id"] = command_id
        if data is not None:
            payload["data"] = data
        emit(payload)

    def failure(command: str, message: str, command_id: str | None = None) -> None:
        payload: dict[str, Any] = {"type": "response", "command": command, "success": False, "error": message}
        if command_id is not None:
            payload["id"] = command_id
        emit(payload)

    unsubscribe = session.subscribe(lambda event: emit(_json_value(event)))
    try:
        for raw_line in stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                command: RpcCommand = json.loads(line)
            except json.JSONDecodeError as exc:
                failure("unknown", f"Invalid JSON: {exc}")
                continue
            command_type = str(command.get("type", ""))
            command_id = str(command["id"]) if "id" in command else None
            try:
                if command_type == "prompt":
                    session.prompt(str(command.get("message", "")))
                    success("prompt", command_id)
                elif command_type == "abort":
                    session.abort()
                    success("abort", command_id)
                elif command_type == "get_state":
                    success("get_state", command_id, _get_state(session))
                elif command_type == "get_messages":
                    success("get_messages", command_id, {"messages": _json_value(session.state.messages)})
                elif command_type == "new_session":
                    path = session.new_session()
                    success("new_session", command_id, {"cancelled": False, "path": path})
                elif command_type == "switch_session":
                    target = str(command.get("sessionPath", ""))
                    session.switch_session(target)
                    success("switch_session", command_id, {"cancelled": False})
                elif command_type == "set_thinking_level":
                    session.set_thinking_level(str(command.get("level", "off")))
                    success("set_thinking_level", command_id)
                elif command_type == "set_session_name":
                    name = str(command.get("name", "")).strip()
                    if not name:
                        raise ValueError("Session name cannot be empty")
                    session.set_session_name(name)
                    success("set_session_name", command_id)
                elif command_type == "set_auto_retry":
                    session.set_auto_retry(bool(command.get("enabled", True)))
                    success("set_auto_retry", command_id)
                elif command_type == "set_auto_compaction":
                    session.set_auto_compaction(bool(command.get("enabled", True)))
                    success("set_auto_compaction", command_id)
                elif command_type == "compact":
                    result = session.compact(str(command.get("customInstructions") or "") or None)
                    success("compact", command_id, result)
                elif command_type == "get_session_stats":
                    success("get_session_stats", command_id, _json_value(session.get_session_stats()))
                elif command_type == "get_last_assistant_text":
                    success("get_last_assistant_text", command_id, {"text": session.get_last_assistant_text()})
                elif command_type == "export_html":
                    output_path = command.get("outputPath")
                    success("export_html", command_id, {"path": session.export_to_html(str(output_path) if output_path else None)})
                elif command_type == "share_session":
                    output_path = command.get("outputPath")
                    success("share_session", command_id, {"path": session.share_session(str(output_path) if output_path else None)})
                elif command_type == "get_commands":
                    include_skills = session.settings_manager.get_enable_skill_commands()
                    commands = build_slash_commands(
                        prompts=session.prompt_templates,
                        skills=session.resource_loader.getSkills()["skills"] if include_skills else [],
                        extension_commands=session.extension_runner.registered_commands if session.extension_runner else [],
                    )
                    success("get_commands", command_id, {"commands": _json_value(commands)})
                elif command_type == "shutdown":
                    success("shutdown", command_id)
                    return 0
                else:
                    failure(command_type or "unknown", "Unsupported RPC command", command_id)
            except Exception as exc:  # noqa: BLE001
                failure(command_type or "unknown", str(exc), command_id)
    finally:
        unsubscribe()
    return 0


def _get_state(session: AgentSession) -> dict[str, Any]:
    return {
        "model": _json_value(session.model),
        "thinkingLevel": session.thinking_level,
        "isStreaming": bool(session.state.is_streaming),
        "steeringMode": session.agent.getSteeringMode(),
        "followUpMode": session.agent.getFollowUpMode(),
        "sessionFile": session.session_file,
        "sessionId": session.session_id,
        "autoCompactionEnabled": bool(session.auto_compaction),
        "autoRetryEnabled": bool(session.auto_retry),
        "messageCount": len(session.state.messages),
        "pendingMessageCount": int(session.agent.hasQueuedMessages()),
    }


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
