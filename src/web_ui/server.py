# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import urlparse

from .bridge import WebUiBridgeBackend, WebUiBridgeConfig


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_length = int(handler.headers.get("Content-Length", "0"))
    if content_length <= 0:
        return {}
    raw = handler.rfile.read(content_length)
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def _send_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _send_ndjson(handler: BaseHTTPRequestHandler, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    handler.wfile.write(encoded)
    handler.wfile.flush()


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".map": "application/json; charset=utf-8",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".ts": "text/plain; charset=utf-8",
    }.get(suffix, "application/octet-stream")


class WebUiHttpServer(ThreadingHTTPServer, ThreadingMixIn):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], app: "WebUiServerApp"):
        super().__init__(server_address, handler_class)
        self.app = app
        self._lock = threading.RLock()


@dataclass
class WebUiServerApp:
    backend: WebUiBridgeBackend
    static_dir: Path
    index_file: Path

    def get_state(self) -> dict[str, Any]:
        return self.backend.get_state()

    def prompt(self, message: str | dict[str, Any] | list[Any]) -> dict[str, Any]:
        return self.backend.prompt(message)

    def stream_prompt(self, message: str | dict[str, Any] | list[Any]):
        return self.backend.stream_prompt(message)

    def abort(self) -> dict[str, Any]:
        return self.backend.abort()

    def set_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.backend.set_model(payload)

    def set_thinking_level(self, level: str) -> dict[str, Any]:
        return self.backend.set_thinking_level(level)

    def new_session(self) -> dict[str, Any]:
        return self.backend.new_session()

    def reload(self) -> dict[str, Any]:
        return self.backend.reload()

    def export_html(self, output_path: str | None = None) -> dict[str, Any]:
        return self.backend.export_html(output_path)


class WebUiRequestHandler(BaseHTTPRequestHandler):
    server: WebUiHttpServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        del format, args

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            _send_json(self, {"ok": True})
            return
        if parsed.path == "/api/state":
            with self.server._lock:
                _send_json(self, {"ok": True, "state": self.server.app.get_state()})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = _read_json(self)
        except (ValueError, json.JSONDecodeError) as exc:
            _send_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        parsed = urlparse(self.path)
        if parsed.path == "/api/prompt/stream":
            self._handle_stream_prompt(payload)
            return

        try:
            with self.server._lock:
                if parsed.path == "/api/prompt":
                    message = payload.get("message", "")
                    if not isinstance(message, (str, dict, list)):
                        raise ValueError("message must be a string, object, or list")
                    result = self.server.app.prompt(message)
                elif parsed.path == "/api/abort":
                    result = {"state": self.server.app.abort()}
                elif parsed.path == "/api/model":
                    result = {"state": self.server.app.set_model(payload)}
                elif parsed.path == "/api/thinking":
                    level = str(payload.get("level") or "off")
                    result = {"state": self.server.app.set_thinking_level(level)}
                elif parsed.path == "/api/session/new":
                    result = {"state": self.server.app.new_session()}
                elif parsed.path == "/api/session/reload":
                    result = {"state": self.server.app.reload()}
                elif parsed.path == "/api/export":
                    result = self.server.app.export_html(payload.get("path"))
                else:
                    _send_json(self, {"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
                    return
        except (RuntimeError, ValueError, KeyError) as exc:
            _send_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        _send_json(self, {"ok": True, **result})

    def _handle_stream_prompt(self, payload: dict[str, Any]) -> None:
        message = payload.get("message", "")
        if not isinstance(message, (str, dict, list)):
            _send_json(self, {"ok": False, "error": "message must be a string, object, or list"}, HTTPStatus.BAD_REQUEST)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        try:
            with self.server._lock:
                for item in self.server.app.stream_prompt(message):
                    _send_ndjson(self, {"ok": True, **item})
        except (BrokenPipeError, ConnectionResetError):
            return

    def _serve_static(self, raw_path: str) -> None:
        requested = raw_path or "/"
        if requested in {"/", ""}:
            target = self.server.app.index_file
        else:
            target = (self.server.app.static_dir / requested.lstrip("/")).resolve()

        static_root = self.server.app.static_dir.resolve()
        if not str(target).startswith(str(static_root)):
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        if not target.exists() or not target.is_file():
            target = self.server.app.index_file
        try:
            data = target.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", _guess_content_type(target))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def create_web_ui_server(
    config: WebUiBridgeConfig,
    *,
    host: str = "0.0.0.0",
    port: int = 8765,
    static_dir: str | Path | None = None,
) -> WebUiHttpServer:
    backend = WebUiBridgeBackend(config)
    resolved_static_dir = Path(static_dir or Path(__file__).resolve().parent / "frontend" / "dist").resolve()
    index_file = resolved_static_dir / "index.html"
    if not index_file.exists():
        raise FileNotFoundError(f"Frontend bundle not found: {index_file}")
    app = WebUiServerApp(backend=backend, static_dir=resolved_static_dir, index_file=index_file)
    return WebUiHttpServer((host, port), WebUiRequestHandler, app)
