# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass

from .bridge import WebUiBridgeBackend, WebUiBridgeConfig
from .example_app import DEFAULT_EXAMPLE_BASE_URL, DEFAULT_EXAMPLE_MODEL, WebUiExampleConfig, WebUiStyleExampleApp
from .main import build_web_ui_frontend, build_web_ui_parser, web_ui_main
from .server import WebUiServerApp, WebUiHttpServer, create_web_ui_server


@dataclass
class WebUiSettings:
    enable_attachments: bool = True
    enable_model_selector: bool = True
    enable_thinking_selector: bool = True


__all__ = [
    "DEFAULT_EXAMPLE_BASE_URL",
    "DEFAULT_EXAMPLE_MODEL",
    "WebUiBridgeBackend",
    "WebUiBridgeConfig",
    "WebUiHttpServer",
    "WebUiServerApp",
    "WebUiExampleConfig",
    "WebUiSettings",
    "WebUiStyleExampleApp",
    "build_web_ui_frontend",
    "build_web_ui_parser",
    "create_web_ui_server",
    "web_ui_main",
]
