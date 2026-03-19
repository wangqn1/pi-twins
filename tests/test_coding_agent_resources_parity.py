from __future__ import annotations

import json
from time import time

from ai import AssistantMessage, Model, ScriptedBackend, Usage, text_block
from coding_agent.core.auth_storage import AuthStorage
from coding_agent.core.package_manager import DefaultPackageManager
from coding_agent.core.prompt_templates import (
    expand_prompt_template,
    load_prompt_templates,
    parse_command_args,
    substitute_args,
)
from coding_agent.core.resource_loader import DefaultResourceLoader, DefaultResourceLoaderOptions
from coding_agent.core.sdk import CreateAgentSessionOptions, create_agent_session
from coding_agent.core.session_manager import SessionManager
from coding_agent.core.settings_manager import SettingsManager, deep_merge_settings
from coding_agent.core.skills import format_skills_for_prompt
from coding_agent.core.slash_commands import build_slash_commands


def test_deep_merge_settings_and_migrations() -> None:
    merged = deep_merge_settings(
        {"retry": {"enabled": True, "maxRetries": 3}, "theme": "light"},
        {"retry": {"maxRetries": 5}, "theme": "dark"},
    )
    assert merged == {"retry": {"enabled": True, "maxRetries": 5}, "theme": "dark"}


