# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any

from .workspace import resolve_workspace_dir

CONFIG_DIR_NAME = ".pi"


@dataclass
class PromptTemplate:
    name: str
    description: str
    content: str
    source: str
    file_path: str


def parse_command_args(args_string: str) -> list[str]:
    args: list[str] = []
    current = ""
    in_quote: str | None = None

    for char in args_string:
        if in_quote is not None:
            if char == in_quote:
                in_quote = None
            else:
                current += char
            continue
        if char in {"'", '"'}:
            in_quote = char
            continue
        if char in {" ", "\t"}:
            if current:
                args.append(current)
                current = ""
            continue
        current += char

    if current:
        args.append(current)
    return args


def substitute_args(content: str, args: list[str]) -> str:
    result = content

    for index, value in enumerate(args, start=1):
        result = result.replace(f"${index}", value)

    def slice_replace(text: str) -> str:
        output = text
        import re

        pattern = re.compile(r"\$\{@:(\d+)(?::(\d+))?\}")

        def repl(match: re.Match[str]) -> str:
            start = max(int(match.group(1)) - 1, 0)
            length = match.group(2)
            if length is not None:
                return " ".join(args[start : start + int(length)])
            return " ".join(args[start:])

        output = pattern.sub(repl, output)
        return output

    result = slice_replace(result)
    all_args = " ".join(args)
    result = result.replace("$ARGUMENTS", all_args)
    result = result.replace("$@", all_args)
    return result


def load_prompt_templates(
    *,
    cwd: str | None = None,
    agent_dir: str | None = None,
    prompt_paths: list[str] | None = None,
    include_defaults: bool = True,
) -> list[PromptTemplate]:
    resolved_cwd = Path(cwd or Path.cwd())
    resolved_agent_dir = Path(agent_dir or resolve_workspace_dir(resolved_cwd.as_posix()))
    templates: list[PromptTemplate] = []

    if include_defaults:
        templates.extend(_load_templates_from_dir(resolved_agent_dir / "prompts", "user", "(user)"))
        project_prompts_dir = resolved_cwd / CONFIG_DIR_NAME / "prompts"
        if project_prompts_dir.resolve() != (resolved_agent_dir / "prompts").resolve():
            templates.extend(_load_templates_from_dir(project_prompts_dir, "project", "(project)"))

    for raw_path in prompt_paths or []:
        resolved = _resolve_path(raw_path, resolved_cwd)
        if resolved.is_dir():
            templates.extend(_load_templates_from_dir(resolved, "path", _build_path_label(resolved)))
        elif resolved.is_file() and resolved.suffix == ".md":
            template = _load_template_from_file(resolved, "path", _build_path_label(resolved))
            if template is not None:
                templates.append(template)

    return templates


def expand_prompt_template(text: str, templates: list[PromptTemplate]) -> str:
    if not text.startswith("/"):
        return text
    space_index = text.find(" ")
    template_name = text[1:] if space_index == -1 else text[1:space_index]
    args_string = "" if space_index == -1 else text[space_index + 1 :]
    template = next((item for item in templates if item.name == template_name), None)
    if template is None:
        return text
    return substitute_args(template.content, parse_command_args(args_string))


def _load_templates_from_dir(path: Path, source: str, label: str) -> list[PromptTemplate]:
    if not path.exists() or not path.is_dir():
        return []
    templates: list[PromptTemplate] = []
    for entry in sorted(path.iterdir()):
        if entry.is_file() and entry.suffix == ".md":
            template = _load_template_from_file(entry, source, label)
            if template is not None:
                templates.append(template)
    return templates


def _load_template_from_file(path: Path, source: str, label: str) -> PromptTemplate | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter, body = _parse_frontmatter(raw)
    description = str(frontmatter.get("description", "")).strip()
    if not description:
        for line in body.splitlines():
            if line.strip():
                description = line.strip()[:60]
                break
    if description:
        description = f"{description} {label}"
    else:
        description = label
    return PromptTemplate(
        name=path.stem,
        description=description,
        content=body,
        source=source,
        file_path=path.as_posix(),
    )


def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---\n", 4)
    if end == -1:
        return {}, raw
    frontmatter_raw = raw[4:end]
    body = raw[end + 5 :]
    result: dict[str, Any] = {}
    for line in frontmatter_raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result, body


def _resolve_path(raw_path: str, cwd: Path) -> Path:
    expanded = os.path.expanduser(raw_path.strip())
    path = Path(expanded)
    if path.is_absolute():
        return path
    return (cwd / path).resolve()


def _build_path_label(path: Path) -> str:
    return f"(path:{path.stem or 'path'})"
