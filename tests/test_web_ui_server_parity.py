from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path
from time import time
from urllib.request import Request, urlopen

from ai import AssistantMessage, ScriptedBackend, Usage, text_block
from web_ui import WebUiBridgeConfig, create_web_ui_server
from web_ui.bridge import WebUiBridgeBackend


def _http_json(url: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    with urlopen(request) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def test_web_ui_server_serves_static_assets_and_python_engine_api(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    index_file = static_dir / "index.html"
    index_file.write_text("<!doctype html><title>py-twins web-ui test</title>", encoding="utf-8")

    def responder(model, context, options):  # noqa: ANN001
        del context, options
        return AssistantMessage(
            content=[text_block("bridge ok")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    server = create_web_ui_server(
        WebUiBridgeConfig(
            cwd=workspace.as_posix(),
            session_dir=session_dir.as_posix(),
            backend=ScriptedBackend(responder),
            with_tools=False,
        ),
        host="127.0.0.1",
        port=0,
        static_dir=static_dir,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])

    try:
        root_html = urlopen(f"http://127.0.0.1:{port}/").read().decode("utf-8")  # noqa: S310
        assert "py-twins web-ui test" in root_html

        state_response = _http_json(f"http://127.0.0.1:{port}/api/state")
        assert state_response["ok"] is True
        assert state_response["state"]["model"]["id"] == "qwen3.5-122b-vl"
        assert state_response["state"]["thinkingLevel"] == "off"

        prompt_response = _http_json(
            f"http://127.0.0.1:{port}/api/prompt",
            method="POST",
            payload={"message": "Say hello."},
        )
        assert prompt_response["ok"] is True
        assert any(event["type"] == "message_end" for event in prompt_response["events"])
        assert prompt_response["state"]["messages"][-1]["role"] == "assistant"
        assert prompt_response["state"]["messages"][-1]["content"][0]["text"] == "bridge ok"

        thinking_response = _http_json(
            f"http://127.0.0.1:{port}/api/thinking",
            method="POST",
            payload={"level": "low"},
        )
        assert thinking_response["state"]["thinkingLevel"] == "low"

        export_response = _http_json(
            f"http://127.0.0.1:{port}/api/export",
            method="POST",
            payload={"path": (tmp_path / "session.html").as_posix()},
        )
        assert Path(export_response["path"]).exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_ui_server_stream_prompt_emits_incremental_events(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("ok", encoding="utf-8")

    def fake_stream(model, context, options):  # noqa: ANN001
        del context, options
        from ai import AssistantMessageEventStream

        stream = AssistantMessageEventStream()
        partial = AssistantMessage(
            content=[],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )
        stream.push({"type": "start", "partial": partial})
        partial.content.append({"type": "text", "text": ""})
        stream.push({"type": "text_start", "contentIndex": 0, "partial": partial})
        partial.content[0]["text"] += "hel"
        stream.push({"type": "text_delta", "contentIndex": 0, "delta": "hel", "partial": partial})
        partial.content[0]["text"] += "lo"
        stream.push({"type": "text_end", "contentIndex": 0, "content": "hello", "partial": partial})
        stream.push({"type": "done", "reason": "stop", "message": partial})
        stream.end(partial)
        return stream

    server = create_web_ui_server(
        WebUiBridgeConfig(
            cwd=workspace.as_posix(),
            session_dir=(tmp_path / "sessions").as_posix(),
            with_tools=False,
            backend=None,
        ),
        host="127.0.0.1",
        port=0,
        static_dir=static_dir,
    )
    server.app.backend.session.agent.streamFn = fake_stream
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])

    try:
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps({"message": "hello"}).encode("utf-8")
        connection.request("POST", "/api/prompt/stream", body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        payload = response.read().decode("utf-8").strip().splitlines()
        records = [json.loads(line) for line in payload if line.strip()]
        event_types = [record["event"]["type"] for record in records if record.get("kind") == "event"]

        assert response.status == 200
        assert "message_update" in event_types
        assert any(record.get("kind") == "state" for record in records)
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_ui_bridge_supports_skill_commands(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_dir = workspace / ".pi" / "skills" / "refactor"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: Refactor code safely\n---\nUse this skill for structured refactors.\n",
        encoding="utf-8",
    )

    def responder(model, context, options):  # noqa: ANN001
        del options
        user_texts = [str(getattr(message, "content", "")) for message in context.messages if getattr(message, "role", None) == "user"]
        assert any("Use the following skill instructions" in text for text in user_texts)
        return AssistantMessage(
            content=[text_block("skill command ok")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("ok", encoding="utf-8")

    server = create_web_ui_server(
        WebUiBridgeConfig(
            cwd=workspace.as_posix(),
            session_dir=(tmp_path / "sessions").as_posix(),
            with_tools=False,
            backend=ScriptedBackend(responder),
        ),
        host="127.0.0.1",
        port=0,
        static_dir=static_dir,
    )
    try:
        result = server.app.prompt("/skill:refactor split this module safely")
        assert result["state"]["messages"][-1]["role"] == "assistant"
        assert result["state"]["messages"][-1]["content"][0]["text"] == "skill command ok"
    finally:
        server.server_close()


def test_web_ui_bridge_starts_fresh_by_default_without_resuming_recent_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"

    def responder(model, context, options):  # noqa: ANN001
        del context, options
        return AssistantMessage(
            content=[text_block("fresh session ok")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    first = WebUiBridgeBackend(
        WebUiBridgeConfig(
            cwd=workspace.as_posix(),
            session_dir=session_dir.as_posix(),
            backend=ScriptedBackend(responder),
            with_tools=False,
        )
    )
    first.prompt("remember this")
    assert len(first.get_state()["messages"]) == 2

    second = WebUiBridgeBackend(
        WebUiBridgeConfig(
            cwd=workspace.as_posix(),
            session_dir=session_dir.as_posix(),
            backend=ScriptedBackend(responder),
            with_tools=False,
        )
    )

    assert second.get_state()["messages"] == []
    assert second.get_state()["sessionId"] != first.get_state()["sessionId"]
