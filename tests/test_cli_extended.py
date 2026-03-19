from __future__ import annotations

from cli import main


def test_list_packages_command_returns_success(capsys) -> None:  # noqa: ANN001
    assert main(["list-packages"]) == 0
    output = capsys.readouterr().out
    assert "__pycache__" not in output


def test_agent_command_returns_success() -> None:
    assert main(["agent", "--message", "hello"]) == 0


def test_coding_agent_command_returns_success(capsys) -> None:  # noqa: ANN001
    assert main(["coding-agent", "-p", "hello"]) == 0
    assert "Echo: hello" in capsys.readouterr().out


def test_coding_agent_command_passthrough_works_with_argv_none(monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setattr("sys.argv", ["cli.py", "coding-agent", "--cwd", "/tmp", "-p", "hello"])
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


def test_mom_command_returns_success(tmp_path, capsys) -> None:  # noqa: ANN001
    assert main(["mom", tmp_path.as_posix()]) == 0
    assert "\"ok\": true" in capsys.readouterr().out.lower()
