from __future__ import annotations

from pathlib import Path
from time import time

from ai import AssistantMessage, Model, ScriptedBackend, Usage, text_block
from coding_agent.core.agent_session import (
    AgentSession,
    AgentSessionConfig,
)
from coding_agent.core.sdk import CreateAgentSessionOptions, create_agent_session
from coding_agent.core.session_manager import SessionManager
from coding_agent.core.tools import create_coding_tools
from agent import Agent, AgentState


def test_agent_session_persists_messages_to_session_entries(tmp_path: Path) -> None:
    session_manager = SessionManager.in_memory(str(tmp_path))

    def responder(model, context, options):  # noqa: ANN001
        del context, options
        return AssistantMessage(
            content=[text_block("ok")],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    agent = Agent(
        initial_state=AgentState(
            system_prompt="",
            model=Model(provider="mock", id="echo"),
            thinking_level="off",
            tools=create_coding_tools(str(tmp_path)),
            messages=[],
        ),
        backend=ScriptedBackend(responder),
    )
    session = AgentSession(
        AgentSessionConfig(
            agent=agent,
            session_manager=session_manager,
            cwd=str(tmp_path),
        )
    )

    session.prompt("hello")
    entries = session_manager.get_entries()
    message_entries = [entry for entry in entries if entry.get("type") == "message"]
    assert len(message_entries) >= 2
    assert any(entry["message"].get("role") == "assistant" for entry in message_entries)


def test_create_agent_session_restores_thinking_and_model(tmp_path: Path) -> None:
    session_manager = SessionManager.in_memory(str(tmp_path))
    session_manager.append_model_change("mock", "echo")
    session_manager.append_thinking_level_change("high")

    session = create_agent_session(
        CreateAgentSessionOptions(
            cwd=str(tmp_path),
            session_manager=session_manager,
            model=Model(provider="mock", id="echo"),
        )
    )
    assert session.model.id == "echo"
    assert session.thinking_level == "high"
