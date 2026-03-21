from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any

from .extensions.loader import load_extensions
from .package_manager import DefaultPackageManager
from .prompt_templates import PromptTemplate, load_prompt_templates
from .settings_manager import SettingsManager
from .skills import Skill, load_skills
from .workspace import resolve_workspace_dir

CONFIG_DIR_NAME = ".pi"


@dataclass
class LoadExtensionsResult:
    extensions: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    runtime: Any = None


@dataclass
class DefaultResourceLoaderOptions:
    cwd: str | None = None
    agent_dir: str | None = None
    settings_manager: SettingsManager | None = None
    additional_extension_paths: list[str] | None = None
    additional_skill_paths: list[str] | None = None
    additional_prompt_template_paths: list[str] | None = None
    system_prompt: str | None = None
    append_system_prompt: str | None = None
    no_extensions: bool = False
    no_skills: bool = False
    no_prompt_templates: bool = False


class DefaultResourceLoader:
    def __init__(self, options: DefaultResourceLoaderOptions | None = None) -> None:
        opts = options or DefaultResourceLoaderOptions()
        self.cwd = opts.cwd or Path.cwd().as_posix()
        self.agent_dir = opts.agent_dir or resolve_workspace_dir(self.cwd)
        self.settings_manager = opts.settings_manager or SettingsManager.create(self.cwd, self.agent_dir)
        self.additional_extension_paths = list(opts.additional_extension_paths or [])
        self.additional_skill_paths = list(opts.additional_skill_paths or [])
        self.additional_prompt_template_paths = list(opts.additional_prompt_template_paths or [])
        self.system_prompt_source = opts.system_prompt
        self.append_system_prompt_source = opts.append_system_prompt
        self.no_extensions = bool(opts.no_extensions)
        self.no_skills = bool(opts.no_skills)
        self.no_prompt_templates = bool(opts.no_prompt_templates)

        self._extensions = LoadExtensionsResult()
        self._skills: list[Skill] = []
        self._skill_diagnostics: list[dict[str, Any]] = []
        self._prompts: list[PromptTemplate] = []
        self._themes: list[dict[str, Any]] = []
        self._agents_files: list[dict[str, str]] = []
        self._system_prompt: str | None = None
        self._append_system_prompt: list[str] = []
        self._path_metadata: dict[str, dict[str, str]] = {}

    def reload(self) -> None:
        package_manager = DefaultPackageManager(cwd=self.cwd, agent_dir=self.agent_dir, settings_manager=self.settings_manager)
        resolved_packages = package_manager.resolve()
        package_extension_paths = [item.path for item in resolved_packages.extensions if item.enabled]
        package_skill_paths = [item.path for item in resolved_packages.skills if item.enabled]
        package_prompt_paths = [item.path for item in resolved_packages.prompts if item.enabled]
        package_theme_paths = [item.path for item in resolved_packages.themes if item.enabled]

        extension_paths = self.settings_manager.get_extension_paths() + package_extension_paths + self.additional_extension_paths
        self._extensions = load_extensions(
            cwd=self.cwd,
            agent_dir=self.agent_dir,
            extension_paths=extension_paths,
            include_defaults=not self.no_extensions,
        )
        skill_paths = self.settings_manager.get_skill_paths() + package_skill_paths + self.additional_skill_paths
        skills_result = load_skills(
            cwd=self.cwd,
            agent_dir=self.agent_dir,
            skill_paths=skill_paths,
            include_defaults=not self.no_skills,
        )
        self._skills = list(skills_result["skills"])
        self._skill_diagnostics = list(skills_result["diagnostics"])
        prompt_paths = self.settings_manager.get_prompt_paths() + package_prompt_paths + self.additional_prompt_template_paths
        self._prompts = [] if self.no_prompt_templates else load_prompt_templates(
            cwd=self.cwd,
            agent_dir=self.agent_dir,
            prompt_paths=prompt_paths,
            include_defaults=True,
        )
        self._agents_files = _load_project_context_files(self.cwd, self.agent_dir)
        self._system_prompt = _resolve_prompt_input(self.system_prompt_source)
        append_values = [_resolve_prompt_input(self.append_system_prompt_source)] if self.append_system_prompt_source else []
        self._append_system_prompt = [item for item in append_values if item]
        self._path_metadata = {prompt.file_path: {"source": prompt.source} for prompt in self._prompts}
        for skill in self._skills:
            self._path_metadata[skill.file_path] = {"source": skill.source}
        for extension in self._extensions["extensions"]:
            if getattr(extension, "path", None):
                self._path_metadata[str(extension.path)] = {"source": "extension"}
        self._themes = [
            {
                "path": item.path,
                "enabled": item.enabled,
                "metadata": {
                    "source": item.metadata.source,
                    "scope": item.metadata.scope,
                    "origin": item.metadata.origin,
                    "baseDir": item.metadata.base_dir,
                },
            }
            for item in resolved_packages.themes
        ]
        for item in resolved_packages.extensions + resolved_packages.skills + resolved_packages.prompts + resolved_packages.themes:
            self._path_metadata[item.path] = {
                "source": item.metadata.source,
                "scope": item.metadata.scope,
                "origin": item.metadata.origin,
            }

    def getExtensions(self) -> LoadExtensionsResult:
        return self._extensions

    def getSkills(self) -> dict[str, Any]:
        return {"skills": list(self._skills), "diagnostics": list(self._skill_diagnostics)}

    def getPrompts(self) -> dict[str, Any]:
        return {"prompts": list(self._prompts), "diagnostics": []}

    def getThemes(self) -> dict[str, Any]:
        return {"themes": list(self._themes), "diagnostics": []}

    def getAgentsFiles(self) -> dict[str, Any]:
        return {"agentsFiles": list(self._agents_files)}

    def getSystemPrompt(self) -> str | None:
        return self._system_prompt

    def getAppendSystemPrompt(self) -> list[str]:
        return list(self._append_system_prompt)

    def getPathMetadata(self) -> dict[str, dict[str, str]]:
        return dict(self._path_metadata)

    def extendResources(self, paths: dict[str, list[dict[str, Any]]] | None = None) -> None:
        if not paths:
            return
        extension_paths = [str(item["path"]) for item in paths.get("extensionPaths", []) if item.get("path")]
        skill_paths = [str(item["path"]) for item in paths.get("skillPaths", []) if item.get("path")]
        prompt_paths = [str(item["path"]) for item in paths.get("promptPaths", []) if item.get("path")]
        if extension_paths:
            self.additional_extension_paths.extend(extension_paths)
        if skill_paths:
            self.additional_skill_paths.extend(skill_paths)
        if prompt_paths:
            self.additional_prompt_template_paths.extend(prompt_paths)
        if extension_paths or skill_paths or prompt_paths:
            self.reload()


def _resolve_prompt_input(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(os.path.expanduser(value))
    if path.exists() and path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return value
    return value


def _load_project_context_files(cwd: str, agent_dir: str) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    global_context = _load_context_file_from_dir(Path(agent_dir))
    if global_context is not None:
        files.append(global_context)
        seen.add(global_context["path"])

    current = Path(cwd).resolve()
    ancestors: list[dict[str, str]] = []
    while True:
        context = _load_context_file_from_dir(current)
        if context is not None and context["path"] not in seen:
            ancestors.insert(0, context)
            seen.add(context["path"])
        if current.parent == current:
            break
        current = current.parent

    files.extend(ancestors)
    return files


def _load_context_file_from_dir(path: Path) -> dict[str, str] | None:
    for filename in ("AGENTS.md", "CLAUDE.md"):
        candidate = path / filename
        if candidate.exists() and candidate.is_file():
            try:
                return {"path": candidate.as_posix(), "content": candidate.read_text(encoding="utf-8")}
            except OSError:
                continue
    return None
