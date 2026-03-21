from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from .workspace import resolve_workspace_dir

CONFIG_DIR_NAME = ".pi"
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    file_path: str
    base_dir: str
    source: str
    disable_model_invocation: bool = False


def load_skills(
    *,
    cwd: str | None = None,
    agent_dir: str | None = None,
    skill_paths: list[str] | None = None,
    include_defaults: bool = True,
) -> dict[str, Any]:
    resolved_cwd = Path(cwd or Path.cwd()).resolve()
    resolved_agent_dir = Path(agent_dir or resolve_workspace_dir(resolved_cwd.as_posix())).resolve()
    skills_by_name: dict[str, Skill] = {}
    real_paths: set[str] = set()
    diagnostics: list[dict[str, Any]] = []

    def add_result(result: dict[str, Any]) -> None:
        diagnostics.extend(result["diagnostics"])
        for skill in result["skills"]:
            try:
                real_path = str(Path(skill.file_path).resolve())
            except OSError:
                real_path = skill.file_path
            if real_path in real_paths:
                continue
            if skill.name in skills_by_name:
                diagnostics.append(
                    {
                        "type": "collision",
                        "message": f'name "{skill.name}" collision',
                        "path": skill.file_path,
                        "collision": {
                            "resourceType": "skill",
                            "name": skill.name,
                            "winnerPath": skills_by_name[skill.name].file_path,
                            "loserPath": skill.file_path,
                        },
                    }
                )
                continue
            skills_by_name[skill.name] = skill
            real_paths.add(real_path)

    if include_defaults:
        add_result(_load_skills_from_dir(resolved_agent_dir / "skills", "user", include_root_files=True))
        add_result(_load_skills_from_dir(resolved_cwd / CONFIG_DIR_NAME / "skills", "project", include_root_files=True))

    for raw_path in skill_paths or []:
        path = _resolve_path(raw_path, resolved_cwd)
        if not path.exists():
            diagnostics.append({"type": "warning", "message": "skill path does not exist", "path": path.as_posix()})
            continue
        if path.is_dir():
            add_result(_load_skills_from_dir(path, "path", include_root_files=True))
            continue
        if path.is_file() and path.suffix == ".md":
            loaded, loaded_diagnostics = _load_skill_from_file(path, "path")
            if loaded is not None:
                add_result({"skills": [loaded], "diagnostics": loaded_diagnostics})
            else:
                diagnostics.extend(loaded_diagnostics)
            continue
        diagnostics.append({"type": "warning", "message": "skill path is not a markdown file", "path": path.as_posix()})

    return {"skills": list(skills_by_name.values()), "diagnostics": diagnostics}


def format_skills_for_prompt(skills: list[Skill]) -> str:
    visible_skills = [skill for skill in skills if not skill.disable_model_invocation]
    if not visible_skills:
        return ""

    lines = [
        "",
        "",
        "The following skills provide specialized instructions for specific tasks.",
        "Use the read tool to load a skill's file when the task matches its description.",
        "When a skill file references a relative path, resolve it against the skill directory.",
        "",
        "<available_skills>",
    ]
    for skill in visible_skills:
        lines.extend(
            [
                "  <skill>",
                f"    <name>{_escape_xml(skill.name)}</name>",
                f"    <description>{_escape_xml(skill.description)}</description>",
                f"    <location>{_escape_xml(skill.file_path)}</location>",
                "  </skill>",
            ]
        )
    lines.append("</available_skills>")
    return "\n".join(lines)


def _load_skills_from_dir(path: Path, source: str, include_root_files: bool) -> dict[str, Any]:
    skills: list[Skill] = []
    diagnostics: list[dict[str, Any]] = []
    if not path.exists() or not path.is_dir():
        return {"skills": skills, "diagnostics": diagnostics}

    try:
        entries = sorted(path.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        return {"skills": [], "diagnostics": [{"type": "warning", "message": str(exc), "path": path.as_posix()}]}

    for entry in entries:
        if entry.name.startswith(".") or entry.name == "node_modules":
            continue
        if entry.is_dir():
            nested = _load_skills_from_dir(entry, source, include_root_files=False)
            skills.extend(nested["skills"])
            diagnostics.extend(nested["diagnostics"])
            continue
        if not entry.is_file():
            continue
        is_root_markdown = include_root_files and entry.suffix == ".md"
        is_skill_markdown = not include_root_files and entry.name == "SKILL.md"
        if not is_root_markdown and not is_skill_markdown:
            continue
        loaded, loaded_diagnostics = _load_skill_from_file(entry, source)
        diagnostics.extend(loaded_diagnostics)
        if loaded is not None:
            skills.append(loaded)

    return {"skills": skills, "diagnostics": diagnostics}


def _load_skill_from_file(path: Path, source: str) -> tuple[Skill | None, list[dict[str, Any]]]:
    diagnostics: list[dict[str, Any]] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [{"type": "warning", "message": str(exc), "path": path.as_posix()}]

    frontmatter, _body = _parse_frontmatter(raw)
    parent_dir_name = path.parent.name
    name = str(frontmatter.get("name") or parent_dir_name)
    description = str(frontmatter.get("description") or "").strip()
    disable_model_invocation = bool(frontmatter.get("disable-model-invocation") is True)

    diagnostics.extend(_validate_name(name, parent_dir_name, path))
    diagnostics.extend(_validate_description(description, path))
    if not description:
        return None, diagnostics

    return (
        Skill(
            name=name,
            description=description,
            file_path=path.as_posix(),
            base_dir=path.parent.as_posix(),
            source=source,
            disable_model_invocation=disable_model_invocation,
        ),
        diagnostics,
    )


def _validate_name(name: str, parent_dir_name: str, path: Path) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    if name != parent_dir_name:
        diagnostics.append({"type": "warning", "message": f'name "{name}" does not match parent directory "{parent_dir_name}"', "path": path.as_posix()})
    if len(name) > MAX_NAME_LENGTH:
        diagnostics.append({"type": "warning", "message": f"name exceeds {MAX_NAME_LENGTH} characters ({len(name)})", "path": path.as_posix()})
    if not name or any(ch for ch in name if ch not in "abcdefghijklmnopqrstuvwxyz0123456789-"):
        diagnostics.append({"type": "warning", "message": "name contains invalid characters (must be lowercase a-z, 0-9, hyphens only)", "path": path.as_posix()})
    if name.startswith("-") or name.endswith("-"):
        diagnostics.append({"type": "warning", "message": "name must not start or end with a hyphen", "path": path.as_posix()})
    if "--" in name:
        diagnostics.append({"type": "warning", "message": "name must not contain consecutive hyphens", "path": path.as_posix()})
    return diagnostics


def _validate_description(description: str, path: Path) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    if not description:
        diagnostics.append({"type": "warning", "message": "description is required", "path": path.as_posix()})
    elif len(description) > MAX_DESCRIPTION_LENGTH:
        diagnostics.append(
            {"type": "warning", "message": f"description exceeds {MAX_DESCRIPTION_LENGTH} characters ({len(description)})", "path": path.as_posix()}
        )
    return diagnostics


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
        parsed = value.strip()
        lower = parsed.lower()
        if lower == "true":
            result[key.strip()] = True
        elif lower == "false":
            result[key.strip()] = False
        else:
            result[key.strip()] = parsed
    return result, body


def _resolve_path(raw_path: str, cwd: Path) -> Path:
    expanded = os.path.expanduser(raw_path.strip())
    path = Path(expanded)
    if path.is_absolute():
        return path
    return (cwd / path).resolve()


def _escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
