from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent import Agent, AgentState
from ai import Model, ScriptedBackend, stream_simple
from coding_agent.core.agent_session import AgentSession, AgentSessionConfig
from coding_agent.core.auth_storage import AuthStorage
from coding_agent.core.messages import convert_to_llm
from coding_agent.core.model_registry import ModelRegistry
from coding_agent.core.resource_loader import DefaultResourceLoader, DefaultResourceLoaderOptions
from coding_agent.core.session_manager import SessionManager
from coding_agent.core.settings_manager import SettingsManager
from coding_agent.core.tools import create_coding_tools

DEFAULT_EXAMPLE_BASE_URL = "http://192.168.64.22:3001/v1"
DEFAULT_EXAMPLE_MODEL = "qwen3.5-122b-vl"
DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant.

The current Python refactor exposes Agent, coding-agent sessions, tools, and session export.
Respond clearly and use tools only when they are actually needed."""


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text"]
        return " ".join(part.strip() for part in parts if part.strip())
    return str(content).strip()


def _generate_title(messages: list[Any]) -> str:
    first_user = next((message for message in messages if getattr(message, "role", None) == "user"), None)
    if first_user is None:
        return ""
    text = _extract_text(getattr(first_user, "content", ""))
    if not text:
        return ""
    sentence_end = next((index for index, char in enumerate(text) if char in ".!?"), -1)
    if 0 < sentence_end <= 50:
        return text[: sentence_end + 1]
    return text if len(text) <= 50 else f"{text[:47]}..."


def _should_persist(messages: list[Any]) -> bool:
    has_user = any(getattr(message, "role", None) == "user" for message in messages)
    has_assistant = any(getattr(message, "role", None) == "assistant" for message in messages)
    return has_user and has_assistant


@dataclass
class WebUiExampleConfig:
    cwd: str
    session_dir: str | None = None
    agent_dir: str | None = None
    provider: str = "openai"
    api: str = "openai-completions"
    model_name: str = DEFAULT_EXAMPLE_MODEL
    base_url: str = DEFAULT_EXAMPLE_BASE_URL
    api_key: str | None = None
    thinking_level: str = "off"
    with_tools: bool = True
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    backend: Any = None
    no_extensions: bool = True
    no_skills: bool = False
    no_prompt_templates: bool = True
    additional_skill_paths: list[str] | None = None

    @classmethod
    def from_env(
        cls,
        *,
        cwd: str,
        session_dir: str | None = None,
        with_tools: bool = True,
        backend: Any = None,
    ) -> "WebUiExampleConfig":
        return cls(
            cwd=cwd,
            session_dir=session_dir,
            base_url=os.environ.get("LLM_BASE_URL", DEFAULT_EXAMPLE_BASE_URL),
            api_key=os.environ.get("LLM_API_KEY"),
            model_name=os.environ.get("LLM_MODEL", DEFAULT_EXAMPLE_MODEL),
            with_tools=with_tools,
            backend=backend,
        )


class WebUiStyleExampleApp:
    def __init__(self, config: WebUiExampleConfig, session: AgentSession) -> None:
        self.config = config
        self.session = session
        self.title = session.session_manager.get_session_name() or ""

    @classmethod
    def create(cls, config: WebUiExampleConfig) -> "WebUiStyleExampleApp":
        session_manager = SessionManager.create(config.cwd, session_dir=config.session_dir)
        return cls(config, _build_agent_session(config, session_manager))

    @classmethod
    def open(cls, config: WebUiExampleConfig, session_file: str) -> "WebUiStyleExampleApp":
        session_manager = SessionManager.open(session_file, session_dir=config.session_dir)
        return cls(config, _build_agent_session(config, session_manager))

    def send(self, prompt: str) -> str | None:
        self.session.prompt(prompt)
        if not self.title and _should_persist(self.session.state.messages):
            generated = _generate_title(self.session.state.messages) or f"Session {self.session.session_id[:8]}"
            self.title = generated
            self.session.set_session_name(generated)
        return self.session.get_last_assistant_text()

    def export_html(self, output_path: str | None = None) -> str:
        return self.session.export_to_html(output_path)

    def snapshot(self) -> dict[str, Any]:
        stats = self.session.get_session_stats()
        return {
            "sessionId": self.session.session_id,
            "sessionFile": self.session.session_file,
            "title": self.title,
            "lastAssistantText": self.session.get_last_assistant_text(),
            "stats": {
                "userMessages": stats.user_messages,
                "assistantMessages": stats.assistant_messages,
                "toolCalls": stats.tool_calls,
                "toolResults": stats.tool_results,
                "totalMessages": stats.total_messages,
                "tokens": dict(stats.tokens),
            },
        }


def _build_agent_session(config: WebUiExampleConfig, session_manager: SessionManager) -> AgentSession:
    agent_dir = config.agent_dir or str(Path(config.cwd) / ".pi" / "agent")
    settings_manager = SettingsManager(cwd=config.cwd, agent_dir=agent_dir, global_settings={}, project_settings={})
    resource_loader = DefaultResourceLoader(
        DefaultResourceLoaderOptions(
            cwd=config.cwd,
            agent_dir=agent_dir,
            settings_manager=settings_manager,
            no_extensions=config.no_extensions,
            no_skills=config.no_skills,
            no_prompt_templates=config.no_prompt_templates,
            additional_skill_paths=list(config.additional_skill_paths or []),
        )
    )
    resource_loader.reload()

    auth_storage = AuthStorage.in_memory()
    if config.api_key:
        auth_storage.set_api_key(config.provider, config.api_key)

    model = Model(
        provider=config.provider,
        id=config.model_name,
        name=config.model_name,
        api=config.api,
        base_url=config.base_url,
    )
    model_registry = ModelRegistry()
    model_registry.register_model(model)

    tools = create_coding_tools(config.cwd) if config.with_tools else []
    agent_kwargs: dict[str, Any] = {
        "initial_state": AgentState(
            system_prompt=config.system_prompt,
            model=model,
            thinking_level=config.thinking_level,  # type: ignore[arg-type]
            tools=tools,
            messages=[],
        ),
        "convert_to_llm": convert_to_llm,
        "get_api_key": auth_storage.get_api_key,
        "transport": settings_manager.get_transport(),
        "thinking_budgets": settings_manager.get_thinking_budgets(),
        "max_retry_delay_ms": settings_manager.get_retry_settings().max_delay_ms,
    }
    if config.backend is not None:
        agent_kwargs["backend"] = config.backend
    else:
        agent_kwargs["stream_fn"] = stream_simple

    agent = Agent(**agent_kwargs)
    agent.set_tools(tools)
    agent.session_id = session_manager.get_session_id()

    return AgentSession(
        AgentSessionConfig(
            agent=agent,
            session_manager=session_manager,
            cwd=config.cwd,
            settings_manager=settings_manager,
            auth_storage=auth_storage,
            model_registry=model_registry,
            resource_loader=resource_loader,
            auto_retry=False if isinstance(config.backend, ScriptedBackend) else True,
            auto_compaction=False if isinstance(config.backend, ScriptedBackend) else True,
        )
    )
