from __future__ import annotations

import json
import os
from pathlib import Path

from .types import Config, GPU, Pod, PodModel


def get_config_dir(config_dir: str | None = None) -> Path:
    base = Path(config_dir or os.environ.get("PI_CONFIG_DIR") or (Path.home() / ".pi"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_config_path(config_dir: str | None = None) -> Path:
    return get_config_dir(config_dir) / "pods.json"


def _pod_model_from_dict(data: dict[str, object]) -> PodModel:
    return PodModel(
        model=str(data.get("model", "")),
        port=int(data.get("port", 0)),
        gpu=[int(item) for item in data.get("gpu", [])] if isinstance(data.get("gpu"), list) else [],
        pid=int(data.get("pid", 0)),
    )


def _gpu_from_dict(data: dict[str, object]) -> GPU:
    return GPU(
        id=int(data.get("id", 0)),
        name=str(data.get("name", "")),
        memory=str(data.get("memory", "")),
    )


def _pod_from_dict(data: dict[str, object]) -> Pod:
    raw_models = data.get("models", {})
    models: dict[str, PodModel] = {}
    if isinstance(raw_models, dict):
        for name, value in raw_models.items():
            if isinstance(value, dict):
                models[str(name)] = _pod_model_from_dict(value)

    raw_gpus = data.get("gpus", [])
    gpus = [_gpu_from_dict(item) for item in raw_gpus if isinstance(item, dict)] if isinstance(raw_gpus, list) else []

    vllm_value = data.get("vllmVersion")
    if not isinstance(vllm_value, str):
        vllm_value = data.get("vllm_version")

    return Pod(
        ssh=str(data.get("ssh", "")),
        gpus=gpus,
        models=models,
        models_path=str(data["modelsPath"]) if "modelsPath" in data and data["modelsPath"] is not None else (
            str(data["models_path"]) if "models_path" in data and data["models_path"] is not None else None
        ),
        vllm_version=vllm_value if vllm_value in {"release", "nightly", "gpt-oss"} else None,
    )


def _config_from_dict(data: dict[str, object]) -> Config:
    raw_pods = data.get("pods", {})
    pods: dict[str, Pod] = {}
    if isinstance(raw_pods, dict):
        for name, pod in raw_pods.items():
            if isinstance(pod, dict):
                pods[str(name)] = _pod_from_dict(pod)
    active = data.get("active")
    return Config(pods=pods, active=str(active) if active is not None else None)


def _pod_model_to_dict(model: PodModel) -> dict[str, object]:
    return {
        "model": model.model,
        "port": model.port,
        "gpu": list(model.gpu),
        "pid": model.pid,
    }


def _gpu_to_dict(gpu: GPU) -> dict[str, object]:
    return {"id": gpu.id, "name": gpu.name, "memory": gpu.memory}


def _pod_to_dict(pod: Pod) -> dict[str, object]:
    payload: dict[str, object] = {
        "ssh": pod.ssh,
        "gpus": [_gpu_to_dict(gpu) for gpu in pod.gpus],
        "models": {name: _pod_model_to_dict(model) for name, model in pod.models.items()},
    }
    if pod.models_path is not None:
        payload["modelsPath"] = pod.models_path
    if pod.vllm_version is not None:
        payload["vllmVersion"] = pod.vllm_version
    return payload


def _config_to_dict(config: Config) -> dict[str, object]:
    payload: dict[str, object] = {"pods": {name: _pod_to_dict(pod) for name, pod in config.pods.items()}}
    if config.active is not None:
        payload["active"] = config.active
    return payload


def load_config(config_dir: str | None = None) -> Config:
    config_path = get_config_path(config_dir)
    if not config_path.exists():
        return Config()
    try:
        return _config_from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return Config()


def save_config(config: Config, config_dir: str | None = None) -> None:
    config_path = get_config_path(config_dir)
    config_path.write_text(json.dumps(_config_to_dict(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_active_pod(config_dir: str | None = None) -> tuple[str, Pod] | None:
    config = load_config(config_dir)
    if config.active is None:
        return None
    pod = config.pods.get(config.active)
    if pod is None:
        return None
    return config.active, pod


def add_pod(name: str, pod: Pod, config_dir: str | None = None) -> None:
    config = load_config(config_dir)
    config.pods[name] = pod
    if config.active is None:
        config.active = name
    save_config(config, config_dir)


def remove_pod(name: str, config_dir: str | None = None) -> None:
    config = load_config(config_dir)
    config.pods.pop(name, None)
    if config.active == name:
        config.active = None
    save_config(config, config_dir)


def set_active_pod(name: str, config_dir: str | None = None) -> None:
    config = load_config(config_dir)
    if name not in config.pods:
        raise ValueError(f"Pod '{name}' not found")
    config.active = name
    save_config(config, config_dir)
