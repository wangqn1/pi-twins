from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import resources
from typing import Callable, Iterable

from .config import add_pod, get_active_pod, load_config, remove_pod, save_config, set_active_pod
from .model_configs import ModelSelection, get_model_config, get_model_name, is_known_model
from .ssh import SSHResult, parse_ssh_command, scp_file, ssh_exec, ssh_exec_stream
from .types import GPU, Pod, PodModel, VLLMVersion


class PodsCommandError(RuntimeError):
    pass


@dataclass
class SetupPodOptions:
    mount: str | None = None
    models_path: str | None = None
    vllm: VLLMVersion = "release"


@dataclass
class StartModelOptions:
    pod: str | None = None
    vllm_args: list[str] = field(default_factory=list)
    memory: str | None = None
    context: str | None = None
    gpus: int | None = None


@dataclass
class PromptOptions:
    pod: str | None = None
    api_key: str | None = None
    cwd: str | None = None


def _get_pod(pod_override: str | None = None, config_dir: str | None = None) -> tuple[str, Pod]:
    if pod_override is not None:
        config = load_config(config_dir)
        pod = config.pods.get(pod_override)
        if pod is None:
            raise PodsCommandError(f"Pod '{pod_override}' not found")
        return pod_override, pod

    active = get_active_pod(config_dir)
    if active is None:
        raise PodsCommandError("No active pod. Use 'pi-mono-py pods active <name>' to set one.")
    return active


def _extract_models_path(mount: str | None, models_path: str | None) -> str | None:
    if models_path:
        return models_path
    if not mount:
        return None
    parts = mount.strip().split(" ")
    if not parts:
        return None
    last = parts[-1]
    return last if last.startswith("/") else None


def _extract_host(ssh_cmd: str) -> str:
    parsed = parse_ssh_command(ssh_cmd)
    return parsed.host.split("@")[-1]


def _remove_option(args: list[str], option: str) -> list[str]:
    result: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == option:
            i += 2
            continue
        result.append(args[i])
        i += 1
    return result


def _parse_gpu_csv(stdout: str) -> list[GPU]:
    gpus: list[GPU] = []
    for line in stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            gpu_id = int(parts[0])
        except ValueError:
            continue
        gpus.append(GPU(id=gpu_id, name=parts[1], memory=parts[2]))
    return gpus


def list_pods(config_dir: str | None = None) -> list[dict[str, object]]:
    config = load_config(config_dir)
    summaries: list[dict[str, object]] = []
    for name in sorted(config.pods.keys()):
        pod = config.pods[name]
        summaries.append(
            {
                "name": name,
                "active": config.active == name,
                "ssh": pod.ssh,
                "gpuCount": len(pod.gpus),
                "gpuName": pod.gpus[0].name if pod.gpus else None,
                "modelsPath": pod.models_path,
                "vllmVersion": pod.vllm_version,
            }
        )
    return summaries


def setup_pod(
    name: str,
    ssh_cmd: str,
    options: SetupPodOptions,
    *,
    config_dir: str | None = None,
    hf_token: str | None = None,
    api_key: str | None = None,
    ssh_exec_fn: Callable[..., SSHResult] = ssh_exec,
    ssh_exec_stream_fn: Callable[..., int] = ssh_exec_stream,
    scp_file_fn: Callable[[str, str, str], bool] = scp_file,
) -> dict[str, object]:
    resolved_hf_token = hf_token or os.environ.get("HF_TOKEN")
    resolved_api_key = api_key or os.environ.get("PI_API_KEY")
    if not resolved_hf_token:
        raise PodsCommandError("HF_TOKEN environment variable is required")
    if not resolved_api_key:
        raise PodsCommandError("PI_API_KEY environment variable is required")

    models_path = _extract_models_path(options.mount, options.models_path)
    if not models_path:
        raise PodsCommandError("--models-path is required (or must be extractable from --mount)")

    test_result = ssh_exec_fn(ssh_cmd, "echo 'SSH OK'")
    if test_result.exit_code != 0:
        raise PodsCommandError(test_result.stderr or "Failed to connect via SSH")

    script_ref = resources.files("pods").joinpath("scripts", "pod_setup.sh")
    with resources.as_file(script_ref) as setup_script:
        if not scp_file_fn(ssh_cmd, str(setup_script), "/tmp/pod_setup.sh"):
            raise PodsCommandError("Failed to copy setup script")

    setup_cmd = (
        f"bash /tmp/pod_setup.sh --models-path '{models_path}' --hf-token '{resolved_hf_token}' "
        f"--vllm-api-key '{resolved_api_key}' --vllm '{options.vllm}'"
    )
    if options.mount:
        setup_cmd += f" --mount '{options.mount}'"

    exit_code = ssh_exec_stream_fn(ssh_cmd, setup_cmd, force_tty=True)
    if exit_code != 0:
        raise PodsCommandError("Setup failed")

    gpu_result = ssh_exec_fn(ssh_cmd, "nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader")
    gpus = _parse_gpu_csv(gpu_result.stdout) if gpu_result.exit_code == 0 else []

    pod = Pod(
        ssh=ssh_cmd,
        gpus=gpus,
        models={},
        models_path=models_path,
        vllm_version=options.vllm,
    )
    add_pod(name, pod, config_dir)
    return {
        "name": name,
        "ssh": ssh_cmd,
        "modelsPath": models_path,
        "vllmVersion": options.vllm,
        "gpus": gpus,
    }


