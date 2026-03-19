from __future__ import annotations

from pathlib import Path
from time import time

from ai import AssistantMessage, Model, ScriptedBackend, Usage, text_block
from mom import (
    MomRunner,
    MomRunnerConfig,
    PendingMessage,
    SandboxConfig,
    build_system_prompt,
    create_executor,
    parse_sandbox_arg,
)
from mom.tools import create_mom_tools


class _Message:
    def __init__(self, text: str, user: str = "U1", user_name: str = "alice", timestamp: int | None = None) -> None:
        self.text = text
        self.user = user
        self.user_name = user_name
        self.timestamp = timestamp or int(time() * 1000)
        self.ts = str(self.timestamp)


class _Ctx:
    def __init__(self, text: str) -> None:
        self.message = _Message(text)
        self.responses: list[str] = []
        self.uploads: list[tuple[str, str | None]] = []
        self.typing: list[bool] = []

    def respond(self, text: str) -> None:
        self.responses.append(text)

    def upload_file(self, file_path: str, title: str | None = None) -> None:
        self.uploads.append((file_path, title))

    def set_typing(self, value: bool) -> None:
        self.typing.append(value)


def test_parse_sandbox_arg_and_executor_host() -> None:
    host = parse_sandbox_arg("host")
    assert host.type == "host"
    docker = parse_sandbox_arg("docker:mom")
    assert docker.type == "docker"
    assert docker.container == "mom"
    executor = create_executor(host)
    result = executor.exec("printf 'ok'")
    assert result.stdout == "ok"


def test_create_mom_tools_exposes_expected_tool_names() -> None:
    tools = create_mom_tools(create_executor(SandboxConfig(type="host")))
    assert [tool.name for tool in tools] == ["read", "bash", "edit", "write", "attach"]


def test_build_system_prompt_includes_memory(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("global memory", encoding="utf-8")
    channel_dir = tmp_path / "C1"
    channel_dir.mkdir()
    (channel_dir / "MEMORY.md").write_text("channel memory", encoding="utf-8")
    from mom import MomWorkspace

    prompt = build_system_prompt(MomWorkspace(tmp_path.as_posix()), "C1", "/workspace")
    assert "global memory" in prompt
    assert "channel memory" in prompt
    assert "/workspace/C1" in prompt


def test_mom_runner_uses_scripted_backend_and_responds(tmp_path: Path) -> None:
    channel_dir = tmp_path / "C1"
    channel_dir.mkdir()

    def responder(model, context, options):  # noqa: ANN001
        del options
        texts: list[str] = []
        for message in context.messages:
            content = getattr(message, "content", [])
            if isinstance(content, list):
                texts.extend(str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text")
        return AssistantMessage(
            content=[text_block(f"handled: {texts[-1]}")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    runner = MomRunner(
        MomRunnerConfig(
            sandbox=SandboxConfig(type="host"),
            workspace_dir=tmp_path.as_posix(),
            channel_id="C1",
            backend=ScriptedBackend(responder),
            model=Model(provider="mock", id="echo", api="mock"),
        )
    )
    ctx = _Ctx("hello mom")
    result = runner.run(ctx)
    assert result["stopReason"] == "stop"
    assert ctx.responses[-1].startswith("handled: [alice]: hello mom")
    assert ctx.typing == [True, False]


def test_mom_runner_supports_pending_messages(tmp_path: Path) -> None:
    channel_dir = tmp_path / "C1"
    channel_dir.mkdir()

    def responder(model, context, options):  # noqa: ANN001
        del model, options
        last = context.messages[-1]
        content = getattr(last, "content", [])
        text = next((block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"), "")
        return AssistantMessage(
            content=[text_block(f"pending:{text}")],
            api="mock",
            provider="mock",
            model="echo",
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    runner = MomRunner(
        MomRunnerConfig(
            sandbox=SandboxConfig(type="host"),
            workspace_dir=tmp_path.as_posix(),
            channel_id="C1",
            backend=ScriptedBackend(responder),
            model=Model(provider="mock", id="echo", api="mock"),
        )
    )
    ctx = _Ctx("current")
    result = runner.run(ctx, pending_messages=[PendingMessage(user_name="bob", text="pending first")])
    assert result["stopReason"] == "stop"
    assert "current" in ctx.responses[-1]
