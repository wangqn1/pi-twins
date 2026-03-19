from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal


SandboxType = Literal["host", "docker"]


@dataclass
class SandboxConfig:
    type: SandboxType
    container: str | None = None


@dataclass
class ExecOptions:
    timeout: float | None = None


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    code: int


def parse_sandbox_arg(value: str) -> SandboxConfig:
    if value == "host":
        return SandboxConfig(type="host")
    if value.startswith("docker:"):
        container = value[len("docker:") :].strip()
        if not container:
            raise ValueError("docker sandbox requires container name (e.g. docker:mom-sandbox)")
        return SandboxConfig(type="docker", container=container)
    raise ValueError(f"Invalid sandbox type '{value}'. Use 'host' or 'docker:<container-name>'")


def _exec_simple(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"Exit code {proc.returncode}")
    return proc.stdout


def validate_sandbox(config: SandboxConfig) -> None:
    if config.type == "host":
        return
    _exec_simple(["docker", "--version"])
    result = _exec_simple(["docker", "inspect", "-f", "{{.State.Running}}", str(config.container)])
    if result.strip() != "true":
        raise RuntimeError(f"Container '{config.container}' is not running")


class Executor:
    def exec(self, command: str, options: ExecOptions | None = None) -> ExecResult:  # pragma: no cover - interface only
        raise NotImplementedError

    def get_workspace_path(self, host_path: str) -> str:
        raise NotImplementedError


class HostExecutor(Executor):
    def exec(self, command: str, options: ExecOptions | None = None) -> ExecResult:
        timeout = options.timeout if options is not None else None
        proc = subprocess.run(  # noqa: S603
            [os_shell(), shell_flag(), command],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return ExecResult(stdout=proc.stdout, stderr=proc.stderr, code=proc.returncode)

    def get_workspace_path(self, host_path: str) -> str:
        return host_path


class DockerExecutor(Executor):
    def __init__(self, container: str) -> None:
        self.container = container
        self._host = HostExecutor()

    def exec(self, command: str, options: ExecOptions | None = None) -> ExecResult:
        quoted = shlex.quote(command)
        docker_command = f"docker exec {shlex.quote(self.container)} sh -c {quoted}"
        return self._host.exec(docker_command, options)

    def get_workspace_path(self, host_path: str) -> str:
        del host_path
        return "/workspace"


def create_executor(config: SandboxConfig) -> Executor:
    if config.type == "host":
        return HostExecutor()
    return DockerExecutor(str(config.container))


def os_shell() -> str:
    return "cmd" if sys.platform == "win32" else "sh"


def shell_flag() -> str:
    return "/c" if sys.platform == "win32" else "-c"
