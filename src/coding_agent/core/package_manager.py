from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .settings_manager import SettingsManager

RESOURCE_TYPES = ("extensions", "skills", "prompts", "themes")


@dataclass(frozen=True)
class PathMetadata:
    source: str
    scope: str
    origin: str
    base_dir: str | None = None


@dataclass(frozen=True)
class ResolvedResource:
    path: str
    enabled: bool
    metadata: PathMetadata


@dataclass(frozen=True)
class ResolvedPaths:
    extensions: list[ResolvedResource]
    skills: list[ResolvedResource]
    prompts: list[ResolvedResource]
    themes: list[ResolvedResource]


class DefaultPackageManager:
    def __init__(self, *, cwd: str, agent_dir: str, settings_manager: SettingsManager) -> None:
        self.cwd = Path(cwd).resolve().as_posix()
        self.agent_dir = Path(agent_dir).resolve().as_posix()
        self.settings_manager = settings_manager
        self._progress_callback: Any = None

    def set_progress_callback(self, callback: Any) -> None:
        self._progress_callback = callback

    def resolve(self) -> ResolvedPaths:
        accumulator = {resource_type: {} for resource_type in RESOURCE_TYPES}
        for source in self.settings_manager.get_project_package_sources():
            self._collect_source(source, "project", accumulator)
        for source in self.settings_manager.get_global_package_sources():
            self._collect_source(source, "user", accumulator)
        return ResolvedPaths(
            extensions=list(accumulator["extensions"].values()),
            skills=list(accumulator["skills"].values()),
            prompts=list(accumulator["prompts"].values()),
            themes=list(accumulator["themes"].values()),
        )

    def install(self, source: str, options: dict[str, Any] | None = None) -> str:
        options = options or {}
        parsed = _normalize_package_source(source)
        if parsed["type"] != "local":
            raise ValueError("Python parity package manager currently supports local sources only")
        path = Path(parsed["path"])
        if not path.exists():
            raise ValueError(f"Package source does not exist: {path.as_posix()}")
        return path.as_posix()

    def remove(self, source: str, options: dict[str, Any] | None = None) -> None:
        del options
        parsed = _normalize_package_source(source)
        if parsed["type"] != "local":
            raise ValueError("Python parity package manager currently supports local sources only")

    def update(self, source: str | None = None) -> None:
        if source is not None:
            parsed = _normalize_package_source(source)
            if parsed["type"] != "local":
                raise ValueError("Python parity package manager currently supports local sources only")
            if not Path(parsed["path"]).exists():
                raise ValueError(f"Package source does not exist: {parsed['path']}")
            return
        for package in self.settings_manager.get_package_sources():
            normalized = _normalize_package_source(package)
            if normalized["type"] != "local":
                raise ValueError("Python parity package manager currently supports local sources only")
            if not Path(normalized["path"]).exists():
                raise ValueError(f"Package source does not exist: {normalized['path']}")

    def add_source_to_settings(self, source: str, options: dict[str, Any] | None = None) -> bool:
        options = options or {}
        local = bool(options.get("local"))
        scope_packages = self._get_scope_packages(local)
        normalized = _normalize_package_source(source)
        source_value = _source_storage_value(normalized)
        if any(_same_package_source(item, source_value) for item in scope_packages):
            return False
        scope_packages.append(source_value)
        self._set_scope_packages(scope_packages, local)
        return True

    def remove_source_from_settings(self, source: str, options: dict[str, Any] | None = None) -> bool:
        options = options or {}
        local = bool(options.get("local"))
        scope_packages = self._get_scope_packages(local)
        normalized = _normalize_package_source(source)
        source_value = _source_storage_value(normalized)
        remaining = [item for item in scope_packages if not _same_package_source(item, source_value)]
        if len(remaining) == len(scope_packages):
            return False
        self._set_scope_packages(remaining, local)
        return True

    def get_installed_path(self, source: str, scope: str) -> str | None:
        normalized = _normalize_package_source(source)
        if normalized["type"] == "local":
            return normalized["path"]
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
        base = Path(self.agent_dir) / "packages" / ("project" if scope == "project" else "user")
        return (base / digest).as_posix()

    def _get_scope_packages(self, local: bool) -> list[Any]:
        return self.settings_manager.get_project_package_sources() if local else self.settings_manager.get_global_package_sources()

    def _set_scope_packages(self, packages: list[Any], local: bool) -> None:
        if local:
            self.settings_manager.set_project_setting("packages", packages or None)
            self.settings_manager.write_project_settings()
        else:
            self.settings_manager.set_global_setting("packages", packages or None)
            self.settings_manager.write_global_settings()
        self.settings_manager.reload()

    def _collect_source(self, source: Any, scope: str, accumulator: dict[str, dict[str, ResolvedResource]]) -> None:
        normalized = _normalize_package_source(source)
        if normalized["type"] != "local":
            return
        root = Path(normalized["path"])
        if not root.exists():
            return
        metadata = PathMetadata(
            source=_display_source(source),
            scope=scope,
            origin="package",
            base_dir=root.as_posix(),
        )
        manifest = _read_pi_manifest(root)
        for resource_type in RESOURCE_TYPES:
            entries = manifest.get(resource_type) if manifest else None
            if isinstance(entries, list):
                self._collect_manifest_entries(root, resource_type, entries, metadata, accumulator[resource_type])
            else:
                self._collect_default_dir(root / resource_type, resource_type, metadata, accumulator[resource_type])

    def _collect_manifest_entries(
        self,
        root: Path,
        resource_type: str,
        entries: list[Any],
        metadata: PathMetadata,
        target: dict[str, ResolvedResource],
    ) -> None:
        for entry in entries:
            if not isinstance(entry, str):
                continue
            path = (root / entry).resolve() if not Path(entry).is_absolute() else Path(entry).resolve()
            self._add_resource(path, resource_type, metadata, target)

    def _collect_default_dir(
        self,
        directory: Path,
        resource_type: str,
        metadata: PathMetadata,
        target: dict[str, ResolvedResource],
    ) -> None:
        if not directory.exists() or not directory.is_dir():
            return
        if resource_type == "extensions":
            for path in _discover_extension_files(directory):
                self._add_resource(path, resource_type, metadata, target)
            return
        if resource_type == "skills":
            for path in _discover_skill_files(directory):
                self._add_resource(path, resource_type, metadata, target)
            return
        suffix = ".md" if resource_type == "prompts" else ".json"
        for path in sorted(directory.rglob(f"*{suffix}")):
            if path.is_file() and not any(part.startswith(".") for part in path.parts):
                self._add_resource(path, resource_type, metadata, target)

    def _add_resource(self, path: Path, resource_type: str, metadata: PathMetadata, target: dict[str, ResolvedResource]) -> None:
        if not path.exists():
            return
        resolved_path = path.as_posix()
        if resolved_path in target:
            return
        target[resolved_path] = ResolvedResource(path=resolved_path, enabled=True, metadata=metadata)


