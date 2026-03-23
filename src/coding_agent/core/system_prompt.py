# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .skills import Skill, format_skills_for_prompt

_TOOL_DESCRIPTIONS = {
    "read": "Read file contents",
    "bash": "Execute bash commands (ls, rg, find, etc.)",
    "edit": "Make surgical edits to files",
    "write": "Create or overwrite files",
    "grep": "Search file contents for patterns",
    "find": "Find files by glob pattern",
    "ls": "List directory contents",
}


def build_system_prompt(
    *,
    custom_prompt: str | None = None,
    selected_tools: list[str] | None = None,
    tool_snippets: dict[str, str] | None = None,
    prompt_guidelines: list[str] | None = None,
    append_system_prompt: str | None = None,
    cwd: str | None = None,
    context_files: list[dict[str, str]] | None = None,
    skills: list[Any] | None = None,
) -> str:
    resolved_cwd = cwd or Path.cwd().as_posix()
    date_time = datetime.now().astimezone().strftime("%A, %B %d, %Y %H:%M:%S %Z")
    context_files = context_files or []
    skills = skills or []
    append_section = f"\n\n{append_system_prompt}" if append_system_prompt else ""

    if custom_prompt:
        prompt = custom_prompt
        if append_section:
            prompt += append_section
        if context_files:
            prompt += "\n\n# Project Context\n\n"
            for item in context_files:
                prompt += f"## {item['path']}\n\n{item['content']}\n\n"
        if skills and (selected_tools is None or "read" in selected_tools):
            prompt += _format_skills(skills)
        prompt += f"\nCurrent date and time: {date_time}"
        prompt += f"\nCurrent working directory: {resolved_cwd}"
        return prompt

    tools = selected_tools or ["read", "bash", "edit", "write"]
    tools_list = "\n".join(
        f"- {name}: {(tool_snippets or {}).get(name) or _TOOL_DESCRIPTIONS.get(name, name)}" for name in tools
    )
    guidelines = _build_guidelines(tools, prompt_guidelines or [])

    prompt = (
        "You are an expert coding assistant operating inside pi, a coding agent harness. "
        "You help users by reading files, executing commands, editing code, and writing new files.\n\n"
        f"Available tools:\n{tools_list or '(none)'}\n\n"
        "In addition to the tools above, you may have access to other custom tools depending on the project.\n\n"
        f"Guidelines:\n{guidelines}"
    )

    if append_section:
        prompt += append_section
    if context_files:
        prompt += "\n\n# Project Context\n\n"
        for item in context_files:
            prompt += f"## {item['path']}\n\n{item['content']}\n\n"
    if skills and "read" in tools:
        prompt += _format_skills(skills)
    prompt += f"\nCurrent date and time: {date_time}"
    prompt += f"\nCurrent working directory: {resolved_cwd}"
    return prompt


def _build_guidelines(tools: list[str], additional: list[str]) -> str:
    has_bash = "bash" in tools
    has_edit = "edit" in tools
    has_write = "write" in tools
    has_read = "read" in tools
    has_grep = "grep" in tools
    has_find = "find" in tools
    has_ls = "ls" in tools
    items: list[str] = []

    def add(text: str) -> None:
        if text not in items:
            items.append(text)

    if has_bash and not (has_grep or has_find or has_ls):
        add("Use bash for file operations like ls, rg, find")
    elif has_bash:
        add("Prefer grep/find/ls tools over bash for file exploration")
    if has_read and has_edit:
        add("Use read to examine files before editing")
    if has_edit:
        add("Use edit for precise changes")
    if has_write:
        add("Use write only for new files or complete rewrites")
    if has_edit or has_write:
        add("When summarizing your actions, output plain text directly")
    for item in additional:
        item = item.strip()
        if item:
            add(item)
    add("Be concise in your responses")
    add("Show file paths clearly when working with files")
    return "\n".join(f"- {item}" for item in items)


def _format_skills(skills: list[dict[str, Any]]) -> str:
    normalized: list[Skill] = []
    for skill in skills:
        if isinstance(skill, Skill):
            normalized.append(skill)
            continue
        if isinstance(skill, dict):
            normalized.append(
                Skill(
                    name=str(skill.get("name", "")),
                    description=str(skill.get("description", "")).strip(),
                    file_path=str(skill.get("file_path") or skill.get("path") or ""),
                    base_dir=str(skill.get("base_dir") or skill.get("baseDir") or ""),
                    source=str(skill.get("source") or skill.get("location") or ""),
                    disable_model_invocation=bool(
                        skill.get("disable_model_invocation") or skill.get("disableModelInvocation", False)
                    ),
                )
            )
    return format_skills_for_prompt(normalized)
