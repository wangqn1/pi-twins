# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import Any

from ..workspace import resolve_workspace_dir
from .types import Extension

CONFIG_DIR_NAME = ".pi"


@dataclass
class ExtensionRuntime:
    values: dict[str, Any] = field(default_factory=dict)


def create_extension_runtime() -> ExtensionRuntime:
    return ExtensionRuntime()


def load_extensions(
    *,
    cwd: str | None = None,
    agent_dir: str | None = None,
    extension_paths: list[str] | None = None,
    include_defaults: bool = True,
) -> dict[str, Any]:
    resolved_cwd = Path(cwd or Path.cwd()).resolve()
    resolved_agent_dir = Path(agent_dir or resolve_workspace_dir(resolved_cwd.as_posix())).resolve()
    runtime = create_extension_runtime()
    extensions: list[Extension] = []
    errors: list[str] = []
    seen_paths: set[str] = set()

    def load_path(raw_path: str) -> None:
        path = _resolve_path(raw_path, resolved_cwd)
        if not path.exists():
            errors.append(f"Extension path does not exist: {path.as_posix()}")
            return

        candidates = _discover_extension_files(path)
        if not candidates:
            errors.append(f"No Python extensions found at: {path.as_posix()}")
            return

        for candidate in candidates:
            try:
                real = candidate.resolve().as_posix()
            except OSError:
                real = candidate.as_posix()
            if real in seen_paths:
                continue
            seen_paths.add(real)
            try:
                extension = _load_extension_from_file(candidate)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{candidate.as_posix()}: {exc}")
                continue
            extension.path = candidate.as_posix()
            for command in extension.registered_commands:
                if not command.path:
                    command.path = extension.path
            extensions.append(extension)

    if include_defaults:
        load_path((resolved_agent_dir / "extensions").as_posix())
        load_path((resolved_cwd / CONFIG_DIR_NAME / "extensions").as_posix())

    for raw_path in extension_paths or []:
        load_path(raw_path)

    return {"extensions": extensions, "errors": errors, "runtime": runtime}


def _discover_extension_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix == ".py" else []

    if not path.is_dir():
        return []

    candidates: list[Path] = []
    for entry in sorted(path.iterdir()):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if entry.is_file() and entry.suffix == ".py":
            candidates.append(entry)
        elif entry.is_dir():
            init_file = entry / "__init__.py"
            extension_file = entry / "extension.py"
            if init_file.exists():
                candidates.append(init_file)
            elif extension_file.exists():
                candidates.append(extension_file)
    return candidates


def _load_extension_from_file(path: Path) -> Extension:
    module = _load_module(path)
    for attr in ("extension", "EXTENSION"):
        value = getattr(module, attr, None)
        if isinstance(value, Extension):
            return value

    for attr in ("create_extension", "load_extension", "get_extension"):
        value = getattr(module, attr, None)
        if callable(value):
            created = value()
            if isinstance(created, Extension):
                return created
            raise RuntimeError(f"{attr}() must return Extension")

    raise RuntimeError("Extension module must export `extension`, `EXTENSION`, or `create_extension()`")


def _load_module(path: Path) -> ModuleType:
    digest = hashlib.sha1(path.as_posix().encode("utf-8")).hexdigest()[:12]
    module_name = f"coding_agent_extension_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not create module spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_path(raw_path: str, cwd: Path) -> Path:
    expanded = os.path.expanduser(raw_path.strip())
    path = Path(expanded)
    if path.is_absolute():
        return path
    return (cwd / path).resolve()