def switch_active_pod(name: str, config_dir: str | None = None) -> str:
    set_active_pod(name, config_dir)
    return name


def remove_pod_command(name: str, config_dir: str | None = None) -> str:
    config = load_config(config_dir)
    if name not in config.pods:
        raise PodsCommandError(f"Pod '{name}' not found")
    remove_pod(name, config_dir)
    return name


def get_next_port(pod: Pod) -> int:
    used_ports = {model.port for model in pod.models.values()}
    port = 8001
    while port in used_ports:
        port += 1
    return port


def select_gpus(pod: Pod, count: int = 1) -> list[int]:
    if count <= 0:
        return []
    if count == len(pod.gpus):
        return [gpu.id for gpu in pod.gpus]

    gpu_usage = {gpu.id: 0 for gpu in pod.gpus}
    for model in pod.models.values():
        for gpu_id in model.gpu:
            gpu_usage[gpu_id] = gpu_usage.get(gpu_id, 0) + 1
    return [gpu_id for gpu_id, _ in sorted(gpu_usage.items(), key=lambda item: item[1])[:count]]


def _apply_model_overrides(args: list[str], memory: str | None, context: str | None) -> list[str]:
    updated = list(args)
    if memory:
        updated = _remove_option(updated, "--gpu-memory-utilization")
        fraction = parse_float_percent(memory)
        updated.extend(["--gpu-memory-utilization", str(fraction)])
    if context:
        updated = _remove_option(updated, "--max-model-len")
        updated.extend(["--max-model-len", str(parse_context_window(context))])
    return updated


def parse_float_percent(value: str) -> float:
    return float(value.replace("%", "")) / 100.0


def parse_context_window(value: str) -> int:
    lookup = {
        "4k": 4096,
        "8k": 8192,
        "16k": 16384,
        "32k": 32768,
        "64k": 65536,
        "128k": 131072,
    }
    lowered = value.lower()
    if lowered in lookup:
        return lookup[lowered]
    return int(value)


def _render_model_run_script(model_id: str, name: str, port: int, vllm_args: Iterable[str]) -> str:
    template = resources.files("pods").joinpath("scripts", "model_run.sh").read_text(encoding="utf-8")
    return (
        template.replace("{{MODEL_ID}}", model_id)
        .replace("{{NAME}}", name)
        .replace("{{PORT}}", str(port))
        .replace("{{VLLM_ARGS}}", " ".join(vllm_args))
    )


