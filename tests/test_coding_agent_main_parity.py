from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from coding_agent.main import coding_agent_main
from coding_agent.core.session_manager import SessionManager


class _TtyInput(StringIO):
    def isatty(self) -> bool:  # noqa: D401
        return True


def test_coding_agent_main_text_mode_outputs_last_assistant_message(tmp_path) -> None:  # noqa: ANN001
    stdout = StringIO()
    stderr = StringIO()

    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "-p", "hello world"],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert "Echo: hello world" in stdout.getvalue()


def test_coding_agent_main_defaults_workspace_to_project_dot_pi(tmp_path) -> None:  # noqa: ANN001
    stdout = StringIO()
    stderr = StringIO()

    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "-p", "hello workspace"],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert (tmp_path / ".pi" / "sessions").exists()
    assert "Echo: hello workspace" in stdout.getvalue()


def test_coding_agent_main_list_models_outputs_table(tmp_path) -> None:  # noqa: ANN001
    stdout = StringIO()

    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--list-models"],
        stdout=stdout,
        stderr=StringIO(),
    )

    output = stdout.getvalue()
    assert code == 0
    assert "provider" in output
    assert "model" in output
    assert "mock" in output
    assert "echo" in output


def test_coding_agent_main_list_models_filters_results_from_settings(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "settings.json").write_text(
        json.dumps(
            {
                "defaultProvider": "openai",
                "defaultModel": "gpt-4o-mini",
                "enabledModels": ["anthropic/claude-3-7-sonnet", "openai/gpt-4o-mini"],
            }
        ),
        encoding="utf-8",
    )
    stdout = StringIO()

    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--agent-dir", agent_dir.as_posix(), "--list-models", "sonnet"],
        stdout=stdout,
        stderr=StringIO(),
    )

    output = stdout.getvalue()
    assert code == 0
    assert "anthropic" in output
    assert "claude-3-7-sonnet" in output
    assert "gpt-4o-mini" not in output


def test_coding_agent_main_interactive_mode_runs_repl_and_quits(tmp_path) -> None:  # noqa: ANN001
    stdin = _TtyInput("hello repl\n/quit\n")
    stdout = StringIO()

    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix()],
        stdin=stdin,
        stdout=stdout,
        stderr=StringIO(),
    )

    output = stdout.getvalue()
    assert code == 0
    assert "pi interactive mode" in output
    assert "pi> " in output
    assert "Echo: hello repl" in output
    assert "Bye." in output


def test_coding_agent_main_resume_uses_most_recent_session_in_non_tty_mode(tmp_path) -> None:  # noqa: ANN001
    session_dir = tmp_path / "sessions"
    first = SessionManager.create(tmp_path.as_posix(), session_dir=session_dir.as_posix())
    first.append_session_info("first")
    second = SessionManager.create(tmp_path.as_posix(), session_dir=session_dir.as_posix())
    second.append_session_info("second")

    stdout = StringIO()
    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--session-dir", session_dir.as_posix(), "--resume", "-p", "resume test"],
        stdin=StringIO(""),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert code == 0
    assert "Echo: resume test" in stdout.getvalue()
    assert "resume test" not in Path(first.get_session_file() or "").read_text(encoding="utf-8")
    assert "resume test" in Path(second.get_session_file() or "").read_text(encoding="utf-8")


def test_coding_agent_main_resume_prompts_for_session_selection_in_tty_mode(tmp_path) -> None:  # noqa: ANN001
    session_dir = tmp_path / "sessions"
    first = SessionManager.create(tmp_path.as_posix(), session_dir=session_dir.as_posix())
    first.append_session_info("first")
    second = SessionManager.create(tmp_path.as_posix(), session_dir=session_dir.as_posix())
    second.append_session_info("second")

    stdout = StringIO()
    stderr = StringIO()
    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--session-dir", session_dir.as_posix(), "--resume", "-p", "pick first"],
        stdin=_TtyInput("2\n"),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert "Available sessions:" in stdout.getvalue()
    assert "Select session" in stdout.getvalue()
    assert stderr.getvalue() == ""
    assert "pick first" in Path(first.get_session_file() or "").read_text(encoding="utf-8")
    assert "pick first" not in Path(second.get_session_file() or "").read_text(encoding="utf-8")


def test_coding_agent_main_text_mode_executes_slash_commands(tmp_path) -> None:  # noqa: ANN001
    stdout = StringIO()
    stderr = StringIO()

    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "-p", "/session"],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert "Session:" in stdout.getvalue()


def test_coding_agent_main_json_mode_streams_events(tmp_path) -> None:  # noqa: ANN001
    stdout = StringIO()

    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--mode", "json", "hello json"],
        stdout=stdout,
        stderr=StringIO(),
    )

    lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert code == 0
    assert lines[0]["type"] == "session"
    assert any(line.get("type") == "message_end" for line in lines)


