from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from ai import Model

from .cli.args import CodingAgentArgs, parse_args
from .cli.list_models import render_models
from .cli.session_picker import select_session_path
from .core.model_registry import ModelRegistry
from .core.package_manager import DefaultPackageManager, render_config_snapshot, render_package_list
from .core.resource_loader import DefaultResourceLoader, DefaultResourceLoaderOptions
from .core.sdk import CreateAgentSessionOptions, create_agent_session
from .core.session_manager import SessionManager
from .core.settings_manager import SettingsManager
from .core.workspace import resolve_session_dir, resolve_workspace_dir
from .modes.interactive.interactive_mode import run_interactive_mode
from .modes.print_mode import run_print_mode
from .modes.rpc.rpc_mode import run_rpc_mode


def coding_agent_main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    in_stream = stdin or sys.stdin
    out_stream = stdout or sys.stdout
    err_stream = stderr or sys.stderr
    raw_argv = list(argv or [])
    cwd, agent_dir, command_argv = _extract_global_cli_context(raw_argv)

    package_handled = _handle_package_command(
        command_argv,
        cwd=cwd,
        agent_dir=agent_dir,
        stdout=out_stream,
        stderr=err_stream,
    )
    if package_handled is not None:
        return package_handled

    args = parse_args(raw_argv)
    resolved_cwd = Path(args.cwd).resolve().as_posix()
    resolved_agent_dir = _resolve_agent_dir(resolved_cwd, args)
    settings_manager = SettingsManager.create(resolved_cwd, resolved_agent_dir)

    if args.list_models is not None:
        search_pattern = args.list_models if isinstance(args.list_models, str) else None
        out_stream.write(f"{render_models(_create_model_registry(args, settings_manager), search_pattern)}\n")
        return 0

    if args.resume and not args.session:
        selected = select_session_path(
            cwd=resolved_cwd,
            session_dir=resolve_session_dir(resolved_cwd, args.session_dir, resolved_agent_dir),
            stdin=in_stream,
            stdout=out_stream,
            stderr=err_stream,
        )
        if selected is None:
            return 1
        args.session = selected

    session = _create_session(args, settings_manager=settings_manager)

    if args.mode == "rpc":
        return run_rpc_mode(session, stdin=in_stream, stdout=out_stream)

    messages = list(args.messages)
    if not messages and not in_stream.isatty():
        piped = in_stream.read().strip()
        if piped:
            messages.append(piped)

    if args.print_mode and not messages:
        err_stream.write("No input provided for print mode.\n")
        return 1

    if messages:
        mode = "json" if args.mode == "json" else "text"
        code = run_print_mode(session, mode=mode, messages=messages, stdout=out_stream, stderr=err_stream)
        if code != 0:
            return code
        if args.export:
            out_stream.write(f"{session.export_to_html(args.export)}\n")
        return 0

    if args.mode == "json":
        err_stream.write("JSON mode requires at least one input message.\n")
        return 1

    if args.export:
        out_stream.write(f"{session.export_to_html(args.export)}\n")
        return 0

    return run_interactive_mode(session, stdin=in_stream, stdout=out_stream, stderr=err_stream)


def _create_session(args: CodingAgentArgs, *, settings_manager: SettingsManager | None = None):
    cwd = Path(args.cwd).resolve().as_posix()
    agent_dir = _resolve_agent_dir(cwd, args)
    settings_manager = settings_manager or SettingsManager.create(cwd, agent_dir)
    resource_loader = DefaultResourceLoader(
        DefaultResourceLoaderOptions(
            cwd=cwd,
            agent_dir=agent_dir,
            settings_manager=settings_manager,
            additional_extension_paths=args.extensions,
            additional_skill_paths=args.skills,
            additional_prompt_template_paths=args.prompt_templates,
            system_prompt=args.system_prompt,
            append_system_prompt=args.append_system_prompt,
            no_extensions=args.no_extensions,
            no_skills=args.no_skills,
            no_prompt_templates=args.no_prompt_templates,
        )
    )
    session_manager = _create_session_manager(cwd, args)

    return create_agent_session(
        CreateAgentSessionOptions(
            cwd=cwd,
            agent_dir=agent_dir,
            model=_resolve_model(args, settings_manager),
            session_manager=session_manager,
            settings_manager=settings_manager,
            resource_loader=resource_loader,
            system_prompt=args.system_prompt or "",
            append_system_prompt=args.append_system_prompt,
            thinking_level=args.thinking,
        )
    )


def _create_session_manager(cwd: str, args: CodingAgentArgs) -> SessionManager:
    if args.no_session:
        return SessionManager.in_memory(cwd)
    manager = SessionManager.continue_recent(cwd, session_dir=resolve_session_dir(cwd, args.session_dir, _resolve_agent_dir(cwd, args)))
    if args.session:
        manager.set_session_file(args.session)
    return manager


