# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_WORKSPACE_DIR_NAME = ".pi"


def _resolve_path(raw_path: str, cwd: str | None = None) -> Path:
    base = Path(cwd or Path.cwd()).resolve()
    expanded = os.path.expanduser(raw_path.strip())
    path = Path(expanded)
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def resolve_workspace_dir(cwd: str | None = None, workspace_dir: str | None = None) -> str:
    configured = workspace_dir or os.environ.get("PI_CONFIG_DIR")
    if configured:
        return _resolve_path(configured, cwd).as_posix()
    base = Path(cwd or Path.cwd()).resolve()
    return (base / DEFAULT_WORKSPACE_DIR_NAME).as_posix()


def resolve_session_dir(
    cwd: str | None = None,
    session_dir: str | None = None,
    workspace_dir: str | None = None,
) -> str:
    if session_dir:
        return _resolve_path(session_dir, cwd).as_posix()
    return (Path(resolve_workspace_dir(cwd, workspace_dir)) / "sessions").as_posix()
