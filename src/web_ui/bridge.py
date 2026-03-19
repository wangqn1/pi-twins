from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Any

from ai import Model

from .example_app import WebUiExampleConfig, _build_agent_session


def _json_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, set):
        return sorted(_json_value(item) for item in value)
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _tool_descriptor(tool: Any) -> dict[str, Any]:
    return {
        "name": str(getattr(tool, "name", "")),
        "label": str(getattr(tool, "label", getattr(tool, "name", ""))),
        "description": str(getattr(tool, "description", "")),
    }


@dataclass
class WebUiBridgeConfig:
    cwd: str
    session_dir: str | None = None
    resume_session: bool = False
    agent_dir: str | None = None
    provider: str = "openai"
    api: str = "openai-completions"
    model_name: str = "qwen3.5-122b-vl"
    base_url: str = "http://192.168.64.22:3001/v1"
    api_key: str | None = None
    system_prompt: str = ""
    thinking_level: str = "off"
    with_tools: bool = True
    backend: Any = None
    no_skills: bool = False
    additional_skill_paths: list[str] | None = None

    @classmethod
    def from_example_config(cls, config: WebUiExampleConfig) -> "WebUiBridgeConfig":
        return cls(
            cwd=config.cwd,
            session_dir=config.session_dir,
            resume_session=False,
            agent_dir=config.agent_dir,
            provider=config.provider,
            api=config.api,
            model_name=config.model_name,
            base_url=config.base_url,
            api_key=config.api_key,
            system_prompt=config.system_prompt,
            thinking_level=config.thinking_level,
            with_tools=config.with_tools,
            backend=config.backend,
            no_skills=config.no_skills,
            additional_skill_paths=list(config.additional_skill_paths or []),
        )


class WebUiBridgeBackend:
    def __init__(self, config: WebUiBridgeConfig) -> None:
        self.config = config
        self.session = _build_agent_session(
            WebUiExampleConfig(
                cwd=config.cwd,
                session_dir=config.session_dir,
                agent_dir=config.agent_dir,
                provider=config.provider,
                api=config.api,
                model_name=config.model_name,
                base_url=config.base_url,
                api_key=config.api_key,
                thinking_level=config.thinking_level,
                with_tools=config.with_tools,
                system_prompt=config.system_prompt,
                backend=config.backend,
                no_skills=config.no_skills,
                additional_skill_paths=list(config.additional_skill_paths or []),
            ),
            session_manager=_create_session_manager(config),
        )

    def _serialize_state(self) -> dict[str, Any]:
        state = self.session.state
        return {
            "model": _json_value(self.session.model),
            "thinkingLevel": self.session.thinking_level,
            "messages": _json_value(state.messages),
            "tools": [_tool_descriptor(tool) for tool in state.tools],
            "isStreaming": bool(state.is_streaming),
            "streamMessage": _json_value(state.stream_message),
            "pendingToolCalls": sorted(state.pending_tool_calls),
            "error": state.error,
            "sessionId": self.session.session_id,
            "sessionFile": self.session.session_file,
            "sessionTitle": self.session.session_manager.get_session_name(),
            "cwd": self.config.cwd,
        }

    def get_state(self) -> dict[str, Any]:
        return self._serialize_state()

    def prompt(self, message: str | dict[str, Any] | list[Any]) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        unsubscribe = self.session.subscribe(lambda event: events.append(_json_value(event)))
        try:
            self.session.prompt(message)
        finally:
            unsubscribe()
        return {"events": events, "state": self._serialize_state()}

    def stream_prompt(self, message: str | dict[str, Any] | list[Any]):
        queue: Queue[dict[str, Any] | object] = Queue()
        sentinel = object()

        def listener(event: dict[str, Any]) -> None:
            queue.put({"kind": "event", "event": _json_value(event)})

        unsubscribe = self.session.subscribe(listener)

        def run() -> None:
            try:
                self.session.prompt(message)
                queue.put({"kind": "state", "state": self._serialize_state()})
            except Exception as exc:  # noqa: BLE001
                queue.put({"kind": "error", "error": str(exc)})
            finally:
                unsubscribe()
                queue.put(sentinel)

        Thread(target=run, daemon=True).start()

        while True:
            item = queue.get()
            if item is sentinel:
                break
            yield item

    def abort(self) -> dict[str, Any]:
        self.session.abort()
        return self._serialize_state()

    def set_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.session.model
        provider = str(payload.get("provider") or current.provider)
        model_id = str(payload.get("id") or current.id)
        api = str(payload.get("api") or current.api)
        name = str(payload.get("name") or model_id)
        base_url = str(payload.get("baseUrl") or payload.get("base_url") or current.base_url)
        self.session.set_model(
            Model(
                provider=provider,
                id=model_id,
                name=name,
                api=api,
                base_url=base_url,
                reasoning=bool(payload.get("reasoning", current.reasoning)),
                context_window=int(payload.get("contextWindow", current.context_window)),
                max_tokens=int(payload.get("maxTokens", current.max_tokens)),
                input=list(payload.get("input", current.input)),
                headers=dict(payload.get("headers", current.headers)),
                cost=current.cost,
            )
        )
        return self._serialize_state()

    def set_thinking_level(self, level: str) -> dict[str, Any]:
        self.session.set_thinking_level(level)
        return self._serialize_state()

    def new_session(self) -> dict[str, Any]:
        self.session.new_session()
        return self._serialize_state()

    def reload(self) -> dict[str, Any]:
        self.session.reload()
        return self._serialize_state()

    def export_html(self, output_path: str | None = None) -> dict[str, Any]:
        return {"path": self.session.export_to_html(output_path)}


def _create_session_manager(config: WebUiBridgeConfig):
    from coding_agent.core.session_manager import SessionManager

    cwd = Path(config.cwd).resolve().as_posix()
    if config.resume_session:
        return SessionManager.continue_recent(cwd, session_dir=config.session_dir)
    return SessionManager.create(cwd, session_dir=config.session_dir)