def test_settings_manager_loads_file_settings_and_migrates(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    project_dir = tmp_path / "project"
    agent_dir.mkdir(parents=True)
    (project_dir / ".pi").mkdir(parents=True)
    (agent_dir / "settings.json").write_text(json.dumps({"queueMode": "all", "websockets": True}), encoding="utf-8")
    (project_dir / ".pi" / "settings.json").write_text(
        json.dumps({"defaultThinkingLevel": "high", "retry": {"maxDelayMs": 1234}}),
        encoding="utf-8",
    )

    manager = SettingsManager.create(project_dir.as_posix(), agent_dir.as_posix())

    assert manager.get_steering_mode() == "all"
    assert manager.get_transport() == "websocket"
    assert manager.get_default_thinking_level() == "high"
    assert manager.get_retry_settings().max_delay_ms == 1234


def test_prompt_template_loading_and_expansion(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    prompts_dir = agent_dir / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "explain.md").write_text(
        "---\ndescription: Explain something\n---\nExplain $1 and $ARGUMENTS",
        encoding="utf-8",
    )

    templates = load_prompt_templates(agent_dir=agent_dir.as_posix())
    assert templates[0].name == "explain"
    assert parse_command_args('foo "bar baz"') == ["foo", "bar baz"]
    assert substitute_args("A $1 B $@", ["x", "y"]) == "A x B x y"
    assert expand_prompt_template('/explain test "more words"', templates) == "Explain test and test more words"


def test_resource_loader_loads_context_files_and_prompts(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    cwd = tmp_path / "workspace" / "project"
    (agent_dir / "prompts").mkdir(parents=True)
    (cwd / ".pi" / "prompts").mkdir(parents=True)
    (agent_dir / "AGENTS.md").write_text("global rules", encoding="utf-8")
    (tmp_path / "workspace" / "AGENTS.md").write_text("workspace rules", encoding="utf-8")
    (cwd / ".pi" / "prompts" / "summarize.md").write_text("Summarize $1", encoding="utf-8")

    loader = DefaultResourceLoader(
        DefaultResourceLoaderOptions(
            cwd=cwd.as_posix(),
            agent_dir=agent_dir.as_posix(),
            settings_manager=SettingsManager.in_memory(),
        )
    )
    loader.reload()

    agents_files = loader.getAgentsFiles()["agentsFiles"]
    prompts = loader.getPrompts()["prompts"]

    assert [item["content"] for item in agents_files] == ["global rules", "workspace rules"]
    assert prompts[0].name == "summarize"
    commands = build_slash_commands(prompts=prompts)
    assert any(command.name == "summarize" and command.source == "prompt" for command in commands)


def test_resource_loader_loads_skills_and_extensions_from_disk(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    cwd = tmp_path / "workspace"
    (agent_dir / "extensions").mkdir(parents=True)
    (agent_dir / "skills" / "refactor").mkdir(parents=True)
    (agent_dir / "extensions" / "disk_extension.py").write_text(
        "\n".join(
            [
                "from coding_agent.core.extensions import build_extension",
                "",
                "def create_extension():",
                "    def factory(api):",
                '        api.register_command("disk-cmd", "Command from disk extension")',
                "    return build_extension('disk-ext', factory)",
            ]
        ),
        encoding="utf-8",
    )
    (agent_dir / "skills" / "refactor" / "SKILL.md").write_text(
        "---\ndescription: Refactor large modules safely\ndisable-model-invocation: true\n---\nUse this skill.\n",
        encoding="utf-8",
    )

    loader = DefaultResourceLoader(
        DefaultResourceLoaderOptions(
            cwd=cwd.as_posix(),
            agent_dir=agent_dir.as_posix(),
            settings_manager=SettingsManager.in_memory(),
        )
    )
    loader.reload()

    skills = loader.getSkills()["skills"]
    extensions = loader.getExtensions()["extensions"]
    assert [skill.name for skill in skills] == ["refactor"]
    assert "disable-model-invocation" not in format_skills_for_prompt(skills)
    assert [extension.name for extension in extensions] == ["disk-ext"]
    assert extensions[0].registered_commands[0].name == "disk-cmd"

    commands = build_slash_commands(skills=skills, extension_commands=extensions[0].registered_commands)
    assert any(command.name == "skill:refactor" and command.source == "skill" for command in commands)
    assert any(command.name == "disk-cmd" and command.source == "extension" for command in commands)


def test_create_agent_session_uses_settings_resource_loader_and_prompt_templates(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    cwd = tmp_path / "project"
    (agent_dir / "prompts").mkdir(parents=True)
    (cwd / ".pi").mkdir(parents=True)
    (agent_dir / "AGENTS.md").write_text("team instruction", encoding="utf-8")
    (agent_dir / "prompts" / "explain.md").write_text("Explain $1", encoding="utf-8")

    settings_manager = SettingsManager.in_memory(
        project_settings={
            "defaultThinkingLevel": "high",
            "steeringMode": "all",
            "followUpMode": "all",
            "transport": "websocket",
            "thinkingBudgets": {"high": 2048},
            "retry": {"maxDelayMs": 321},
        }
    )
    resource_loader = DefaultResourceLoader(
        DefaultResourceLoaderOptions(
            cwd=cwd.as_posix(),
            agent_dir=agent_dir.as_posix(),
            settings_manager=settings_manager,
        )
    )
    resource_loader.reload()

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

    session = create_agent_session(
        CreateAgentSessionOptions(
            cwd=cwd.as_posix(),
            agent_dir=agent_dir.as_posix(),
            model=Model(provider="mock", id="echo", api="mock"),
            backend=ScriptedBackend(responder),
            session_manager=SessionManager.in_memory(cwd.as_posix()),
            settings_manager=settings_manager,
            resource_loader=resource_loader,
        )
    )
    session.prompt("/explain parity")

    assert "team instruction" in str(captured["system_prompt"])
    messages = captured["messages"]
    assert messages is not None
    last = messages[-1]
    content = getattr(last, "content", "")
    assert isinstance(content, list)
    assert content[0]["text"] == "Explain parity"
    assert session.thinking_level == "high"
    assert session.agent.getSteeringMode() == "all"
    assert session.agent.getFollowUpMode() == "all"
    assert session.agent.transport == "websocket"
    assert session.agent.thinkingBudgets == {"high": 2048}
    assert session.agent.maxRetryDelayMs == 321


def test_create_agent_session_wires_auth_storage_into_agent(tmp_path) -> None:  # noqa: ANN001
    cwd = tmp_path / "project"
    auth_storage = AuthStorage.in_memory({"mock": {"type": "api_key", "key": "sk-from-auth"}})

    session = create_agent_session(
        CreateAgentSessionOptions(
            cwd=cwd.as_posix(),
            model=Model(provider="mock", id="echo", api="mock"),
            session_manager=SessionManager.in_memory(cwd.as_posix()),
            auth_storage=auth_storage,
        )
    )

    assert session.auth_storage.get_api_key("mock") == "sk-from-auth"
    assert session.agent.getApiKey is not None
    assert session.agent.getApiKey("mock") == "sk-from-auth"


def test_resource_loader_loads_package_managed_resources(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    cwd = tmp_path / "workspace"
    package_dir = tmp_path / "local-package"
    (package_dir / "skills" / "pkg-skill").mkdir(parents=True)
    (package_dir / "prompts").mkdir(parents=True)
    (package_dir / "extensions").mkdir(parents=True)
    (package_dir / "skills" / "pkg-skill" / "SKILL.md").write_text(
        "---\ndescription: Skill from package\n---\nUse package skill.\n",
        encoding="utf-8",
    )
    (package_dir / "prompts" / "pkgprompt.md").write_text("Prompt from package", encoding="utf-8")
    (package_dir / "extensions" / "pkgext.py").write_text(
        "\n".join(
            [
                "from coding_agent.core.extensions import build_extension",
                "",
                "def create_extension():",
                "    def factory(api):",
                '        api.register_command("pkg-ext", "extension from package")',
                "    return build_extension('pkg-ext', factory)",
            ]
        ),
        encoding="utf-8",
    )

    settings_manager = SettingsManager.create(cwd.as_posix(), agent_dir.as_posix())
    package_manager = DefaultPackageManager(cwd=cwd.as_posix(), agent_dir=agent_dir.as_posix(), settings_manager=settings_manager)
    package_manager.add_source_to_settings(package_dir.as_posix(), {"local": True})
    settings_manager.reload()

    loader = DefaultResourceLoader(
        DefaultResourceLoaderOptions(
            cwd=cwd.as_posix(),
            agent_dir=agent_dir.as_posix(),
            settings_manager=settings_manager,
        )
    )
    loader.reload()

    assert [skill.name for skill in loader.getSkills()["skills"]] == ["pkg-skill"]
    assert [prompt.name for prompt in loader.getPrompts()["prompts"]] == ["pkgprompt"]
    assert [extension.name for extension in loader.getExtensions()["extensions"]] == ["pkg-ext"]
    themes = loader.getThemes()["themes"]
    assert themes == []


def test_create_agent_session_auto_loads_extensions_from_resource_loader(tmp_path) -> None:  # noqa: ANN001
    agent_dir = tmp_path / "agent"
    cwd = tmp_path / "project"
    (agent_dir / "extensions").mkdir(parents=True)
    (agent_dir / "extensions" / "prelude.py").write_text(
        "\n".join(
            [
                "from coding_agent.core.extensions import build_extension",
                "",
                "def create_extension():",
                "    def factory(api):",
                "        api.on(",
                "            'before_agent_start',",
                "            lambda event, ctx: {",
                "                'message': {",
                "                    'customType': 'note',",
                "                    'content': 'from disk extension',",
                "                    'display': False,",
                "                }",
                "            },",
                "        )",
                "    return build_extension('prelude', factory)",
            ]
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def responder(model, context, options):  # noqa: ANN001
        del model, options
        captured["messages"] = context.messages
        return AssistantMessage(
            content=[text_block("ok")],
            api="mock",
            provider="mock",
            model="echo",
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    session = create_agent_session(
        CreateAgentSessionOptions(
            cwd=cwd.as_posix(),
            agent_dir=agent_dir.as_posix(),
            model=Model(provider="mock", id="echo", api="mock"),
            backend=ScriptedBackend(responder),
            session_manager=SessionManager.in_memory(cwd.as_posix()),
        )
    )
    session.prompt("hello")

    messages = captured["messages"]
    assert isinstance(messages, list)
    assert any(
        any(block.get("type") == "text" and block.get("text") == "from disk extension" for block in getattr(message, "content", []))
        for message in messages
    )
