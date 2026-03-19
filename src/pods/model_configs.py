from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from .types import GPU


@dataclass
class ModelSelection:
    args: list[str]
    env: dict[str, str] | None = None
    notes: str | None = None


def _extract_gpu_type(gpus: list[GPU]) -> str:
    if not gpus:
        return ""
    name = gpus[0].name.replace("NVIDIA", "").strip()
    return name.split(" ")[0] if name else ""


@lru_cache(maxsize=1)
def _load_models() -> dict[str, object]:
    raw = resources.files("pods").joinpath("models.json").read_text(encoding="utf-8")
    return json.loads(raw)


def get_model_config(model_id: str, gpus: list[GPU], requested_gpu_count: int) -> ModelSelection | None:
    data = _load_models()
    models = data.get("models", {})
    if not isinstance(models, dict):
        return None
    model_info = models.get(model_id)
    if not isinstance(model_info, dict):
        return None

    configs = model_info.get("configs", [])
    if not isinstance(configs, list):
        return None

    gpu_type = _extract_gpu_type(gpus)
    best_config: dict[str, object] | None = None

    for config in configs:
        if not isinstance(config, dict):
            continue
        if int(config.get("gpuCount", 0)) != requested_gpu_count:
            continue
        config_gpu_types = config.get("gpuTypes", [])
        if isinstance(config_gpu_types, list) and config_gpu_types:
            matches = any(
                isinstance(item, str) and (gpu_type in item or item in gpu_type)
                for item in config_gpu_types
            )
            if not matches:
                continue
        best_config = config
        break

    if best_config is None:
        for config in configs:
            if isinstance(config, dict) and int(config.get("gpuCount", 0)) == requested_gpu_count:
                best_config = config
                break

    if best_config is None:
        return None

    args = best_config.get("args", [])
    env = best_config.get("env")
    notes = best_config.get("notes") or model_info.get("notes")
    return ModelSelection(
        args=[str(item) for item in args] if isinstance(args, list) else [],
        env={str(key): str(value) for key, value in env.items()} if isinstance(env, dict) else None,
        notes=str(notes) if notes else None,
    )


def is_known_model(model_id: str) -> bool:
    data = _load_models()
    models = data.get("models", {})
    return isinstance(models, dict) and model_id in models


def get_known_models() -> list[str]:
    data = _load_models()
    models = data.get("models", {})
    if not isinstance(models, dict):
        return []
    return sorted(str(key) for key in models.keys())


def get_model_name(model_id: str) -> str:
    data = _load_models()
    models = data.get("models", {})
    if not isinstance(models, dict):
        return model_id
    model_info = models.get(model_id)
    if not isinstance(model_info, dict):
        return model_id
    return str(model_info.get("name", model_id))
