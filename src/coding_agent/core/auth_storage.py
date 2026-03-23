# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.env_api_keys import get_env_api_key


@dataclass
class ApiKeyCredential:
    type: str
    key: str


class AuthStorage:
    def __init__(self, auth_path: str | None = None, data: dict[str, dict[str, Any]] | None = None) -> None:
        self.auth_path = auth_path
        self._data = dict(data or {})
        self._errors: list[Exception] = []
        if self.auth_path:
            self.reload()

    @classmethod
    def create(cls, agent_dir: str) -> AuthStorage:
        return cls(str(Path(agent_dir) / "auth.json"))

    @classmethod
    def in_memory(cls, data: dict[str, dict[str, Any]] | None = None) -> AuthStorage:
        return cls(None, data=data)

    def reload(self) -> None:
        if not self.auth_path:
            return
        path = Path(self.auth_path)
        if not path.exists():
            self._data = {}
            return
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self._data = loaded if isinstance(loaded, dict) else {}
        except Exception as exc:  # noqa: BLE001
            self._errors.append(exc)

    def drain_errors(self) -> list[Exception]:
        errors = list(self._errors)
        self._errors = []
        return errors

    def get(self, provider: str) -> dict[str, Any] | None:
        value = self._data.get(provider)
        return dict(value) if isinstance(value, dict) else None

    def list(self) -> list[str]:
        return sorted(self._data.keys())

    def has(self, provider: str) -> bool:
        return provider in self._data

    def has_auth(self, provider: str) -> bool:
        return self.has(provider) or get_env_api_key(provider) is not None

    def set_api_key(self, provider: str, api_key: str) -> None:
        self._data[provider] = {"type": "api_key", "key": api_key}
        self._persist()

    def login(self, provider: str, api_key: str) -> None:
        self.set_api_key(provider, api_key)

    def logout(self, provider: str) -> None:
        if provider in self._data:
            del self._data[provider]
            self._persist()

    def get_api_key(self, provider: str) -> str | None:
        credential = self.get(provider)
        if credential and credential.get("type") == "api_key":
            return str(credential.get("key") or "")
        return get_env_api_key(provider)

    def _persist(self) -> None:
        if not self.auth_path:
            return
        path = Path(self.auth_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
