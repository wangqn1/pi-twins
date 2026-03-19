from __future__ import annotations

from time import time

from agent import Agent, AgentState
from ai import AssistantMessage, Model, ScriptedBackend, Usage, text_block
from coding_agent.core.agent_session import AgentSession, AgentSessionConfig
from coding_agent.core.compaction import CompactionSettings, RetrySettings
from coding_agent.core.session_manager import SessionManager


def _assistant_text(message: object) -> str:
    if isinstance(message, dict):
        blocks = message.get("content", [])
    else:
        blocks = getattr(message, "content", [])
    if isinstance(blocks, list):
        texts = [str(block.get("text", "")) for block in blocks if isinstance(block, dict) and block.get("type") == "text"]
        return "\n".join(texts)
    return ""


def _assistant_stop_reason(message: object) -> str | None:
    if isinstance(message, dict):
        return message.get("stopReason") or message.get("stop_reason")
    return getattr(message, "stop_reason", None)


def _make_session(
    *,
    backend: ScriptedBackend,
    session_manager: SessionManager,
    model: Model | None = None,
    retry_settings: RetrySettings | None = None,
    compaction_settings: CompactionSettings | None = None,
    auto_retry: bool = True,
    auto_compaction: bool = True,
) -> AgentSession:
    m = model or Model(provider="mock", id="echo")
    agent = Agent(
        initial_state=AgentState(
            system_prompt="",
            model=m,
            thinking_level="off",
            tools=[],
            messages=[],
        ),
        backend=backend,
    )
    return AgentSession(
        AgentSessionConfig(
            agent=agent,
            session_manager=session_manager,
            cwd="/tmp/project",
            retry_settings=retry_settings or RetrySettings(),
            compaction_settings=compaction_settings or CompactionSettings(),
            auto_retry=auto_retry,
            auto_compaction=auto_compaction,
        )
    )


