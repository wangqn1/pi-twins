# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass, field
import argparse
from pathlib import Path


@dataclass
class CodingAgentArgs:
    mode: str = "text"
    print_mode: bool = False
    cwd: str = field(default_factory=lambda: Path.cwd().as_posix())
    workspace: str | None = None
    agent_dir: str | None = None
    provider: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    append_system_prompt: str | None = None
    thinking: str | None = None
    continue_session: bool = False
    resume: bool = False
    session: str | None = None
    session_dir: str | None = None
    export: str | None = None
    list_models: str | bool | None = None
    no_session: bool = False
    extensions: list[str] = field(default_factory=list)
    no_extensions: bool = False
    skills: list[str] = field(default_factory=list)
    no_skills: bool = False
    prompt_templates: list[str] = field(default_factory=list)
    no_prompt_templates: bool = False
    messages: list[str] = field(default_factory=list)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="py-twins coding-agent", add_help=True)
    parser.add_argument("messages", nargs="*", help="Prompt messages")
    parser.add_argument("--mode", choices=("text", "json", "rpc"), default="text")
    parser.add_argument("--print", "-p", dest="print_mode", action="store_true", help="Run one-shot print mode")
    parser.add_argument("--cwd", default=Path.cwd().as_posix())
    parser.add_argument("--workspace")
    parser.add_argument("--agent-dir")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--system-prompt")
    parser.add_argument("--append-system-prompt")
    parser.add_argument("--thinking")
    parser.add_argument("--continue", "-c", dest="continue_session", action="store_true")
    parser.add_argument("--resume", "-r", action="store_true")
    parser.add_argument("--session")
    parser.add_argument("--session-dir")
    parser.add_argument("--export")
    parser.add_argument("--list-models", nargs="?", const=True, default=None)
    parser.add_argument("--no-session", action="store_true")
    parser.add_argument("--extension", "-e", action="append", default=[])
    parser.add_argument("--no-extensions", action="store_true")
    parser.add_argument("--skill", action="append", default=[])
    parser.add_argument("--no-skills", action="store_true")
    parser.add_argument("--prompt-template", action="append", default=[])
    parser.add_argument("--no-prompt-templates", action="store_true")
    return parser


def parse_args(argv: list[str] | None = None) -> CodingAgentArgs:
    parser = build_parser()
    namespace = parser.parse_args(argv)
    return CodingAgentArgs(
        mode=namespace.mode,
        print_mode=bool(namespace.print_mode),
        cwd=namespace.cwd,
        workspace=namespace.workspace,
        agent_dir=namespace.agent_dir,
        provider=namespace.provider,
        model=namespace.model,
        system_prompt=namespace.system_prompt,
        append_system_prompt=namespace.append_system_prompt,
        thinking=namespace.thinking,
        continue_session=bool(namespace.continue_session),
        resume=bool(namespace.resume),
        session=namespace.session,
        session_dir=namespace.session_dir,
        export=namespace.export,
        list_models=namespace.list_models,
        no_session=bool(namespace.no_session),
        extensions=list(namespace.extension or []),
        no_extensions=bool(namespace.no_extensions),
        skills=list(namespace.skill or []),
        no_skills=bool(namespace.no_skills),
        prompt_templates=list(namespace.prompt_template or []),
        no_prompt_templates=bool(namespace.no_prompt_templates),
        messages=list(namespace.messages or []),
    )
