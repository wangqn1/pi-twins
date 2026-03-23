# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent import Agent
from coding_agent.core.tools import ToolExecutionError, ToolRegistry, create_coding_tools
from coding_agent.main import coding_agent_main
from web_ui import web_ui_main

PACKAGE_NAMES = ("ai", "agent", "coding_agent", "tui", "web_ui")
MODULE_ENTRYPOINTS = {
    "coding-agent": coding_agent_main,
    "web-ui": web_ui_main,
}
CORE_CHECKS = {
    "ai": [
        "__init__.py",
        "types.py",
        "backend.py",
        "api_registry.py",
        "stream.py",
        "event_stream.py",
        "env_api_keys.py",
        "models.py",
        "overflow.py",
        "providers/__init__.py",
        "providers/simple_options.py",
        "providers/retry.py",
        "providers/openai_completions.py",
        "providers/anthropic.py",
        "providers/register_builtins.py",
    ],
    "agent": ["__init__.py", "types.py", "loop.py", "agent.py"],
    "coding_agent": [
        "__init__.py",
        "main.py",
        "cli/__init__.py",
        "cli/args.py",
        "cli/list_models.py",
        "cli/session_picker.py",
        "core/__init__.py",
        "core/messages.py",
        "core/session_manager.py",
        "core/tools/__init__.py",
        "core/model_registry.py",
        "core/agent_session.py",
        "core/compaction.py",
        "core/sdk.py",
        "core/workspace.py",
        "modes/print_mode.py",
        "modes/interactive/interactive_mode.py",
        "modes/rpc/rpc_mode.py",
    ],
    "tui": ["__init__.py"],
    "web_ui": ["__init__.py"],
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="py-twins", description="Local AI coding tools, agent sessions, and web UI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-tools", help="List all available tools")
    subparsers.add_parser("list-packages", help="List package-aligned modules")
    subparsers.add_parser("docs-index", help="Show feature documents index path")
    subparsers.add_parser("parity-check", help="Check core modules and built-in tools")

    tool_parser = subparsers.add_parser("tool", help="Run a tool with JSON input")
    tool_parser.add_argument("name", help="Tool name")
    tool_parser.add_argument("--input", required=True, help="Tool input JSON object")
    tool_parser.add_argument("--cwd", default=Path.cwd().as_posix(), help="Working directory")

    agent_parser = subparsers.add_parser("agent", help="Run one local agent turn")
    agent_parser.add_argument("--message", required=True, help="Prompt text")
    agent_parser.add_argument("--cwd", default=Path.cwd().as_posix(), help="Working directory")

    subparsers.add_parser("coding-agent", help="Run coding-agent text/json/rpc modes")
    subparsers.add_parser("web-ui", help="Serve the browser UI against the local Python engine")

    return parser


def _load_json_object(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolExecutionError(f"Invalid JSON input: {exc}") from exc
    if not isinstance(payload, dict):
        raise ToolExecutionError("Input must be a JSON object")
    return payload


def _run_list_tools() -> int:
    registry = ToolRegistry(Path.cwd().as_posix())
    print("\n".join(registry.list_tools()))
    return 0


def _run_list_packages() -> int:
    root_dir = Path(__file__).resolve().parent
    packages = sorted(path.name for path in root_dir.iterdir() if path.is_dir() and path.name in PACKAGE_NAMES)
    print("\n".join(packages))
    return 0


def _run_docs_index() -> int:
    docs_path = Path(__file__).resolve().parents[1] / "docs" / "01_feature_documents_index.md"
    print(str(docs_path))
    return 0


def _run_parity_check() -> int:
    root = Path(__file__).resolve().parents[1]
    twin_packages_dir = root / "src"
    twin_packages = sorted(
        path.name
        for path in twin_packages_dir.iterdir()
        if path.is_dir() and not path.name.startswith("__") and path.name in PACKAGE_NAMES
    )

    files_missing: dict[str, list[str]] = {}
    for package_name, required_files in CORE_CHECKS.items():
        package_dir = twin_packages_dir / package_name
        current_missing = [file_name for file_name in required_files if not (package_dir / file_name).exists()]
        if current_missing:
            files_missing[package_name] = current_missing

    tools_expected = {"read", "write", "edit", "bash", "grep", "find", "ls"}
    tools_actual = set(ToolRegistry(Path.cwd().as_posix()).list_tools())
    tools_missing = sorted(tools_expected - tools_actual)
    tools_extra = sorted(tools_actual - tools_expected)

    report = {
        "ok": not files_missing and not tools_missing,
        "twinPackages": twin_packages,
        "missingCoreFiles": files_missing,
        "toolParity": {
            "expected": sorted(tools_expected),
            "actual": sorted(tools_actual),
            "missing": tools_missing,
            "extra": tools_extra,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def _run_tool(name: str, payload: dict[str, Any], cwd: str) -> int:
    registry = ToolRegistry(cwd)
    result = registry.run(name, payload)
    print(json.dumps({"ok": True, "tool": name, "result": result.to_dict()}, ensure_ascii=False, indent=2))
    return 0


def _run_agent(message: str, cwd: str) -> int:
    agent = Agent()
    agent.set_tools(create_coding_tools(cwd))
    agent.prompt(message)
    last = next((msg for msg in reversed(agent.state.messages) if getattr(msg, "role", None) == "assistant"), None)
    if last is None:
        print(json.dumps({"ok": False, "error": "No assistant response"}, ensure_ascii=False, indent=2))
        return 1
    payload = last.to_dict() if hasattr(last, "to_dict") else last
    print(json.dumps({"ok": True, "assistant": payload}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] in MODULE_ENTRYPOINTS:
        return MODULE_ENTRYPOINTS[raw_argv[0]](raw_argv[1:])

    parser = _build_parser()
    args = parser.parse_args(raw_argv)

    try:
        if args.command == "list-tools":
            return _run_list_tools()
        if args.command == "list-packages":
            return _run_list_packages()
        if args.command == "docs-index":
            return _run_docs_index()
        if args.command == "parity-check":
            return _run_parity_check()
        if args.command == "tool":
            payload = _load_json_object(args.input)
            return _run_tool(args.name, payload, args.cwd)
        if args.command == "agent":
            return _run_agent(args.message, args.cwd)
    except (ToolExecutionError, KeyError, RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
