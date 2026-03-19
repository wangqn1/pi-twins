from __future__ import annotations

import argparse
import json
from typing import Any

from .commands import (
    PodsCommandError,
    PromptOptions,
    SetupPodOptions,
    StartModelOptions,
    build_prompt_agent_args,
    list_models,
    list_pods,
    remove_pod_command,
    setup_pod,
    start_model,
    stop_all_models,
    stop_model,
    switch_active_pod,
    view_logs,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pi-mono-py pods", description="Manage vLLM deployments on GPU pods")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    subparsers.add_parser("list", help="List configured pods")

    active_parser = subparsers.add_parser("active", help="Switch active pod")
    active_parser.add_argument("name")

    remove_parser = subparsers.add_parser("remove", help="Remove a pod from local config")
    remove_parser.add_argument("name")

    setup_parser = subparsers.add_parser("setup", help="Setup a new pod")
    setup_parser.add_argument("name")
    setup_parser.add_argument("ssh")
    setup_parser.add_argument("--mount")
    setup_parser.add_argument("--models-path")
    setup_parser.add_argument("--vllm", default="release", choices=["release", "nightly", "gpt-oss"])

    start_parser = subparsers.add_parser("start", help="Start a model")
    start_parser.add_argument("model")
    start_parser.add_argument("--name", required=True)
    start_parser.add_argument("--pod")
    start_parser.add_argument("--memory")
    start_parser.add_argument("--context")
    start_parser.add_argument("--gpus", type=int)
    start_parser.add_argument("--vllm", nargs=argparse.REMAINDER, default=[])

    stop_parser = subparsers.add_parser("stop", help="Stop one model or all")
    stop_parser.add_argument("name", nargs="?")
    stop_parser.add_argument("--all", action="store_true")
    stop_parser.add_argument("--pod")

    models_parser = subparsers.add_parser("models", help="List running models")
    models_parser.add_argument("--pod")
    models_parser.add_argument("--verify", action="store_true")

    logs_parser = subparsers.add_parser("logs", help="Stream model logs")
    logs_parser.add_argument("name")
    logs_parser.add_argument("--pod")

    prompt_parser = subparsers.add_parser("prompt-args", help="Build agent args for a deployed model")
    prompt_parser.add_argument("name")
    prompt_parser.add_argument("user_args", nargs="*")
    prompt_parser.add_argument("--pod")
    prompt_parser.add_argument("--api-key")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.subcommand == "list":
            print(json.dumps(list_pods(), ensure_ascii=False, indent=2))
            return 0
        if args.subcommand == "active":
            print(json.dumps({"active": switch_active_pod(args.name)}, ensure_ascii=False, indent=2))
            return 0
        if args.subcommand == "remove":
            print(json.dumps({"removed": remove_pod_command(args.name)}, ensure_ascii=False, indent=2))
            return 0
        if args.subcommand == "setup":
            result = setup_pod(args.name, args.ssh, SetupPodOptions(mount=args.mount, models_path=args.models_path, vllm=args.vllm))
            print(json.dumps(result, ensure_ascii=False, indent=2, default=lambda obj: obj.__dict__))
            return 0
        if args.subcommand == "start":
            result = start_model(
                args.model,
                args.name,
                StartModelOptions(
                    pod=args.pod,
                    vllm_args=list(args.vllm),
                    memory=args.memory,
                    context=args.context,
                    gpus=args.gpus,
                ),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.subcommand == "stop":
            if args.all:
                print(json.dumps({"stopped": stop_all_models(pod=args.pod)}, ensure_ascii=False, indent=2))
            elif args.name:
                print(json.dumps({"stopped": stop_model(args.name, pod=args.pod)}, ensure_ascii=False, indent=2))
            else:
                raise PodsCommandError("Provide a model name or use --all")
            return 0
        if args.subcommand == "models":
            print(json.dumps(list_models(pod=args.pod, verify=args.verify), ensure_ascii=False, indent=2))
            return 0
        if args.subcommand == "logs":
            return view_logs(args.name, pod=args.pod)
        if args.subcommand == "prompt-args":
            result = build_prompt_agent_args(args.name, list(args.user_args), PromptOptions(pod=args.pod, api_key=args.api_key))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
    except PodsCommandError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    parser.error("Unknown pods subcommand")
    return 2
