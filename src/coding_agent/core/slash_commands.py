# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass

from .prompt_templates import PromptTemplate
from .skills import Skill


@dataclass(frozen=True)
class SlashCommandInfo:
    name: str
    source: str
    description: str | None = None
    location: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class BuiltinSlashCommand:
    name: str
    description: str


BUILTIN_SLASH_COMMANDS: tuple[BuiltinSlashCommand, ...] = (
    BuiltinSlashCommand("settings", "Open settings menu"),
    BuiltinSlashCommand("model", "Select model (opens selector UI)"),
    BuiltinSlashCommand("scoped-models", "Enable/disable models for Ctrl+P cycling"),
    BuiltinSlashCommand("export", "Export session to HTML file"),
    BuiltinSlashCommand("share", "Share session as a secret GitHub gist"),
    BuiltinSlashCommand("copy", "Copy last agent message to clipboard"),
    BuiltinSlashCommand("name", "Set session display name"),
    BuiltinSlashCommand("session", "Show session info and stats"),
    BuiltinSlashCommand("changelog", "Show changelog entries"),
    BuiltinSlashCommand("hotkeys", "Show all keyboard shortcuts"),
    BuiltinSlashCommand("fork", "Create a new fork from a previous message"),
    BuiltinSlashCommand("tree", "Navigate session tree (switch branches)"),
    BuiltinSlashCommand("login", "Login with OAuth provider"),
    BuiltinSlashCommand("logout", "Logout from OAuth provider"),
    BuiltinSlashCommand("new", "Start a new session"),
    BuiltinSlashCommand("compact", "Manually compact the session context"),
    BuiltinSlashCommand("resume", "Resume a different session"),
    BuiltinSlashCommand("reload", "Reload extensions, skills, prompts, and themes"),
    BuiltinSlashCommand("quit", "Quit pi"),
)


def build_slash_commands(
    *,
    prompts: list[PromptTemplate] | None = None,
    skills: list[dict] | list[Skill] | None = None,
    extension_commands: list[dict] | None = None,
) -> list[SlashCommandInfo]:
    commands: list[SlashCommandInfo] = [
        SlashCommandInfo(name=item.name, source="builtin", description=item.description) for item in BUILTIN_SLASH_COMMANDS
    ]
    reserved = {item.name for item in BUILTIN_SLASH_COMMANDS}

    for template in prompts or []:
        if template.name in reserved:
            continue
        commands.append(
            SlashCommandInfo(
                name=template.name,
                source="prompt",
                description=template.description,
                location=template.source,
                path=template.file_path,
            )
        )

    for skill in skills or []:
        name = _get_field(skill, "name")
        if not name or name in reserved:
            continue
        commands.append(
            SlashCommandInfo(
                name=f"skill:{name}",
                source="skill",
                description=_get_field(skill, "description") or None,
                location=_get_field(skill, "location") or _get_field(skill, "source") or None,
                path=_get_field(skill, "path") or _get_field(skill, "file_path") or None,
            )
        )

    for command in extension_commands or []:
        name = _get_field(command, "name")
        if not name or name in reserved:
            continue
        commands.append(
            SlashCommandInfo(
                name=name,
                source="extension",
                description=_get_field(command, "description") or None,
                location=_get_field(command, "location") or None,
                path=_get_field(command, "path") or None,
            )
        )

    return commands


def _get_field(value: object, name: str) -> str:
    if isinstance(value, dict):
        resolved = value.get(name)
        if resolved is None and name == "path":
            resolved = value.get("file_path")
        return str(resolved or "")
    return str(getattr(value, name, "") or "")