def render_package_list(settings_manager: SettingsManager, package_manager: DefaultPackageManager) -> str:
    global_packages = settings_manager.get_global_package_sources()
    project_packages = settings_manager.get_project_package_sources()
    if not global_packages and not project_packages:
        return "No packages installed."

    lines: list[str] = []
    if global_packages:
        lines.append("User packages:")
        for package in global_packages:
            source = _display_source(package)
            lines.append(f"  {source}")
            installed = package_manager.get_installed_path(source, "user")
            if installed:
                lines.append(f"    {installed}")
    if project_packages:
        if lines:
            lines.append("")
        lines.append("Project packages:")
        for package in project_packages:
            source = _display_source(package)
            lines.append(f"  {source}")
            installed = package_manager.get_installed_path(source, "project")
            if installed:
                lines.append(f"    {installed}")
    return "\n".join(lines)


def render_config_snapshot(
    *,
    cwd: str,
    agent_dir: str,
    settings_manager: SettingsManager,
    package_manager: DefaultPackageManager,
) -> str:
    resolved = package_manager.resolve()
    payload = {
        "cwd": cwd,
        "agentDir": agent_dir,
        "settings": settings_manager.get_settings(),
        "packages": {
            "user": settings_manager.get_global_package_sources(),
            "project": settings_manager.get_project_package_sources(),
        },
        "resources": {
            "extensions": [_resource_to_dict(item) for item in resolved.extensions],
            "skills": [_resource_to_dict(item) for item in resolved.skills],
            "prompts": [_resource_to_dict(item) for item in resolved.prompts],
            "themes": [_resource_to_dict(item) for item in resolved.themes],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _resource_to_dict(resource: ResolvedResource) -> dict[str, Any]:
    return {
        "path": resource.path,
        "enabled": resource.enabled,
        "metadata": {
            "source": resource.metadata.source,
            "scope": resource.metadata.scope,
            "origin": resource.metadata.origin,
            "baseDir": resource.metadata.base_dir,
        },
    }


def _normalize_package_source(source: Any) -> dict[str, Any]:
    if isinstance(source, dict):
        source_value = str(source.get("source") or "").strip()
        filter_value = {key: value for key, value in source.items() if key != "source"}
    else:
        source_value = str(source).strip()
        filter_value = {}
    if not source_value:
        raise ValueError("Package source must not be empty")
    path = Path(os.path.expanduser(source_value))
    if path.is_absolute() or source_value.startswith(".") or path.exists():
        return {"type": "local", "path": path.resolve().as_posix(), "filters": filter_value}
    if "://" in source_value or source_value.startswith("git:") or source_value.startswith("npm:"):
        return {"type": "remote", "source": source_value, "filters": filter_value}
    return {"type": "local", "path": (Path.cwd() / path).resolve().as_posix(), "filters": filter_value}


def _source_storage_value(source: dict[str, Any]) -> Any:
    if source["type"] == "local":
        value = source["path"]
    else:
        value = source["source"]
    filters = dict(source.get("filters") or {})
    if not filters:
        return value
    filters["source"] = value
    return filters


def _same_package_source(left: Any, right: Any) -> bool:
    return _display_source(left) == _display_source(right)


def _display_source(source: Any) -> str:
    if isinstance(source, dict):
        return str(source.get("source") or "").strip()
    return str(source).strip()


def _read_pi_manifest(root: Path) -> dict[str, Any] | None:
    package_json = root / "package.json"
    if not package_json.exists():
        return None
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    pi = payload.get("pi")
    return pi if isinstance(pi, dict) else None


def _discover_extension_files(directory: Path) -> list[Path]:
    results: list[Path] = []
    for entry in sorted(directory.iterdir()):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if entry.is_file() and entry.suffix == ".py":
            results.append(entry)
        elif entry.is_dir():
            init_file = entry / "__init__.py"
            extension_file = entry / "extension.py"
            if init_file.exists():
                results.append(init_file)
            elif extension_file.exists():
                results.append(extension_file)
    return results


def _discover_skill_files(directory: Path) -> list[Path]:
    results: list[Path] = []
    for entry in sorted(directory.rglob("*.md")):
        if any(part.startswith(".") for part in entry.parts):
            continue
        if entry.name == "SKILL.md" or entry.parent == directory:
            results.append(entry)
    return results
