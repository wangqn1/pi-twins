from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import TextIO


@dataclass
class SSHResult:
    stdout: str
    stderr: str
    exit_code: int


@dataclass
class ParsedSSHCommand:
    binary: str
    args: list[str]
    host: str
    port: str


def parse_ssh_command(ssh_cmd: str) -> ParsedSSHCommand:
    parts = shlex.split(ssh_cmd)
    if not parts:
        raise ValueError("SSH command is empty")
    binary = parts[0]
    args = list(parts[1:])
    host = ""
    port = "22"

    i = 0
    while i < len(args):
        part = args[i]
        if part == "-p" and i + 1 < len(args):
            port = args[i + 1]
            i += 2
            continue
        if not part.startswith("-"):
            host = part
            break
        i += 1

    if not host:
        raise ValueError(f"Could not parse host from SSH command: {ssh_cmd}")
    return ParsedSSHCommand(binary=binary, args=args, host=host, port=port)


def build_ssh_command(ssh_cmd: str, command: str, *, keep_alive: bool = False, force_tty: bool = False) -> list[str]:
    parsed = parse_ssh_command(ssh_cmd)
    args = list(parsed.args)
    if force_tty and "-t" not in args:
        args = ["-t", *args]
    if keep_alive:
        args = ["-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=120", *args]
    return [parsed.binary, *args, command]


def build_scp_command(ssh_cmd: str, local_path: str, remote_path: str) -> list[str]:
    parsed = parse_ssh_command(ssh_cmd)
    return ["scp", "-P", parsed.port, local_path, f"{parsed.host}:{remote_path}"]


def ssh_exec(ssh_cmd: str, command: str, *, keep_alive: bool = False) -> SSHResult:
    proc = subprocess.run(  # noqa: S603
        build_ssh_command(ssh_cmd, command, keep_alive=keep_alive),
        capture_output=True,
        text=True,
        check=False,
    )
    return SSHResult(stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode)


def ssh_exec_stream(
    ssh_cmd: str,
    command: str,
    *,
    silent: bool = False,
    force_tty: bool = False,
    keep_alive: bool = False,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    if silent:
        out_handle = subprocess.DEVNULL
        err_handle = subprocess.DEVNULL
    else:
        out_handle = stdout or sys.stdout
        err_handle = stderr or sys.stderr

    proc = subprocess.Popen(  # noqa: S603
        build_ssh_command(ssh_cmd, command, keep_alive=keep_alive, force_tty=force_tty),
        stdout=out_handle,
        stderr=err_handle,
    )
    return proc.wait()


def scp_file(ssh_cmd: str, local_path: str, remote_path: str) -> bool:
    proc = subprocess.run(build_scp_command(ssh_cmd, local_path, remote_path), check=False)  # noqa: S603
    return proc.returncode == 0
