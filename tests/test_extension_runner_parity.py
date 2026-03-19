from __future__ import annotations

from pathlib import Path
from time import time

from agent import AgentToolResult
from ai import AssistantMessage, Model, ScriptedBackend, Usage, text_block, tool_call_block
from coding_agent.core.extensions import ExtensionRunner, build_extension
from coding_agent.core.sdk import CreateAgentSessionOptions, create_agent_session
from coding_agent.core.session_manager import SessionManager


class _Tool:
    name = "echo_tool"
    label = "echo_tool"
    description = "Echo params"

    def execute(self, tool_call_id, params, signal=None, on_update=None):  # noqa: ANN001
        del tool_call_id, signal, on_update
        return AgentToolResult(content=[{"type": "text", "text": f"tool:{params['value']}"}], details={"ok": True})


def test_agent_session_tool_hooks_can_block_and_modify_result(tmp_path: Path) -> None:
    blocked = build_extension(
        "blocked",
        lambda api: api.on("tool_call", lambda event, ctx: {"block": event["input"]["value"] == "blocked", "reason": "blocked"}),  # noqa: ARG005
    )
    modified = build_extension(
        "modified",
        lambda api: api.on(
            "tool_result",
            lambda event, ctx: {"content": [{"type": "text", "text": "changed"}], "details": {"fromExtension": True}},  # noqa: ARG005
        ),
    )

    def responder(model, context, options):  # noqa: ANN001
        del options
        has_tool_result = any(getattr(message, "role", None) == "toolResult" for message in context.messages)
        value = "blocked" if any(getattr(message, "role", None) == "user" and "blocked" in str(message.content) for message in context.messages) else "ok"
        if not has_tool_result:
            return AssistantMessage(
                content=[tool_call_block("call-1", "echo_tool", {"value": value})],
                api=model.api,
                provider=model.provider,
                model=model.id,
                usage=Usage(),
                stop_reason="toolUse",
                timestamp=int(time() * 1000),
            )
        return AssistantMessage(
            content=[text_block("done")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    session = create_agent_session(
        options=CreateAgentSessionOptions(
            cwd=tmp_path.as_posix(),
            model=Model(provider="mock", id="echo", api="mock"),
            tools=[_Tool()],
            session_manager=SessionManager.in_memory(tmp_path.as_posix()),
            backend=ScriptedBackend(responder),
            extensions=[blocked, modified],
        )
    )

    session.prompt("run ok")
    tool_results = [message for message in session.state.messages if getattr(message, "role", None) == "toolResult"]
    assert tool_results[-1].content == [{"type": "text", "text": "changed"}]
    assert tool_results[-1].details == {"fromExtension": True}
    assert tool_results[-1].is_error is False

    session.new_session()
    session.prompt("run blocked")
    blocked_result = [message for message in session.state.messages if getattr(message, "role", None) == "toolResult"][-1]
    assert blocked_result.is_error is True
    assert blocked_result.content == [{"type": "text", "text": "changed"}]
    assert blocked_result.details == {"fromExtension": True}


def test_create_agent_session_before_agent_start_can_add_message_and_override_system_prompt(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def responder(model, context, options):  # noqa: ANN001
        del options
        captured["system_prompt"] = context.system_prompt
        captured["messages"] = context.messages
        return AssistantMessage(
            content=[text_block("ok")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    extension = build_extension(
        "prelude",
        lambda api: api.on(
            "before_agent_start",
            lambda event, ctx: {  # noqa: ARG005
                "message": {"customType": "note", "content": "prep context", "display": False, "details": {"source": "ext"}},
                "systemPrompt": "extension prompt",
            },
        ),
    )

    session = create_agent_session(
        options=CreateAgentSessionOptions(
            cwd=tmp_path.as_posix(),
            model=Model(provider="mock", id="echo", api="mock"),
            tools=[],
            session_manager=SessionManager.in_memory(tmp_path.as_posix()),
            backend=ScriptedBackend(responder),
            system_prompt="base prompt",
            extensions=[extension],
        )
    )
    session.prompt("hello")

    assert captured["system_prompt"] == "extension prompt"
    messages = captured["messages"]
    assert isinstance(messages, list)
    assert any(getattr(message, "role", None) == "user" for message in messages)
    assert any(
        any(block.get("type") == "text" and block.get("text") == "prep context" for block in getattr(message, "content", []))
        for message in messages
    )
    assert session.state.system_prompt == "base prompt"
    assert session.session_manager.get_entries()[0]["type"] == "custom_message"


def test_extension_context_handler_can_transform_messages(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def responder(model, context, options):  # noqa: ANN001
        del model, options
        captured["messages"] = context.messages
        return AssistantMessage(
            content=[text_block("done")],
            api="mock",
            provider="mock",
            model="echo",
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    extension = build_extension(
        "context",
        lambda api: api.on(
            "context",
            lambda event, ctx: {  # noqa: ARG005
                "messages": list(event["messages"])
                + [
                    {
                        "role": "custom",
                        "customType": "extra",
                        "content": "extra context",
                        "display": False,
                        "timestamp": 1,
                    }
                ]
            },
        ),
    )

    session = create_agent_session(
        options=CreateAgentSessionOptions(
            cwd=tmp_path.as_posix(),
            model=Model(provider="mock", id="echo", api="mock"),
            tools=[],
            session_manager=SessionManager.in_memory(tmp_path.as_posix()),
            backend=ScriptedBackend(responder),
            extensions=[extension],
        )
    )
    session.prompt("hello")

    messages = captured["messages"]
    assert isinstance(messages, list)
    assert any(
        any(block.get("type") == "text" and block.get("text") == "extra context" for block in getattr(message, "content", []))
        for message in messages
    )


def test_extension_can_override_compaction_result(tmp_path: Path) -> None:
    manager = SessionManager.in_memory(tmp_path.as_posix())
    manager.append_message({"role": "user", "content": "task A", "timestamp": 1})
    manager.append_message(
        {
            "role": "assistant",
            "content": [text_block("did A")],
            "api": "mock",
            "provider": "mock",
            "model": "echo",
            "usage": {"input": 10, "output": 5, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 15},
            "stopReason": "stop",
            "timestamp": 2,
        }
    )
    manager.append_message({"role": "user", "content": "task B", "timestamp": 3})

    extension = build_extension(
        "compact",
        lambda api: api.on(
            "session_before_compact",
            lambda event, ctx: {  # noqa: ARG005
                "compaction": {
                    "summary": "extension summary",
                    "firstKeptEntryId": event["preparation"]["firstKeptEntryId"],
                    "tokensBefore": event["preparation"]["tokensBefore"],
                    "details": {"source": "extension"},
                }
            },
        ),
    )

    session = create_agent_session(
        options=CreateAgentSessionOptions(
            cwd=tmp_path.as_posix(),
            model=Model(provider="mock", id="echo", api="mock", context_window=100),
            tools=[],
            session_manager=manager,
            backend=ScriptedBackend(
                lambda model, context, options: AssistantMessage(  # noqa: ARG005
                    content=[text_block("ok")],
                    api="mock",
                    provider="mock",
                    model="echo",
                    usage=Usage(),
                    stop_reason="stop",
                    timestamp=int(time() * 1000),
                )
            ),
            auto_retry=False,
            auto_compaction=False,
            extensions=[extension],
        )
    )

    result = session.compact()
    assert result["summary"] == "extension summary"
    assert manager.get_entries()[-1]["details"] == {"source": "extension"}
