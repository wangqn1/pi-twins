from __future__ import annotations

from cli import main


def test_list_packages_command_returns_success(capsys) -> None:  # noqa: ANN001
    assert main(["list-packages"]) == 0
    output = capsys.readouterr().out
    assert "__pycache__" not in output
    assert "mom" not in output
    assert "pods" not in output


def test_agent_command_returns_success() -> None:
    assert main(["agent", "--message", "hello"]) == 0


def test_coding_agent_command_returns_success(monkeypatch, tmp_path, capsys) -> None:  # noqa: ANN001
    monkeypatch.setenv("PI_CONFIG_DIR", (tmp_path / ".pi-config").as_posix())
    assert main(["coding-agent", "--session-dir", (tmp_path / "sessions").as_posix(), "-p", "hello"]) == 0
    assert "Echo: hello" in capsys.readouterr().out


def test_coding_agent_command_passthrough_works_with_argv_none(monkeypatch, tmp_path, capsys) -> None:  # noqa: ANN001
    monkeypatch.setenv("PI_CONFIG_DIR", (tmp_path / ".pi-config").as_posix())
    monkeypatch.setattr(
        "sys.argv",
        ["cli.py", "coding-agent", "--cwd", "/tmp", "--session-dir", (tmp_path / "sessions").as_posix(), "-p", "hello"],
    )
    assert main() == 0
    assert "Echo: hello" in capsys.readouterr().out


def test_coding_agent_list_models_command_returns_success(capsys) -> None:  # noqa: ANN001
    assert main(["coding-agent", "--list-models"]) == 0
    output = capsys.readouterr().out
    assert "provider" in output
    assert "mock" in output


def test_coding_agent_package_list_command_returns_success(tmp_path, capsys) -> None:  # noqa: ANN001
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    assert main(["coding-agent", "--cwd", tmp_path.as_posix(), "install", pkg.as_posix(), "--local"]) == 0
    assert main(["coding-agent", "--cwd", tmp_path.as_posix(), "list"]) == 0
    output = capsys.readouterr().out
    assert "Project packages:" in output
    assert pkg.as_posix() in output
