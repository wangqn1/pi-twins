from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from .bridge import WebUiBridgeConfig
from .server import create_web_ui_server

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
DEFAULT_BASE_URL = "http://192.168.64.22:3001/v1"
DEFAULT_MODEL = "qwen3.5-122b-vl"


def build_web_ui_frontend(*, cwd: str | None = None) -> Path:
    frontend_dir = Path(cwd or Path(__file__).resolve().parent / "frontend").resolve()
    vite_bin = Path(__file__).resolve().parents[2] / "tools" / "pi-mono" / "node_modules" / ".bin" / "vite"
    if not vite_bin.exists():
        raise FileNotFoundError(f"vite not found: {vite_bin}")
    subprocess.run([vite_bin.as_posix(), "build"], cwd=frontend_dir, check=True)
    return frontend_dir / "dist"


def build_web_ui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="py-twins web-ui", add_help=True)
    parser.add_argument("--cwd", default=Path.cwd().as_posix(), help="Workspace directory for coding tools")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port")
    parser.add_argument("--session-dir", default=None, help="Optional session storage directory")
    parser.add_argument("--resume", action="store_true", help="Resume the most recent session instead of starting fresh")
    parser.add_argument("--agent-dir", default=None, help="Optional agent resource directory")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible base URL")
    parser.add_argument("--api-key", default=None, help="API key for the backend model")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name")
    parser.add_argument("--provider", default="openai", help="Provider name")
    parser.add_argument("--api", default="openai-completions", help="Backend API type")
    parser.add_argument("--thinking-level", default="off", help="Initial thinking level")
    parser.add_argument("--system-prompt", default="", help="Optional system prompt override")
    parser.add_argument("--no-tools", action="store_true", help="Disable local coding tools")
    parser.add_argument("--skill", action="append", default=[], help="Additional skill directory or markdown file")
    parser.add_argument("--no-skills", action="store_true", help="Disable skill discovery for web-ui sessions")
    parser.add_argument("--frontend-dir", default=None, help="Existing built frontend directory")
    parser.add_argument("--build-frontend", action="store_true", help="Build the frontend before serving")
    return parser


def web_ui_main(argv: list[str] | None = None) -> int:
    parser = build_web_ui_parser()
    args = parser.parse_args(argv)

    static_dir = args.frontend_dir
    if args.build_frontend:
        static_dir = build_web_ui_frontend().as_posix()

    config = WebUiBridgeConfig(
        cwd=args.cwd,
        session_dir=args.session_dir,
        resume_session=bool(args.resume),
        agent_dir=args.agent_dir,
        provider=args.provider,
        api=args.api,
        model_name=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        system_prompt=args.system_prompt,
        thinking_level=args.thinking_level,
        with_tools=not args.no_tools,
        no_skills=bool(args.no_skills),
        additional_skill_paths=list(args.skill or []),
    )

    server = create_web_ui_server(config, host=args.host, port=args.port, static_dir=static_dir)
    address = f"http://{args.host}:{args.port}"
    print(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(web_ui_main())
