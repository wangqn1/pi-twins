# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from .compaction import CompactionSettings, RetrySettings
from .workspace import resolve_workspace_dir

CONFIG_DIR_NAME = ".pi"


@dataclass
class SettingsError:
    scope: str
    error: Exception


def deep_merge_settings(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, override_value in overrides.items():
        if override_value is None:
            continue
        base_value = result.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            result[key] = deep_merge_settings(base_value, override_value)
        else:
            result[key] = deepcopy(override_value)
    return result


class SettingsManager:
    def __init__(
        self,
        *,
        cwd: str,
        agent_dir: str,
        global_settings_path: str | None = None,
        project_settings_path: str | None = None,
        global_settings: dict[str, Any] | None = None,
        project_settings: dict[str, Any] | None = None,
        errors: list[SettingsError] | None = None,
    ) -> None:
        self.cwd = cwd
        self.agent_dir = agent_dir
        self.global_settings_path = global_settings_path or (Path(self.agent_dir) / "settings.json").as_posix()
        self.project_settings_path = project_settings_path or (Path(self.cwd) / CONFIG_DIR_NAME / "settings.json").as_posix()
        self._global_settings = global_settings or {}
        self._project_settings = project_settings or {}
        self._errors = list(errors or [])
        self._settings = deep_merge_settings(self._global_settings, self._project_settings)

    @classmethod
    def create(cls, cwd: str | None = None, agent_dir: str | None = None) -> SettingsManager:
        resolved_cwd = Path(cwd or Path.cwd()).as_posix()
        resolved_agent_dir = agent_dir or resolve_workspace_dir(resolved_cwd)
        global_settings_path = Path(resolved_agent_dir) / "settings.json"
        project_settings_path = Path(resolved_cwd) / CONFIG_DIR_NAME / "settings.json"
        global_settings, global_error = _load_settings(global_settings_path)
        if global_settings_path.resolve() == project_settings_path.resolve():
            project_settings = dict(global_settings)
            project_error = global_error
        else:
            project_settings, project_error = _load_settings(project_settings_path)
        errors: list[SettingsError] = []
        if global_error is not None:
            errors.append(SettingsError(scope="global", error=global_error))
        if project_error is not None:
            errors.append(SettingsError(scope="project", error=project_error))
        return cls(
            cwd=resolved_cwd,
            agent_dir=resolved_agent_dir,
            global_settings_path=global_settings_path.as_posix(),
            project_settings_path=project_settings_path.as_posix(),
            global_settings=global_settings,
            project_settings=project_settings,
            errors=errors,
        )

    @classmethod
    def in_memory(
        cls,
        global_settings: dict[str, Any] | None = None,
        project_settings: dict[str, Any] | None = None,
    ) -> SettingsManager:
        return cls(
            cwd=Path.cwd().as_posix(),
            agent_dir=resolve_workspace_dir(),
            global_settings=global_settings,
            project_settings=project_settings,
        )

    def reload(self) -> None:
        fresh = SettingsManager.create(self.cwd, self.agent_dir)
        self._global_settings = fresh._global_settings
        self._project_settings = fresh._project_settings
        self._settings = fresh._settings
        self._errors = fresh._errors

    def drain_errors(self) -> list[SettingsError]:
        errors = list(self._errors)
        self._errors = []
        return errors

    def get_settings(self) -> dict[str, Any]:
        return deepcopy(self._settings)

    def get_global_settings(self) -> dict[str, Any]:
        return deepcopy(self._global_settings)

    def get_project_settings(self) -> dict[str, Any]:
        return deepcopy(self._project_settings)

    def get_default_provider(self) -> str | None:
        value = self._settings.get("defaultProvider")
        return str(value) if value else None

    def get_default_model(self) -> str | None:
        value = self._settings.get("defaultModel")
        return str(value) if value else None

    def set_default_model_and_provider(self, provider: str, model_id: str) -> None:
        self._global_settings["defaultProvider"] = provider
        self._global_settings["defaultModel"] = model_id
        self._refresh()

    def get_default_thinking_level(self) -> str | None:
        value = self._settings.get("defaultThinkingLevel")
        return str(value) if value else None

    def set_default_thinking_level(self, level: str) -> None:
        self._global_settings["defaultThinkingLevel"] = level
        self._refresh()

    def get_steering_mode(self) -> str:
        return str(self._settings.get("steeringMode") or "one-at-a-time")

    def set_steering_mode(self, mode: str) -> None:
        self._global_settings["steeringMode"] = mode
        self._refresh()

    def get_follow_up_mode(self) -> str:
        return str(self._settings.get("followUpMode") or "one-at-a-time")

    def set_follow_up_mode(self, mode: str) -> None:
        self._global_settings["followUpMode"] = mode
        self._refresh()

    def get_transport(self) -> str:
        return str(self._settings.get("transport") or "sse")

    def get_thinking_budgets(self) -> dict[str, int]:
        value = self._settings.get("thinkingBudgets")
        if not isinstance(value, dict):
            return {}
        return {str(k): int(v) for k, v in value.items() if isinstance(v, (int, float))}

    def get_compaction_settings(self) -> CompactionSettings:
        value = self._settings.get("compaction")
        if not isinstance(value, dict):
            return CompactionSettings()
        return CompactionSettings(
            enabled=bool(value.get("enabled", True)),
            reserve_tokens=int(value.get("reserveTokens", 16384)),
            keep_recent_tokens=int(value.get("keepRecentTokens", 20000)),
        )

    def get_compaction_enabled(self) -> bool:
        return bool(self.get_compaction_settings().enabled)

    def set_compaction_enabled(self, enabled: bool) -> None:
        compaction = dict(self._global_settings.get("compaction", {}))
        compaction["enabled"] = bool(enabled)
        self._global_settings["compaction"] = compaction
        self._refresh()

    def get_retry_settings(self) -> RetrySettings:
        value = self._settings.get("retry")
        if not isinstance(value, dict):
            return RetrySettings()
        return RetrySettings(
            enabled=bool(value.get("enabled", True)),
            max_retries=int(value.get("maxRetries", 3)),
            base_delay_ms=int(value.get("baseDelayMs", 2000)),
            max_delay_ms=int(value.get("maxDelayMs", 60000)),
        )

    def get_retry_enabled(self) -> bool:
        return bool(self.get_retry_settings().enabled)

    def set_retry_enabled(self, enabled: bool) -> None:
        retry = dict(self._global_settings.get("retry", {}))
        retry["enabled"] = bool(enabled)
        self._global_settings["retry"] = retry
        self._refresh()

    def get_theme(self) -> str | None:
        value = self._settings.get("theme")
        return str(value) if value else None

    def get_quiet_startup(self) -> bool:
        return bool(self._settings.get("quietStartup", False))

    def get_enabled_models(self) -> list[str]:
        value = self._settings.get("enabledModels")
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    def get_shell_command_prefix(self) -> str | None:
        value = self._settings.get("shellCommandPrefix")
        return str(value) if value else None

    def get_image_auto_resize(self) -> bool:
        images = self._settings.get("images")
        if isinstance(images, dict) and "autoResize" in images:
            return bool(images["autoResize"])
        return True

    def get_block_images(self) -> bool:
        images = self._settings.get("images")
        if isinstance(images, dict) and "blockImages" in images:
            return bool(images["blockImages"])
        return False

    def get_prompt_paths(self) -> list[str]:
        value = self._settings.get("prompts")
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    def get_extension_paths(self) -> list[str]:
        value = self._settings.get("extensions")
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    def get_skill_paths(self) -> list[str]:
        value = self._settings.get("skills")
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    def get_enable_skill_commands(self) -> bool:
        value = self._settings.get("enableSkillCommands")
        if value is None:
            return True
        return bool(value)

    def get_package_sources(self) -> list[Any]:
        value = self._settings.get("packages")
        if isinstance(value, list):
            return deepcopy(value)
        return []

    def get_global_package_sources(self) -> list[Any]:
        value = self._global_settings.get("packages")
        if isinstance(value, list):
            return deepcopy(value)
        return []

    def get_project_package_sources(self) -> list[Any]:
        value = self._project_settings.get("packages")
        if isinstance(value, list):
            return deepcopy(value)
        return []

    def set_global_setting(self, key: str, value: Any) -> None:
        if value is None:
            self._global_settings.pop(key, None)
        else:
            self._global_settings[key] = deepcopy(value)
        self._refresh()

    def set_project_setting(self, key: str, value: Any) -> None:
        if value is None:
            self._project_settings.pop(key, None)
        else:
            self._project_settings[key] = deepcopy(value)
        self._refresh()

    def write_global_settings(self) -> None:
        _write_settings(Path(self.global_settings_path), self._global_settings)

    def write_project_settings(self) -> None:
        _write_settings(Path(self.project_settings_path), self._project_settings)

    def _refresh(self) -> None:
        self._settings = deep_merge_settings(self._global_settings, self._project_settings)


def _load_settings(path: Path) -> tuple[dict[str, Any], Exception | None]:
    if not path.exists():
        return {}, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {}, exc
    if not isinstance(raw, dict):
        return {}, RuntimeError("Settings root must be an object")
    return _migrate_settings(raw), None


def _write_settings(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _migrate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    result = dict(settings)
    if "queueMode" in result and "steeringMode" not in result:
        result["steeringMode"] = result.pop("queueMode")
    if "transport" not in result and isinstance(result.get("websockets"), bool):
        result["transport"] = "websocket" if result.pop("websockets") else "sse"
    skills = result.get("skills")
    if isinstance(skills, dict):
        if result.get("enableSkillCommands") is None and "enableSkillCommands" in skills:
            result["enableSkillCommands"] = bool(skills["enableSkillCommands"])
        custom_directories = skills.get("customDirectories")
        if isinstance(custom_directories, list) and custom_directories:
            result["skills"] = [str(item) for item in custom_directories]
        else:
            result.pop("skills", None)
    return result
