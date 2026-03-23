# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from coding_agent.core.workspace import resolve_session_dir, resolve_workspace_dir

from .bridge import WebUiBridgeConfig
from .server import create_web_ui_server

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
DEFAULT_BASE_URL = "http://192.168.64.22:3001/v1"
DEFAULT_MODEL = "qwen3.5-122b-vl"


def _default_frontend_root() -> Path:
    return (Path(__file__).resolve().parent / "frontend").resolve()


def build_web_ui_frontend(*, cwd: str | None = None) -> Path:
    frontend_root = Path(cwd).resolve() if cwd else _default_frontend_root()
    if frontend_root.name == "dist":
        dist_dir = frontend_root
    else:
        dist_dir = frontend_root / "dist"
    index_file = dist_dir / "index.html"
    if not index_file.exists():
        raise FileNotFoundError(f"web-ui frontend dist not found: {index_file}")
    return dist_dir


def build_web_ui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="py-twins web-ui", add_help=True)
    parser.add_argument("--cwd", default=Path.cwd().as_posix(), help="Workspace directory for coding tools")
    parser.add_argument("--workspace", default=None, help="Agent workspace directory, default is <cwd>/.pi")
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
    parser.add_argument(
        "--llm-request-log",
        default=None,
        help="Optional JSONL file path used to store final LLM request payloads sent by web-ui sessions",
    )
    parser.add_argument("--frontend-dir", default=None, help="Existing built frontend dist directory")
    parser.add_argument(
        "--build-frontend",
        action="store_true",
        help="Use the bundled frontend dist directory before serving",
    )
    return parser


def web_ui_main(argv: list[str] | None = None) -> int:
    parser = build_web_ui_parser()
    args = parser.parse_args(argv)
    resolved_cwd = Path(args.cwd).resolve().as_posix()
    resolved_agent_dir = (
        Path(args.agent_dir).expanduser().resolve().as_posix()
        if args.agent_dir
        else resolve_workspace_dir(resolved_cwd, args.workspace)
    )
    resolved_session_dir = resolve_session_dir(resolved_cwd, args.session_dir, resolved_agent_dir)

    static_dir = args.frontend_dir
    if args.build_frontend:
        static_dir = build_web_ui_frontend().as_posix()

    config = WebUiBridgeConfig(
        cwd=resolved_cwd,
        workspace=args.workspace,
        session_dir=resolved_session_dir,
        resume_session=bool(args.resume),
        agent_dir=resolved_agent_dir,
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
        llm_request_log_path=args.llm_request_log,
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
