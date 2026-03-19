from __future__ import annotations

from pathlib import Path

from pods import (
    Config,
    GPU,
    PodsCommandError,
    Pod,
    PodModel,
    PromptOptions,
    SetupPodOptions,
    StartModelOptions,
    add_pod,
    build_prompt_agent_args,
    build_scp_command,
    build_ssh_command,
    get_active_pod,
    get_known_models,
    get_model_config,
    get_model_name,
    get_next_port,
    is_known_model,
    list_models,
    list_pods,
    load_config,
    parse_ssh_command,
    remove_pod,
    save_config,
    select_gpus,
    set_active_pod,
    setup_pod,
    start_model,
    stop_all_models,
    stop_model,
)


def test_pods_config_roundtrip_and_active_selection(tmp_path: Path) -> None:
    config = Config(
        pods={
            "dc1": Pod(
                ssh="ssh root@1.2.3.4",
                gpus=[GPU(id=0, name="NVIDIA H200", memory="141GB")],
                models={"qwen": PodModel(model="Qwen/Qwen2.5-Coder-32B-Instruct", port=8001, gpu=[0], pid=123)},
                models_path="/mnt/models",
                vllm_version="release",
            )
        },
        active="dc1",
    )
    save_config(config, tmp_path.as_posix())

    loaded = load_config(tmp_path.as_posix())
    assert loaded.active == "dc1"
    assert loaded.pods["dc1"].ssh == "ssh root@1.2.3.4"
    assert loaded.pods["dc1"].models["qwen"].port == 8001

    active = get_active_pod(tmp_path.as_posix())
    assert active is not None
    assert active[0] == "dc1"
    assert active[1].models_path == "/mnt/models"


def test_add_remove_and_switch_active_pod(tmp_path: Path) -> None:
    add_pod("one", Pod(ssh="ssh root@one"), tmp_path.as_posix())
    add_pod("two", Pod(ssh="ssh root@two"), tmp_path.as_posix())

    loaded = load_config(tmp_path.as_posix())
    assert loaded.active == "one"

    set_active_pod("two", tmp_path.as_posix())
    assert load_config(tmp_path.as_posix()).active == "two"

    remove_pod("two", tmp_path.as_posix())
    assert load_config(tmp_path.as_posix()).active is None


def test_set_active_pod_rejects_unknown_name(tmp_path: Path) -> None:
    try:
        set_active_pod("missing", tmp_path.as_posix())
    except ValueError as exc:
        assert "missing" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError for unknown pod")


def test_list_pods_reports_active_and_gpu_summary(tmp_path: Path) -> None:
    save_config(
        Config(
            pods={
                "dc1": Pod(ssh="ssh root@one", gpus=[GPU(id=0, name="NVIDIA H100", memory="80GB")]),
                "dc2": Pod(ssh="ssh root@two", gpus=[]),
            },
            active="dc2",
        ),
        tmp_path.as_posix(),
    )
    pods = list_pods(tmp_path.as_posix())
    assert [pod["name"] for pod in pods] == ["dc1", "dc2"]
    assert pods[1]["active"] is True
    assert pods[0]["gpuName"] == "NVIDIA H100"


def test_model_config_prefers_matching_gpu_type() -> None:
    selection = get_model_config(
        "Qwen/Qwen2.5-Coder-32B-Instruct",
        [GPU(id=0, name="NVIDIA H200 SXM", memory="141GB")],
        2,
    )
    assert selection is not None
    assert selection.args[:2] == ["--tensor-parallel-size", "2"]
    assert "--tool-call-parser" in selection.args


def test_model_config_falls_back_to_gpu_count_only_when_type_is_unknown() -> None:
    selection = get_model_config(
        "Qwen/Qwen2.5-Coder-32B-Instruct",
        [GPU(id=0, name="NVIDIA A100", memory="80GB")],
        1,
    )
    assert selection is not None
    assert "--enable-auto-tool-choice" in selection.args


def test_known_models_registry_uses_bundled_models_json() -> None:
    assert is_known_model("Qwen/Qwen2.5-Coder-32B-Instruct") is True
    assert is_known_model("unknown/model") is False
    assert "Qwen/Qwen2.5-Coder-32B-Instruct" in get_known_models()
    assert get_model_name("Qwen/Qwen3-Coder-30B-A3B-Instruct") == "Qwen3-Coder-30B"
    assert get_model_name("unknown/model") == "unknown/model"


