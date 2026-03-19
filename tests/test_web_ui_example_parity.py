from __future__ import annotations

import os
from pathlib import Path
from time import time

import pytest

from ai import AssistantMessage, ScriptedBackend, Usage, text_block, tool_call_block
from web_ui.example_app import WebUiExampleConfig, WebUiStyleExampleApp


def test_web_ui_style_example_runs_tool_loop_and_persists_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"

    def responder(model, context, options):  # noqa: ANN001
        del options
        has_tool_result = any(getattr(message, "role", None) == "toolResult" for message in context.messages)
        if not has_tool_result:
            return AssistantMessage(
                content=[tool_call_block("call-write-1", "write", {"path": "note.txt", "content": "hello from web-ui example"})],
                api=model.api,
                provider=model.provider,
                model=model.id,
                usage=Usage(),
                stop_reason="toolUse",
                timestamp=int(time() * 1000),
            )
        return AssistantMessage(
            content=[text_block("scripted flow complete")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    app = WebUiStyleExampleApp.create(
        WebUiExampleConfig(
            cwd=workspace.as_posix(),
            session_dir=session_dir.as_posix(),
            backend=ScriptedBackend(responder),
            with_tools=True,
        )
    )

    reply = app.send("Create a file named note.txt with hello from the example.")
    snapshot = app.snapshot()
    exported = app.export_html((tmp_path / "session.html").as_posix())

    assert reply == "scripted flow complete"
    assert snapshot["title"].startswith("Create a file named note")
    assert snapshot["stats"]["toolCalls"] == 1
    assert snapshot["stats"]["toolResults"] == 1
    assert Path(snapshot["sessionFile"]).exists()
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "hello from web-ui example"
    assert Path(exported).exists()

    reopened = WebUiStyleExampleApp.open(
        WebUiExampleConfig(
            cwd=workspace.as_posix(),
            session_dir=session_dir.as_posix(),
            backend=ScriptedBackend(responder),
            with_tools=True,
        ),
        snapshot["sessionFile"],
    )
    reopened_snapshot = reopened.snapshot()
    assert reopened_snapshot["lastAssistantText"] == "scripted flow complete"
    assert reopened_snapshot["stats"]["assistantMessages"] == 2


@pytest.mark.skipif(
    os.environ.get("RUN_LLM_EXAMPLE") != "1" or not os.environ.get("LLM_API_KEY"),
    reason="Set RUN_LLM_EXAMPLE=1 and LLM_API_KEY to run the real LLM example.",
)
def test_web_ui_style_example_can_run_against_real_openai_compatible_model(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"

    app = WebUiStyleExampleApp.create(
        WebUiExampleConfig.from_env(
            cwd=workspace.as_posix(),
            session_dir=session_dir.as_posix(),
            with_tools=False,
        )
    )

    reply = app.send("Reply with exactly OK.")
    snapshot = app.snapshot()

    assert reply is not None
    assert "OK" in reply.upper()
    assert snapshot["stats"]["userMessages"] >= 1
    assert snapshot["stats"]["assistantMessages"] >= 1