def start_model(
    model_id: str,
    name: str,
    options: StartModelOptions | None = None,
    *,
    config_dir: str | None = None,
    ssh_exec_fn: Callable[..., SSHResult] = ssh_exec,
) -> dict[str, object]:
    opts = options or StartModelOptions()
    pod_name, pod = _get_pod(opts.pod, config_dir)

    if not pod.models_path:
        raise PodsCommandError("Pod does not have a models path configured")
    if name in pod.models:
        raise PodsCommandError(f"Model '{name}' already exists on pod '{pod_name}'")

    port = get_next_port(pod)
    model_selection: ModelSelection | None = None
    gpu_ids: list[int] = []
    vllm_args: list[str] = list(opts.vllm_args)

    if vllm_args:
        gpu_ids = []
    elif is_known_model(model_id):
        if opts.gpus is not None:
            if opts.gpus > len(pod.gpus):
                raise PodsCommandError(f"Requested {opts.gpus} GPUs but pod only has {len(pod.gpus)}")
            model_selection = get_model_config(model_id, pod.gpus, opts.gpus)
            if model_selection is None:
                raise PodsCommandError(f"Model '{get_model_name(model_id)}' does not have a configuration for {opts.gpus} GPU(s)")
            gpu_ids = select_gpus(pod, opts.gpus)
            vllm_args = list(model_selection.args)
        else:
            for gpu_count in range(len(pod.gpus), 0, -1):
                model_selection = get_model_config(model_id, pod.gpus, gpu_count)
                if model_selection is not None:
                    gpu_ids = select_gpus(pod, gpu_count)
                    vllm_args = list(model_selection.args)
                    break
            if model_selection is None:
                raise PodsCommandError(f"Model '{get_model_name(model_id)}' not compatible with this pod's GPUs")
    else:
        if opts.gpus is not None:
            raise PodsCommandError("--gpus can only be used with predefined models")
        gpu_ids = select_gpus(pod, 1)

    if not opts.vllm_args:
        vllm_args = _apply_model_overrides(vllm_args, opts.memory, opts.context)

    rendered_script = _render_model_run_script(model_id, name, port, vllm_args)
    upload_script_cmd = (
        f"cat > /tmp/model_run_{name}.sh << 'EOF'\n{rendered_script}\nEOF\nchmod +x /tmp/model_run_{name}.sh"
    )
    upload_result = ssh_exec_fn(pod.ssh, upload_script_cmd)
    if upload_result.exit_code != 0:
        raise PodsCommandError(upload_result.stderr or "Failed to upload model runner script")

    env_lines = [
        f"export HF_TOKEN='{os.environ.get('HF_TOKEN', '')}'",
        f"export PI_API_KEY='{os.environ.get('PI_API_KEY', '')}'",
        "export HF_HUB_ENABLE_HF_TRANSFER=1",
        "export VLLM_NO_USAGE_STATS=1",
        "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True",
        "export FORCE_COLOR=1",
        "export TERM=xterm-256color",
    ]
    if len(gpu_ids) == 1:
        env_lines.append(f"export CUDA_VISIBLE_DEVICES={gpu_ids[0]}")
    if model_selection and model_selection.env:
        env_lines.extend(f"export {key}='{value}'" for key, value in model_selection.env.items())

    start_cmd = f"""
{os.linesep.join(env_lines)}
mkdir -p ~/.vllm_logs
cat > /tmp/model_wrapper_{name}.sh << 'WRAPPER'
#!/bin/bash
script -q -f -c "/tmp/model_run_{name}.sh" ~/.vllm_logs/{name}.log
exit_code=$?
echo "Script exited with code $exit_code" >> ~/.vllm_logs/{name}.log
exit $exit_code
WRAPPER
chmod +x /tmp/model_wrapper_{name}.sh
setsid /tmp/model_wrapper_{name}.sh </dev/null >/dev/null 2>&1 &
echo $!
exit 0
""".strip()
    pid_result = ssh_exec_fn(pod.ssh, start_cmd)
    if pid_result.exit_code != 0:
        raise PodsCommandError(pid_result.stderr or "Failed to start model runner")
    try:
        pid = int(pid_result.stdout.strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        raise PodsCommandError(f"Failed to parse model PID: {pid_result.stdout!r}") from exc

    config = load_config(config_dir)
    config.pods[pod_name].models[name] = PodModel(model=model_id, port=port, gpu=gpu_ids, pid=pid)
    save_config(config, config_dir)

    return {
        "pod": pod_name,
        "name": name,
        "model": model_id,
        "port": port,
        "pid": pid,
        "gpus": gpu_ids,
        "host": _extract_host(pod.ssh),
        "vllmArgs": vllm_args,
        "notes": model_selection.notes if model_selection else None,
    }


def stop_model(name: str, *, pod: str | None = None, config_dir: str | None = None, ssh_exec_fn: Callable[..., SSHResult] = ssh_exec) -> str:
    pod_name, resolved_pod = _get_pod(pod, config_dir)
    model = resolved_pod.models.get(name)
    if model is None:
        raise PodsCommandError(f"Model '{name}' not found on pod '{pod_name}'")

    kill_cmd = f"""
pkill -TERM -P {model.pid} 2>/dev/null || true
kill {model.pid} 2>/dev/null || true
""".strip()
    ssh_exec_fn(resolved_pod.ssh, kill_cmd)

    config = load_config(config_dir)
    del config.pods[pod_name].models[name]
    save_config(config, config_dir)
    return name


def stop_all_models(*, pod: str | None = None, config_dir: str | None = None, ssh_exec_fn: Callable[..., SSHResult] = ssh_exec) -> list[str]:
    pod_name, resolved_pod = _get_pod(pod, config_dir)
    names = sorted(resolved_pod.models.keys())
    if not names:
        return []
    pids = [str(model.pid) for model in resolved_pod.models.values()]
    kill_cmd = "for PID in " + " ".join(pids) + "; do\npkill -TERM -P $PID 2>/dev/null || true\nkill $PID 2>/dev/null || true\ndone"
    ssh_exec_fn(resolved_pod.ssh, kill_cmd)

    config = load_config(config_dir)
    config.pods[pod_name].models = {}
    save_config(config, config_dir)
    return names


def list_models(
    *,
    pod: str | None = None,
    config_dir: str | None = None,
    verify: bool = False,
    ssh_exec_fn: Callable[..., SSHResult] = ssh_exec,
) -> list[dict[str, object]]:
    pod_name, resolved_pod = _get_pod(pod, config_dir)
    host = _extract_host(resolved_pod.ssh)
    results: list[dict[str, object]] = []
    for name in sorted(resolved_pod.models.keys()):
        model = resolved_pod.models[name]
        item: dict[str, object] = {
            "pod": pod_name,
            "name": name,
            "model": model.model,
            "port": model.port,
            "pid": model.pid,
            "gpu": list(model.gpu),
            "url": f"http://{host}:{model.port}/v1",
        }
        if verify:
            check_cmd = f"""
if ps -p {model.pid} > /dev/null 2>&1; then
  if curl -s -f http://localhost:{model.port}/health > /dev/null 2>&1; then
    echo running
  else
    if tail -n 20 ~/.vllm_logs/{name}.log 2>/dev/null | grep -q "ERROR\\|Failed\\|Cuda error\\|died"; then
      echo crashed
    else
      echo starting
    fi
  fi
else
  echo dead
fi
""".strip()
            status_result = ssh_exec_fn(resolved_pod.ssh, check_cmd)
            item["status"] = status_result.stdout.strip() if status_result.exit_code == 0 else "unknown"
        results.append(item)
    return results


def view_logs(name: str, *, pod: str | None = None, config_dir: str | None = None, ssh_exec_stream_fn: Callable[..., int] = ssh_exec_stream) -> int:
    pod_name, resolved_pod = _get_pod(pod, config_dir)
    if name not in resolved_pod.models:
        raise PodsCommandError(f"Model '{name}' not found on pod '{pod_name}'")
    return ssh_exec_stream_fn(resolved_pod.ssh, f"tail -f ~/.vllm_logs/{name}.log")


def build_prompt_agent_args(
    model_name: str,
    user_args: list[str],
    opts: PromptOptions | None = None,
    *,
    config_dir: str | None = None,
) -> list[str]:
    options = opts or PromptOptions()
    pod_name, pod = _get_pod(options.pod, config_dir)
    model_config = pod.models.get(model_name)
    if model_config is None:
        raise PodsCommandError(f"Model '{model_name}' not found on pod '{pod_name}'")

    host = _extract_host(pod.ssh)
    api_type = "responses" if "gpt-oss" in model_config.model.lower() else "completions"
    cwd = options.cwd or os.getcwd()
    system_prompt = (
        "You help the user understand and navigate the codebase in the current working directory.\n\n"
        "You can read files, list directories, and execute shell commands via the respective tools.\n\n"
        "Do not output file contents you read via the read_file tool directly, unless asked to.\n\n"
        "Do not output markdown tables as part of your responses.\n\n"
        "Keep your responses concise and relevant to the user's request.\n\n"
        'File paths you output must include line numbers where possible, e.g. "src/index.ts:10-20".\n\n'
        f"Current working directory: {cwd}"
    )

    return [
        "--base-url",
        f"http://{host}:{model_config.port}/v1",
        "--model",
        model_config.model,
        "--api-key",
        options.api_key or os.environ.get("PI_API_KEY") or "dummy",
        "--api",
        api_type,
        "--system-prompt",
        system_prompt,
        *user_args,
    ]
