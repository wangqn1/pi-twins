from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from time import sleep
from time import time

from agent import Agent, AgentToolResult
from ai import (
    AssistantMessage,
    AssistantMessageEventStream,
    Model,
    ScriptedBackend,
    Usage,
    text_block,
    tool_call_block,
)
from coding_agent.core.tools import create_coding_tools


def _role(message: object) -> str | None:
    if isinstance(message, dict):
        return message.get("role")
    return getattr(message, "role", None)


def test_agent_tool_loop_matches_core_behavior(tmp_path: Path) -> None:
    def responder(model, context, options):  # noqa: ANN001
        del options
        has_tool_result = any(_role(message) == "toolResult" for message in context.messages)
        if not has_tool_result:
            return AssistantMessage(
                content=[tool_call_block("call_write_1", "write", {"path": "note.txt", "content": "hello parity"})],
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

    events: list[str] = []
    agent = Agent(backend=ScriptedBackend(responder))
    agent.set_tools(create_coding_tools(str(tmp_path)))
    agent.subscribe(lambda event: events.append(event["type"]))

    agent.prompt("create file")

    created = tmp_path / "note.txt"
    assert created.exists()
    assert created.read_text(encoding="utf-8") == "hello parity"
    assert "tool_execution_start" in events
    assert "tool_execution_end" in events
    assert events[0] == "agent_start"
    assert events[-1] == "agent_end"


def test_agent_stream_fn_emits_message_update_events() -> None:
    events: list[str] = []

    def fake_stream(model, context, options):  # noqa: ANN001
        del context, options
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

    agent = Agent(
        initial_state=None,
        stream_fn=fake_stream,
        session_id="session-1",
        transport="sse",
        thinking_budgets={"high": 4096},
    )
    agent.set_model(Model(provider="mock", id="echo", api="mock"))
    agent.subscribe(lambda event: events.append(event["type"]))

    agent.prompt("hello")

    assert "message_update" in events
    assert agent.state.messages[-1].content[0]["text"] == "hello"
    assert agent.session_id == "session-1"
    assert agent.thinking_budgets == {"high": 4096}


def test_agent_scripted_backend_also_emits_message_update_events() -> None:
    events: list[str] = []

    def responder(model, context, options):  # noqa: ANN001
        del context, options
        return AssistantMessage(
            content=[text_block("hello from backend")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    agent = Agent(backend=ScriptedBackend(responder))
    agent.subscribe(lambda event: events.append(event["type"]))
    agent.prompt("hello")

    assert "message_update" in events


def test_agent_abort_and_wait_for_idle() -> None:
    started = Event()

    class BlockingTool:
        name = "block"
        label = "block"
        description = "blocks"
        parameters = {"type": "object", "properties": {}, "required": []}

        def execute(self, tool_call_id, params, signal=None, on_update=None):  # noqa: ANN001
            del tool_call_id, params, on_update
            started.set()
            while signal is None or not signal.aborted:
                sleep(0.01)
            signal.throw_if_aborted()
            raise AssertionError("unreachable")

    def responder(model, context, options):  # noqa: ANN001
        del options
        has_tool_result = any(_role(message) == "toolResult" for message in context.messages)
        if not has_tool_result:
            return AssistantMessage(
                content=[tool_call_block("call_block_1", "block", {})],
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

    agent = Agent(backend=ScriptedBackend(responder))
    agent.set_tools([BlockingTool()])
    thread = Thread(target=lambda: agent.prompt("block"), daemon=True)
    thread.start()
    assert started.wait(1.0)
    agent.abort()
    agent.wait_for_idle(1.0)
    thread.join(1.0)

    assert not thread.is_alive()
    assert agent.state.is_streaming is False
    assert getattr(agent.state.messages[-1], "stop_reason", None) == "aborted"


def test_agent_validates_tool_arguments() -> None:
    class SchemaTool:
        name = "schema"
        label = "schema"
        description = "validates"
        parameters = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

        def execute(self, tool_call_id, params, signal=None, on_update=None):  # noqa: ANN001
            del tool_call_id, signal, on_update
            return AgentToolResult(content=[text_block(params["path"])], details={})

    def responder(model, context, options):  # noqa: ANN001
        del options
        has_tool_result = any(_role(message) == "toolResult" for message in context.messages)
        if not has_tool_result:
            return AssistantMessage(
                content=[tool_call_block("call_schema_1", "schema", {})],
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

    agent = Agent(backend=ScriptedBackend(responder))
    agent.set_tools([SchemaTool()])
    agent.prompt("validate")

    tool_results = [message for message in agent.state.messages if _role(message) == "toolResult"]
    assert tool_results
    assert tool_results[-1].is_error is True
    assert "Missing required tool argument: path" in tool_results[-1].content[0]["text"]


def test_agent_tool_hooks_can_block_and_patch_results() -> None:
    class EchoTool:
        name = "echo"
        label = "echo"
        description = "echoes"
        parameters = {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}

        def execute(self, tool_call_id, params, signal=None, on_update=None):  # noqa: ANN001
            del tool_call_id, signal, on_update
            return AgentToolResult(content=[text_block(f"tool:{params['value']}")], details={"raw": params["value"]})

    def responder(model, context, options):  # noqa: ANN001
        del options
        has_tool_result = any(_role(message) == "toolResult" for message in context.messages)
        value = "blocked" if any(_role(message) == "user" and "blocked" in str(getattr(message, "content", "")) for message in context.messages) else "ok"
        if not has_tool_result:
            return AssistantMessage(
                content=[tool_call_block("call_echo_1", "echo", {"value": value})],
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

    agent = Agent(backend=ScriptedBackend(responder))
    agent.set_tools([EchoTool()])
    agent.set_before_tool_call(lambda payload, signal=None: {"block": True, "reason": "blocked"} if payload["args"]["value"] == "blocked" else None)
    agent.set_after_tool_call(
        lambda payload, signal=None: {
            "content": [text_block("patched")],
            "details": {"hook": True},
            "isError": payload["isError"],
        }
    )

    agent.prompt("run ok")
    first_result = [message for message in agent.state.messages if _role(message) == "toolResult"][-1]
    assert first_result.content == [text_block("patched")]
    assert first_result.details == {"hook": True}
    assert first_result.is_error is False

    agent.reset()
    agent.prompt("run blocked")
    blocked_result = [message for message in agent.state.messages if _role(message) == "toolResult"][-1]
    assert blocked_result.content == [text_block("patched")]
    assert blocked_result.details == {"hook": True}
    assert blocked_result.is_error is True


def test_agent_camelcase_api_aliases_match_ts_shape() -> None:
    agent = Agent(session_id="session-a", thinking_budgets={"high": 1}, max_retry_delay_ms=123)

    agent.setSystemPrompt("sys")
    agent.setSteeringMode("all")
    agent.setFollowUpMode("all")
    agent.steer({"role": "user", "content": "queued-1"})
    agent.followUp({"role": "user", "content": "queued-2"})
    agent.appendMessage({"role": "user", "content": "existing"})
    agent.setTransport("websocket")
    agent.sessionId = "session-b"
    agent.thinkingBudgets = {"low": 2}
    agent.maxRetryDelayMs = 456
    agent.onPayload = lambda payload, model: payload  # noqa: ARG005

    assert agent.getSteeringMode() == "all"
    assert agent.getFollowUpMode() == "all"
    assert agent.hasQueuedMessages() is True
    assert agent.sessionId == "session-b"
    assert agent.thinkingBudgets == {"low": 2}
    assert agent.maxRetryDelayMs == 456
    assert agent.transport == "websocket"
    assert agent.onPayload is not None

    agent.clearSteeringQueue()
    assert agent.hasQueuedMessages() is True
    agent.clearFollowUpQueue()
    assert agent.hasQueuedMessages() is False
    agent.clearMessages()
    assert agent.state.messages == []