def test_coding_agent_main_json_mode_requires_message(tmp_path) -> None:  # noqa: ANN001
    stderr = StringIO()
    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--mode", "json"],
        stdin=_TtyInput(""),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert code == 1
    assert "JSON mode requires at least one input message." in stderr.getvalue()


def test_coding_agent_main_export_flag_writes_html(tmp_path) -> None:  # noqa: ANN001
    export_path = tmp_path / "flag-export.html"
    stdout = StringIO()

    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "-p", "hello export flag", "--export", export_path.as_posix()],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert code == 0
    assert export_path.exists()
    assert export_path.as_posix() in stdout.getvalue()


def test_coding_agent_main_package_commands_manage_local_sources(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    stdout = StringIO()
    stderr = StringIO()

    install_code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--agent-dir", agent_dir.as_posix(), "install", package_dir.as_posix(), "--local"],
        stdout=stdout,
        stderr=stderr,
    )

    assert install_code == 0
    assert "Installed" in stdout.getvalue()
    settings_path = tmp_path / ".pi" / "settings.json"
    assert package_dir.as_posix() in settings_path.read_text(encoding="utf-8")

    stdout = StringIO()
    list_code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--agent-dir", agent_dir.as_posix(), "list"],
        stdout=stdout,
        stderr=StringIO(),
    )
    assert list_code == 0
    assert "Project packages:" in stdout.getvalue()
    assert package_dir.as_posix() in stdout.getvalue()

    stdout = StringIO()
    remove_code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--agent-dir", agent_dir.as_posix(), "remove", package_dir.as_posix(), "--local"],
        stdout=stdout,
        stderr=StringIO(),
    )
    assert remove_code == 0
    assert "Removed" in stdout.getvalue()
    assert '"packages"' not in settings_path.read_text(encoding="utf-8")


def test_coding_agent_main_config_outputs_package_resources(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    package_dir = tmp_path / "pkg"
    (package_dir / "prompts").mkdir(parents=True)
    (package_dir / "prompts" / "hello.md").write_text("hello", encoding="utf-8")
    coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--agent-dir", agent_dir.as_posix(), "install", package_dir.as_posix(), "--local"],
        stdout=StringIO(),
        stderr=StringIO(),
    )

    stdout = StringIO()
    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--agent-dir", agent_dir.as_posix(), "config"],
        stdout=stdout,
        stderr=StringIO(),
    )

    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["packages"]["project"] == [package_dir.as_posix()]
    assert payload["resources"]["prompts"][0]["path"].endswith("hello.md")


def test_coding_agent_main_slash_export_writes_html(tmp_path) -> None:  # noqa: ANN001
    export_path = tmp_path / "session.html"
    stdout = StringIO()

    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "-p", f"/export {export_path.as_posix()}"],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert code == 0
    assert export_path.exists()
    assert "<!DOCTYPE html>" in export_path.read_text(encoding="utf-8")
    html = export_path.read_text(encoding="utf-8")
    assert "Session ID" in html
    assert "Total Entries" in html
    assert "Exported session HTML to:" in stdout.getvalue()


