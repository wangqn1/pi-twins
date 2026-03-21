from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from ai import Model


def default_llm_request_log_path(cwd: str) -> str:
    return (Path(cwd).resolve() / ".pi" / "logs" / "web-ui-llm-requests.jsonl").as_posix()


def _json_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_value(item) for item in value)
    return value


class WebUiLLMRequestLogger:
    def __init__(self, *, cwd: str, output_path: str | None = None) -> None:
        self.cwd = Path(cwd).resolve().as_posix()
        self.output_path = Path(output_path or default_llm_request_log_path(cwd)).resolve()
        self._lock = Lock()

    def log_payload(self, payload: Any, model: Model) -> Any:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "cwd": self.cwd,
            "request": {
                "provider": model.provider,
                "model": model.id,
                "api": model.api,
                "baseUrl": model.base_url,
                "payload": _json_value(payload),
            },
        }
        encoded = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with self.output_path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
        return payload
