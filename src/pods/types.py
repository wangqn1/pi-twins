from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

VLLMVersion = Literal["release", "nightly", "gpt-oss"]


@dataclass
class GPU:
    id: int
    name: str
    memory: str


@dataclass
class PodModel:
    model: str
    port: int
    gpu: list[int] = field(default_factory=list)
    pid: int = 0


@dataclass
class Pod:
    ssh: str
    gpus: list[GPU] = field(default_factory=list)
    models: dict[str, PodModel] = field(default_factory=dict)
    models_path: str | None = None
    vllm_version: VLLMVersion | None = None


@dataclass
class Config:
    pods: dict[str, Pod] = field(default_factory=dict)
    active: str | None = None
