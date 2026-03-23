# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent import Agent, AgentState
from ai import EchoBackend, Model

from .agent_session import AgentSession, AgentSessionConfig
from .auth_storage import AuthStorage
from .compaction import CompactionSettings, RetrySettings
from .extensions import Extension, ExtensionRunner, wrap_registered_tools
from .messages import convert_to_llm
from .model_registry import ModelRegistry
from .resource_loader import DefaultResourceLoader, DefaultResourceLoaderOptions
from .session_manager import SessionManager
from .settings_manager import SettingsManager
from .tools import create_coding_tools
from .workspace import resolve_workspace_dir


@dataclass
class CreateAgentSessionOptions:
    cwd: str | None = None
    agent_dir: str | None = None
    model: Model | None = None
    tools: list[Any] | None = None
    session_manager: SessionManager | None = None
    model_registry: ModelRegistry | None = None
    settings_manager: SettingsManager | None = None
    auth_storage: AuthStorage | None = None
    resource_loader: DefaultResourceLoader | None = None
    backend: Any = None
    system_prompt: str = ""
    append_system_prompt: str | None = None
    thinking_level: str | None = None
    prompt_template_paths: list[str] | None = None
    no_prompt_templates: bool = False
    retry_settings: RetrySettings = field(default_factory=RetrySettings)
    compaction_settings: CompactionSettings = field(default_factory=CompactionSettings)
    auto_retry: bool = True
    auto_compaction: bool = True
    before_compact_hook: Any = None
    compaction_complete_fn: Any = None
    extensions: list[Extension] | None = None
    extension_runner: ExtensionRunner | None = None


def create_agent_session(options: CreateAgentSessionOptions | None = None) -> AgentSession:
    opts = options or CreateAgentSessionOptions()
    cwd = opts.cwd or Path.cwd().as_posix()
    agent_dir = opts.agent_dir or resolve_workspace_dir(cwd)

    model_registry = opts.model_registry or ModelRegistry()
    model = opts.model or model_registry.get_default_model()
    model_registry.register_model(model)

    session_manager = opts.session_manager or SessionManager.continue_recent(cwd)
    settings_manager = opts.settings_manager or SettingsManager.create(cwd, agent_dir)
    auth_storage = opts.auth_storage or AuthStorage.create(agent_dir)
    resource_loader = opts.resource_loader or DefaultResourceLoader(
        DefaultResourceLoaderOptions(
            cwd=cwd,
            agent_dir=agent_dir,
            settings_manager=settings_manager,
            additional_prompt_template_paths=opts.prompt_template_paths,
            system_prompt=opts.system_prompt or None,
            append_system_prompt=opts.append_system_prompt,
            no_prompt_templates=opts.no_prompt_templates,
        )
    )
    resource_loader.reload()
    runner = opts.extension_runner
    loaded_extensions = list(resource_loader.getExtensions().get("extensions", []))
    configured_extensions = list(opts.extensions or [])
    all_extensions = loaded_extensions + configured_extensions
    if runner is None and all_extensions:
        runner = ExtensionRunner(all_extensions, cwd, session_manager, model_registry)

    tools = create_coding_tools(cwd) if opts.tools is None else list(opts.tools)
    if runner is not None:
        tools.extend(wrap_registered_tools(runner.registered_tools, runner))

    transform_context = None
    if runner is not None:
        transform_context = lambda messages, _: runner.emit_context({"type": "context", "messages": list(messages)}).get(
            "messages", list(messages)
        )

    thinking_level = opts.thinking_level or (settings_manager.get_default_thinking_level() or "off")
    base_system_prompt = opts.system_prompt or resource_loader.getSystemPrompt() or ""

    agent = Agent(
        initial_state=AgentState(
            system_prompt=base_system_prompt,
            model=model,
            thinking_level=thinking_level,  # type: ignore[arg-type]
            tools=tools,
            messages=[],
        ),
        convert_to_llm=convert_to_llm,
        transform_context=transform_context,
        backend=opts.backend or EchoBackend(),
        get_api_key=auth_storage.get_api_key,
        steering_mode=settings_manager.get_steering_mode(),
        follow_up_mode=settings_manager.get_follow_up_mode(),
        transport=settings_manager.get_transport(),
        thinking_budgets=settings_manager.get_thinking_budgets(),
        max_retry_delay_ms=settings_manager.get_retry_settings().max_delay_ms,
    )
    agent.set_tools(tools)
    agent.session_id = session_manager.get_session_id()

    session = AgentSession(
        AgentSessionConfig(
            agent=agent,
            session_manager=session_manager,
            settings_manager=settings_manager,
            auth_storage=auth_storage,
            cwd=cwd,
            model_registry=model_registry,
            resource_loader=resource_loader,
            retry_settings=opts.retry_settings,
            compaction_settings=opts.compaction_settings,
            auto_retry=opts.auto_retry,
            auto_compaction=opts.auto_compaction,
            before_compact_hook=opts.before_compact_hook,
            compaction_complete_fn=opts.compaction_complete_fn,
            extension_runner=runner,
        )
    )
    if runner is not None:
        runner.bind_session(session)
    return session