def _resolve_model(args: CodingAgentArgs, settings_manager: SettingsManager) -> Model | None:
    if not args.model and not args.provider:
        return None
    if args.model and "/" in args.model:
        provider, model_id = args.model.split("/", 1)
    else:
        provider = args.provider or settings_manager.get_default_provider() or "mock"
        model_id = args.model or settings_manager.get_default_model() or "echo"
    return Model(provider=provider, id=model_id, api="mock")


def _create_model_registry(args: CodingAgentArgs, settings_manager: SettingsManager) -> ModelRegistry:
    registry = ModelRegistry()
    for reference in settings_manager.get_enabled_models():
        model = _parse_model_reference(reference, settings_manager.get_default_provider())
        if model is not None:
            registry.register_model(model)

    default_provider = settings_manager.get_default_provider()
    default_model = settings_manager.get_default_model()
    if default_model:
        registry.register_model(Model(provider=default_provider or "mock", id=default_model, api="mock"))

    resolved_model = _resolve_model(args, settings_manager)
    if resolved_model is not None:
        registry.register_model(resolved_model)
    return registry


def _parse_model_reference(reference: str, default_provider: str | None) -> Model | None:
    if not reference:
        return None
    if "/" in reference:
        provider, model_id = reference.split("/", 1)
    else:
        provider = default_provider or "mock"
        model_id = reference
    provider = provider.strip()
    model_id = model_id.strip()
    if not provider or not model_id:
        return None
    return Model(provider=provider, id=model_id, api="mock")


def _extract_global_cli_context(argv: list[str]) -> tuple[str, str, list[str]]:
    cwd = Path.cwd().resolve().as_posix()
    workspace: str | None = None
    agent_dir: str | None = None
    remaining: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--cwd" and index + 1 < len(argv):
            cwd = argv[index + 1]
            index += 2
            continue
        if value == "--workspace" and index + 1 < len(argv):
            workspace = argv[index + 1]
            index += 2
            continue
        if value == "--agent-dir" and index + 1 < len(argv):
            agent_dir = argv[index + 1]
            index += 2
            continue
        remaining.append(value)
        index += 1
    resolved_cwd = Path(cwd).resolve().as_posix()
    resolved_agent_dir = (
        Path(agent_dir).expanduser().resolve().as_posix()
        if agent_dir
        else resolve_workspace_dir(resolved_cwd, workspace)
    )
    return resolved_cwd, resolved_agent_dir, remaining


def _resolve_agent_dir(cwd: str, args: CodingAgentArgs) -> str:
    if args.agent_dir:
        return Path(args.agent_dir).expanduser().resolve().as_posix()
    return resolve_workspace_dir(cwd, args.workspace)


def _handle_package_command(
    argv: list[str],
    *,
    cwd: str,
    agent_dir: str,
    stdout: TextIO,
    stderr: TextIO,
) -> int | None:
    if not argv:
        return None
    command = argv[0]
    if command not in {"install", "remove", "update", "list", "config"}:
        return None

    settings_manager = SettingsManager.create(cwd, agent_dir)
    package_manager = DefaultPackageManager(cwd=cwd, agent_dir=agent_dir, settings_manager=settings_manager)
    args = argv[1:]

    if command == "list":
        stdout.write(f"{render_package_list(settings_manager, package_manager)}\n")
        return 0

    if command == "config":
        stdout.write(
            f"{render_config_snapshot(cwd=cwd, agent_dir=agent_dir, settings_manager=settings_manager, package_manager=package_manager)}\n"
        )
        return 0

    local = False
    source: str | None = None
    for value in args:
        if value in {"-l", "--local"}:
            local = True
            continue
        if value.startswith("-"):
            stderr.write(f"Unknown option: {value}\n")
            return 1
        if source is None:
            source = value

    if command in {"install", "remove"} and not source:
        stderr.write(f"Missing {command} source.\n")
        return 1

    try:
        if command == "install":
            package_manager.install(source or "", {"local": local})
            package_manager.add_source_to_settings(source or "", {"local": local})
            stdout.write(f"Installed {source}\n")
            return 0
        if command == "remove":
            package_manager.remove(source or "", {"local": local})
            removed = package_manager.remove_source_from_settings(source or "", {"local": local})
            if not removed:
                stderr.write(f"No matching package found for {source}\n")
                return 1
            stdout.write(f"Removed {source}\n")
            return 0
        if command == "update":
            package_manager.update(source)
            if source:
                stdout.write(f"Updated {source}\n")
            else:
                stdout.write("Updated packages\n")
            return 0
    except ValueError as exc:
        stderr.write(f"{exc}\n")
        return 1

    return None