def test_agent_session_auto_retry_success() -> None:
    calls = {"count": 0}
    events: list[dict[str, object]] = []

    def responder(model, context, options):  # noqa: ANN001
        del context, options
        calls["count"] += 1
        if calls["count"] == 1:
            return AssistantMessage(
                content=[text_block("rate limited")],
                api=model.api,
                provider=model.provider,
                model=model.id,
                usage=Usage(),
                stop_reason="error",
                error_message="429 Too Many Requests",
                timestamp=int(time() * 1000),
            )
        return AssistantMessage(
            content=[text_block("retry success")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    session = _make_session(
        backend=ScriptedBackend(responder),
        session_manager=SessionManager.in_memory("/tmp/project"),
        retry_settings=RetrySettings(enabled=True, max_retries=2, base_delay_ms=0, max_delay_ms=0),
        auto_compaction=False,
    )
    session.subscribe(lambda event: events.append(event))
    session.prompt("hello")

    assistants = [message for message in session.state.messages if getattr(message, "role", None) == "assistant"]
    assert assistants
    assert _assistant_stop_reason(assistants[-1]) == "stop"
    assert "retry success" in _assistant_text(assistants[-1])
    assert any(event.get("type") == "auto_retry_start" for event in events)
    assert any(event.get("type") == "auto_retry_end" and event.get("success") is True for event in events)
    assert session.retry_attempt == 0


def test_agent_session_auto_retry_max_retries_exceeded() -> None:
    events: list[dict[str, object]] = []

    def responder(model, context, options):  # noqa: ANN001
        del context, options
        return AssistantMessage(
            content=[text_block("still failing")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="error",
            error_message="500 server error",
            timestamp=int(time() * 1000),
        )

    session = _make_session(
        backend=ScriptedBackend(responder),
        session_manager=SessionManager.in_memory("/tmp/project"),
        retry_settings=RetrySettings(enabled=True, max_retries=1, base_delay_ms=0, max_delay_ms=0),
        auto_compaction=False,
    )
    session.subscribe(lambda event: events.append(event))
    session.prompt("hello")

    assistants = [message for message in session.state.messages if getattr(message, "role", None) == "assistant"]
    assert assistants
    assert _assistant_stop_reason(assistants[-1]) == "error"
    assert any(event.get("type") == "auto_retry_end" and event.get("success") is False for event in events)
    assert session.retry_attempt == 0


def test_agent_session_manual_compact_appends_compaction_entry() -> None:
    manager = SessionManager.in_memory("/tmp/project")
    manager.append_message({"role": "user", "content": "task A", "timestamp": 1})
    manager.append_message(
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "did A"}],
            "api": "mock",
            "provider": "mock",
            "model": "echo",
            "usage": {"input": 10, "output": 5, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 15, "cost": {"total": 0}},
            "stopReason": "stop",
            "timestamp": 2,
        }
    )
    manager.append_message({"role": "user", "content": "task B", "timestamp": 3})

    def responder(model, context, options):  # noqa: ANN001
        del model, context, options
        return AssistantMessage(
            content=[text_block("ok")],
            api="mock",
            provider="mock",
            model="echo",
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    session = _make_session(
        backend=ScriptedBackend(responder),
        session_manager=manager,
        compaction_settings=CompactionSettings(enabled=True, reserve_tokens=10, keep_recent_tokens=1),
        auto_retry=False,
        auto_compaction=False,
    )
    result = session.compact()
    assert "## Goal" in result["summary"]
    assert manager.get_entries()[-1]["type"] == "compaction"
    context = manager.build_session_context()
    first = context.messages[0]
    assert getattr(first, "role", None) == "compactionSummary"


def test_agent_session_auto_compaction_threshold() -> None:
    events: list[dict[str, object]] = []

    def responder(model, context, options):  # noqa: ANN001
        del context, options
        return AssistantMessage(
            content=[text_block("large context response")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(input=150, output=20, cache_read=0, cache_write=0, total_tokens=170),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    session = _make_session(
        backend=ScriptedBackend(responder),
        session_manager=SessionManager.in_memory("/tmp/project"),
        model=Model(provider="mock", id="echo", context_window=100, max_tokens=64),
        compaction_settings=CompactionSettings(enabled=True, reserve_tokens=10, keep_recent_tokens=1),
        auto_retry=False,
        auto_compaction=True,
    )
    session.subscribe(lambda event: events.append(event))
    session.prompt("trigger compaction")

    assert any(event.get("type") == "auto_compaction_start" for event in events)
    assert any(entry.get("type") == "compaction" for entry in session.session_manager.get_entries())


def test_agent_session_manual_compact_supports_hook_override() -> None:
    manager = SessionManager.in_memory("/tmp/project")
    manager.append_message({"role": "user", "content": "task A", "timestamp": 1})
    manager.append_message(_assistant_text_message("did A", 2))
    manager.append_message({"role": "user", "content": "task B", "timestamp": 3})

    def responder(model, context, options):  # noqa: ANN001
        del model, context, options
        return AssistantMessage(
            content=[text_block("ok")],
            api="mock",
            provider="mock",
            model="echo",
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    def hook(preparation):  # noqa: ANN001
        return {
            "summary": "hook summary",
            "firstKeptEntryId": preparation["firstKeptEntryId"],
            "tokensBefore": preparation["tokensBefore"],
            "details": {"source": "hook"},
        }

    session = _make_session(
        backend=ScriptedBackend(responder),
        session_manager=manager,
        compaction_settings=CompactionSettings(enabled=True, reserve_tokens=10, keep_recent_tokens=1),
        auto_retry=False,
        auto_compaction=False,
    )
    session.before_compact_hook = hook
    result = session.compact()
    assert result["summary"] == "hook summary"
    assert manager.get_entries()[-1]["type"] == "compaction"
    assert manager.get_entries()[-1].get("fromHook") is True
    assert manager.get_entries()[-1].get("details") == {"source": "hook"}


def test_agent_session_error_context_compaction_skips_stale_pre_compaction_usage() -> None:
    events: list[dict[str, object]] = []
    manager = SessionManager.in_memory("/tmp/project")
    u = manager.append_message({"role": "user", "content": "old task", "timestamp": 1})
    a = manager.append_message(_assistant_text_message("old response", 2, input_tokens=200, output_tokens=20))
    assert u and a
    manager.append_compaction("old summary", first_kept_entry_id=a, tokens_before=220)

    def responder(model, context, options):  # noqa: ANN001
        del context, options
        return AssistantMessage(
            content=[text_block("provider temporary error")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="error",
            error_message="some error",
            timestamp=int(time() * 1000),
        )

    session = _make_session(
        backend=ScriptedBackend(responder),
        session_manager=manager,
        model=Model(provider="mock", id="echo", context_window=100, max_tokens=64),
        compaction_settings=CompactionSettings(enabled=True, reserve_tokens=10, keep_recent_tokens=1),
        auto_retry=False,
        auto_compaction=True,
    )
    session.subscribe(lambda event: events.append(event))
    existing_compactions = [entry for entry in manager.get_entries() if entry.get("type") == "compaction"]
    assert len(existing_compactions) == 1

    session.prompt("new turn")

    compactions_after = [entry for entry in manager.get_entries() if entry.get("type") == "compaction"]
    assert len(compactions_after) == 1
    assert not any(event.get("type") == "auto_compaction_start" for event in events)


def _assistant_text_message(text: str, timestamp: int, input_tokens: int = 10, output_tokens: int = 5) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "api": "mock",
        "provider": "mock",
        "model": "echo",
        "usage": {
            "input": input_tokens,
            "output": output_tokens,
            "cacheRead": 0,
            "cacheWrite": 0,
            "totalTokens": input_tokens + output_tokens,
            "cost": {"total": 0},
        },
        "stopReason": "stop",
        "timestamp": timestamp,
    }
