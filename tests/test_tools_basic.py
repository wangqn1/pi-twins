from __future__ import annotations

import base64
from pathlib import Path

import pytest

from coding_agent.core.tools import ScreenshotTool, ToolExecutionError, ToolRegistry


def test_write_read_edit_roundtrip(tmp_path: Path) -> None:
    registry = ToolRegistry(str(tmp_path))

    write_result = registry.run("write", {"path": "a.txt", "content": "hello\nworld"})
    assert "Successfully wrote" in write_result.content[0]["text"]

    read_result = registry.run("read", {"path": "a.txt"})
    assert "hello" in read_result.content[0]["text"]

    edit_result = registry.run(
        "edit",
        {"path": "a.txt", "oldText": "hello", "newText": "hi"},
    )
    assert "Successfully replaced text" in edit_result.content[0]["text"]

    read_result_2 = registry.run("read", {"path": "a.txt"})
    assert "hi\nworld" in read_result_2.content[0]["text"]


def test_bash_tool_success(tmp_path: Path) -> None:
    registry = ToolRegistry(str(tmp_path))
    result = registry.run("bash", {"command": "echo 123"})
    assert "123" in result.content[0]["text"]


def test_bash_tool_non_zero_exit(tmp_path: Path) -> None:
    registry = ToolRegistry(str(tmp_path))
    with pytest.raises(ToolExecutionError):
        registry.run("bash", {"command": "exit 2"})


def test_find_ls_grep(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "one.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "src" / "two.txt").write_text("alpha\nbeta\nhello\n", encoding="utf-8")

    registry = ToolRegistry(str(tmp_path))

    ls_result = registry.run("ls", {"path": "src"})
    assert "one.py" in ls_result.content[0]["text"]

    find_result = registry.run("find", {"path": "src", "pattern": "*.py"})
    assert "one.py" in find_result.content[0]["text"]

    grep_result = registry.run("grep", {"path": "src", "pattern": "hello"})
    assert "hello" in grep_result.content[0]["text"]


def test_screenshot_tool_returns_multimodal_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr("coding_agent.core.tools.screenshot.platform.system", lambda: "Darwin")

    def fake_capture(args: list[str]) -> None:
        calls.append(args)
        Path(args[-1]).write_bytes(b"\x89PNG\r\n\x1a\nfake-image")

    tool = ScreenshotTool(str(tmp_path), capture_runner=fake_capture)
    result = tool.run(path="shots/browser.png", interactive=True)

    assert calls == [["screencapture", "-x", "-i", str(tmp_path / "shots" / "browser.png")]]
    assert "Captured screenshot" in result.content[0]["text"]
    assert result.content[1]["type"] == "image"
    assert result.content[1]["mimeType"] == "image/png"
    assert base64.b64decode(result.content[1]["data"]).startswith(b"\x89PNG")
    assert result.details == {"path": str(tmp_path / "shots" / "browser.png"), "interactive": True}
