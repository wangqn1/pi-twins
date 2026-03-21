from __future__ import annotations
from web_ui.example_app import WebUiExampleConfig, WebUiStyleExampleApp

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.as_posix() not in sys.path:
    sys.path.insert(0, SRC.as_posix())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a web-ui style py-twins example session")
    parser.add_argument("--cwd", default=ROOT.as_posix())
    parser.add_argument("--session-dir")
    parser.add_argument("--prompt", default="Reply with exactly OK.")
    parser.add_argument("--export")
    parser.add_argument("--no-tools", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = WebUiExampleConfig.from_env(
        cwd=Path(args.cwd).resolve().as_posix(),
        session_dir=args.session_dir,
        with_tools=not args.no_tools,
    )
    if not config.api_key:
        print(json.dumps(
            {"ok": False, "error": "Missing env: LLM_API_KEY"}, ensure_ascii=False, indent=2))
        return 1

    app = WebUiStyleExampleApp.create(config)
    reply = app.send(args.prompt)
    payload = app.snapshot()
    payload["reply"] = reply
    if args.export:
        payload["exportedHtml"] = app.export_html(args.export)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