def test_coding_agent_main_slash_share_writes_bundle(tmp_path) -> None:  # noqa: ANN001
    share_path = tmp_path / "session.share.json"
    stdout = StringIO()

    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "-p", "hello share", f"/share {share_path.as_posix()}"],
        stdout=stdout,
        stderr=StringIO(),
    )

    payload = json.loads(share_path.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["type"] == "pi-share-bundle"
    assert payload["stats"]["entries"] >= 1
    assert payload["htmlPreviewPath"]
    assert "Created share bundle:" in stdout.getvalue()


def test_coding_agent_main_executes_extension_commands(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    (agent_dir / "extensions").mkdir(parents=True)
    (agent_dir / "extensions" / "cmd_extension.py").write_text(
        "\n".join(
            [
                "from coding_agent.core.extensions import build_extension",
                "",
                "def create_extension():",
                "    def factory(api):",
                '        api.register_command("hello-ext", "hello from extension", lambda args, ctx: f"ext:{args[0]}")',
                "    return build_extension('cmd-ext', factory)",
            ]
        ),
        encoding="utf-8",
    )

    stdout = StringIO()
    code = coding_agent_main(
        ["--cwd", tmp_path.as_posix(), "--agent-dir", agent_dir.as_posix(), "-p", "/hello-ext parity"],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert code == 0
    assert "ext:parity" in stdout.getvalue()


def test_coding_agent_main_login_and_logout_persist_auth(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    login_stdout = StringIO()

    login_code = coding_agent_main(
        [
            "--cwd",
            tmp_path.as_posix(),
            "--agent-dir",
            agent_dir.as_posix(),
            "-p",
            "/login mock sk-test-key",
        ],
        stdout=login_stdout,
        stderr=StringIO(),
    )

    auth_path = agent_dir / "auth.json"
    assert login_code == 0
    assert auth_path.exists()
    assert json.loads(auth_path.read_text(encoding="utf-8")) == {"mock": {"type": "api_key", "key": "sk-test-key"}}
    assert "Stored credentials for provider: mock" in login_stdout.getvalue()

    logout_stdout = StringIO()
    logout_code = coding_agent_main(
        [
            "--cwd",
            tmp_path.as_posix(),
            "--agent-dir",
            agent_dir.as_posix(),
            "-p",
            "/logout mock",
        ],
        stdout=logout_stdout,
        stderr=StringIO(),
    )

    assert logout_code == 0
    assert json.loads(auth_path.read_text(encoding="utf-8")) == {}
    assert "Removed credentials for provider: mock" in logout_stdout.getvalue()


def test_coding_agent_main_rpc_mode_supports_prompt_state_and_commands(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    cwd = tmp_path / "workspace"
    (agent_dir / "extensions").mkdir(parents=True)
    (agent_dir / "skills" / "review").mkdir(parents=True)
    (agent_dir / "extensions" / "rpc_extension.py").write_text(
        "\n".join(
            [
                "from coding_agent.core.extensions import build_extension",
                "",
                "def create_extension():",
                "    def factory(api):",
                '        api.register_command("rpc-cmd", "rpc command")',
                "    return build_extension('rpc-ext', factory)",
            ]
        ),
        encoding="utf-8",
    )
    (agent_dir / "skills" / "review" / "SKILL.md").write_text(
        "---\ndescription: Review code changes carefully\n---\nUse this skill.\n",
        encoding="utf-8",
    )

    stdin = StringIO(
        "\n".join(
            [
                json.dumps({"id": "1", "type": "get_state"}),
                json.dumps({"id": "2", "type": "prompt", "message": "rpc hello"}),
                json.dumps({"id": "3", "type": "get_commands"}),
                json.dumps({"id": "4", "type": "shutdown"}),
            ]
        )
        + "\n"
    )
    stdout = StringIO()

    code = coding_agent_main(
        ["--mode", "rpc", "--cwd", cwd.as_posix(), "--agent-dir", agent_dir.as_posix()],
        stdin=stdin,
        stdout=stdout,
        stderr=StringIO(),
    )

    lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    responses = [line for line in lines if line.get("type") == "response"]
    assert code == 0
    assert any(line.get("command") == "get_state" and line.get("success") is True for line in responses)
    assert any(line.get("command") == "prompt" and line.get("success") is True for line in responses)
    commands_response = next(line for line in responses if line.get("command") == "get_commands")
    command_names = [item["name"] for item in commands_response["data"]["commands"]]
    assert "skill:review" in command_names
    assert "rpc-cmd" in command_names


def test_coding_agent_main_rpc_mode_supports_session_export_commands(tmp_path) -> None:  # noqa: ANN001
    export_path = tmp_path / "rpc-export.html"
    share_path = tmp_path / "rpc-share.json"
    stdin = StringIO(
        "\n".join(
            [
                json.dumps({"id": "1", "type": "prompt", "message": "hello rpc"}),
                json.dumps({"id": "2", "type": "set_session_name", "name": "demo"}),
                json.dumps({"id": "3", "type": "get_last_assistant_text"}),
                json.dumps({"id": "4", "type": "export_html", "outputPath": export_path.as_posix()}),
                json.dumps({"id": "5", "type": "share_session", "outputPath": share_path.as_posix()}),
                json.dumps({"id": "6", "type": "new_session"}),
                json.dumps({"id": "7", "type": "shutdown"}),
            ]
        )
        + "\n"
    )
    stdout = StringIO()

    code = coding_agent_main(
        ["--mode", "rpc", "--cwd", tmp_path.as_posix()],
        stdin=stdin,
        stdout=stdout,
        stderr=StringIO(),
    )

    responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    response_map = {line.get("command"): line for line in responses if line.get("type") == "response"}
    assert code == 0
    assert response_map["set_session_name"]["success"] is True
    assert response_map["get_last_assistant_text"]["data"]["text"] == "Echo: hello rpc"
    assert response_map["export_html"]["data"]["path"] == export_path.as_posix()
    assert response_map["share_session"]["data"]["path"] == share_path.as_posix()
    assert response_map["new_session"]["success"] is True
    assert export_path.exists()
    assert share_path.exists()