def test_ssh_command_parsing_and_command_building() -> None:
    parsed = parse_ssh_command("ssh -p 2222 root@example.com")
    assert parsed.binary == "ssh"
    assert parsed.host == "root@example.com"
    assert parsed.port == "2222"

    command = build_ssh_command("ssh -p 2222 root@example.com", "hostname", keep_alive=True, force_tty=True)
    assert command[:7] == ["ssh", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=120", "-t", "-p"]
    assert command[-2:] == ["root@example.com", "hostname"]

    scp_command = build_scp_command("ssh -p 2222 root@example.com", "/tmp/a", "/remote/b")
    assert scp_command == ["scp", "-P", "2222", "/tmp/a", "root@example.com:/remote/b"]


def test_setup_pod_runs_bootstrap_and_persists_detected_gpus(tmp_path: Path) -> None:
    ssh_calls: list[tuple[str, str]] = []
    streamed: list[tuple[str, str]] = []

    def fake_ssh_exec(ssh_cmd: str, command: str, **kwargs):  # noqa: ANN001
        del kwargs
        ssh_calls.append((ssh_cmd, command))
        if "echo 'SSH OK'" in command:
            from pods import SSHResult

            return SSHResult(stdout="SSH OK\n", stderr="", exit_code=0)
        if "nvidia-smi" in command:
            from pods import SSHResult

            return SSHResult(stdout="0, NVIDIA H200, 141GB\n1, NVIDIA H200, 141GB\n", stderr="", exit_code=0)
        raise AssertionError(command)

    def fake_stream(ssh_cmd: str, command: str, **kwargs):  # noqa: ANN001
        streamed.append((ssh_cmd, command))
        return 0

    def fake_scp(ssh_cmd: str, local_path: str, remote_path: str) -> bool:
        assert Path(local_path).name == "pod_setup.sh"
        assert remote_path == "/tmp/pod_setup.sh"
        return True

    result = setup_pod(
        "dc1",
        "ssh root@example.com",
        SetupPodOptions(mount="sudo mount -t nfs example:/data /mnt/models"),
        config_dir=tmp_path.as_posix(),
        hf_token="hf-token",
        api_key="pi-key",
        ssh_exec_fn=fake_ssh_exec,
        ssh_exec_stream_fn=fake_stream,
        scp_file_fn=fake_scp,
    )
    assert result["modelsPath"] == "/mnt/models"
    assert len(result["gpus"]) == 2
    assert "--vllm 'release'" in streamed[0][1]
    loaded = load_config(tmp_path.as_posix())
    assert loaded.active == "dc1"
    assert loaded.pods["dc1"].models_path == "/mnt/models"


def test_setup_pod_requires_models_path_when_not_extractable(tmp_path: Path) -> None:
    try:
        setup_pod("dc1", "ssh root@example.com", SetupPodOptions(), config_dir=tmp_path.as_posix(), hf_token="hf", api_key="pi")
    except PodsCommandError as exc:
        assert "models-path" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected PodsCommandError")


def test_start_model_selects_gpu_and_persists_running_model(tmp_path: Path) -> None:
    save_config(
        Config(
            pods={
                "dc1": Pod(
                    ssh="ssh root@example.com",
                    gpus=[GPU(id=0, name="NVIDIA H200", memory="141GB"), GPU(id=1, name="NVIDIA H200", memory="141GB")],
                    models={"busy": PodModel(model="other/model", port=8001, gpu=[0], pid=111)},
                    models_path="/mnt/models",
                    vllm_version="release",
                )
            },
            active="dc1",
        ),
        tmp_path.as_posix(),
    )
    commands: list[str] = []

    def fake_ssh_exec(ssh_cmd: str, command: str, **kwargs):  # noqa: ANN001
        del ssh_cmd, kwargs
        commands.append(command)
        from pods import SSHResult

        if "echo $!" in command:
            return SSHResult(stdout="4242\n", stderr="", exit_code=0)
        return SSHResult(stdout="", stderr="", exit_code=0)

    result = start_model(
        "Qwen/Qwen2.5-Coder-32B-Instruct",
        "qwen",
        StartModelOptions(memory="50%", context="16k"),
        config_dir=tmp_path.as_posix(),
        ssh_exec_fn=fake_ssh_exec,
    )
    assert result["gpus"] == [0, 1]
    assert result["port"] == 8002
    assert "--gpu-memory-utilization" in result["vllmArgs"]
    assert "--max-model-len" in result["vllmArgs"]
    loaded = load_config(tmp_path.as_posix())
    assert loaded.pods["dc1"].models["qwen"].pid == 4242
    assert any("model_run_qwen.sh" in command for command in commands)


def test_start_model_rejects_custom_model_gpu_override(tmp_path: Path) -> None:
    save_config(
        Config(
            pods={"dc1": Pod(ssh="ssh root@example.com", gpus=[GPU(id=0, name="NVIDIA H200", memory="141GB")], models={}, models_path="/mnt/models")},
            active="dc1",
        ),
        tmp_path.as_posix(),
    )
    try:
        start_model("custom/model", "custom", StartModelOptions(gpus=2), config_dir=tmp_path.as_posix())
    except PodsCommandError as exc:
        assert "--gpus" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected PodsCommandError")


def test_next_port_and_gpu_selection_balance_usage() -> None:
    pod = Pod(
        ssh="ssh root@example.com",
        gpus=[GPU(id=0, name="NVIDIA H200", memory="141GB"), GPU(id=1, name="NVIDIA H200", memory="141GB")],
        models={
            "a": PodModel(model="m1", port=8001, gpu=[0], pid=10),
            "b": PodModel(model="m2", port=8003, gpu=[0], pid=11),
        },
    )
    assert get_next_port(pod) == 8002
    assert select_gpus(pod, 1) == [1]


def test_stop_model_and_stop_all_models_update_config(tmp_path: Path) -> None:
    save_config(
        Config(
            pods={
                "dc1": Pod(
                    ssh="ssh root@example.com",
                    gpus=[GPU(id=0, name="NVIDIA H200", memory="141GB")],
                    models={
                        "a": PodModel(model="m1", port=8001, gpu=[0], pid=10),
                        "b": PodModel(model="m2", port=8002, gpu=[0], pid=11),
                    },
                    models_path="/mnt/models",
                )
            },
            active="dc1",
        ),
        tmp_path.as_posix(),
    )
    issued: list[str] = []

    def fake_ssh_exec(ssh_cmd: str, command: str, **kwargs):  # noqa: ANN001
        del ssh_cmd, kwargs
        issued.append(command)
        from pods import SSHResult

        return SSHResult(stdout="", stderr="", exit_code=0)

    assert stop_model("a", config_dir=tmp_path.as_posix(), ssh_exec_fn=fake_ssh_exec) == "a"
    assert "a" not in load_config(tmp_path.as_posix()).pods["dc1"].models
    stopped = stop_all_models(config_dir=tmp_path.as_posix(), ssh_exec_fn=fake_ssh_exec)
    assert stopped == ["b"]
    assert load_config(tmp_path.as_posix()).pods["dc1"].models == {}
    assert any("kill 10" in command for command in issued)


def test_list_models_can_verify_remote_status(tmp_path: Path) -> None:
    save_config(
        Config(
            pods={
                "dc1": Pod(
                    ssh="ssh root@example.com",
                    gpus=[GPU(id=0, name="NVIDIA H200", memory="141GB")],
                    models={"a": PodModel(model="m1", port=8001, gpu=[0], pid=10)},
                    models_path="/mnt/models",
                )
            },
            active="dc1",
        ),
        tmp_path.as_posix(),
    )

    def fake_ssh_exec(ssh_cmd: str, command: str, **kwargs):  # noqa: ANN001
        del ssh_cmd, command, kwargs
        from pods import SSHResult

        return SSHResult(stdout="running\n", stderr="", exit_code=0)

    models = list_models(config_dir=tmp_path.as_posix(), verify=True, ssh_exec_fn=fake_ssh_exec)
    assert models[0]["status"] == "running"
    assert models[0]["url"] == "http://example.com:8001/v1"


def test_build_prompt_agent_args_uses_responses_for_gpt_oss(tmp_path: Path) -> None:
    save_config(
        Config(
            pods={
                "dc1": Pod(
                    ssh="ssh root@example.com",
                    gpus=[],
                    models={"gpt": PodModel(model="openai/gpt-oss-20b", port=8001, gpu=[0], pid=10)},
                )
            },
            active="dc1",
        ),
        tmp_path.as_posix(),
    )
    args = build_prompt_agent_args("gpt", ["hello"], PromptOptions(cwd="/work"), config_dir=tmp_path.as_posix())
    assert args[:8] == [
        "--base-url",
        "http://example.com:8001/v1",
        "--model",
        "openai/gpt-oss-20b",
        "--api-key",
        "dummy",
        "--api",
        "responses",
    ]
    assert args[-1] == "hello"
