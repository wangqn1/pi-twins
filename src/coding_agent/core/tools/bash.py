from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass

from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_tail
from .types import ToolExecutionError, ToolResult


@dataclass
class BashTool:
    cwd: str
    command_prefix: str | None = None

    def run(self, *, command: str, timeout: int | None = None) -> ToolResult:
        shell = os.environ.get("SHELL", "/bin/bash")
        resolved_command = f"{self.command_prefix}\n{command}" if self.command_prefix else command

        process = subprocess.Popen(
            [shell, "-lc", resolved_command],
            cwd=self.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            raise ToolExecutionError(f"Command timed out after {timeout} seconds") from exc
        exit_code = process.returncode if process.returncode is not None else 1

        encoded = output.encode("utf-8", errors="replace")
        temp_file_path: str | None = None
        if len(encoded) > DEFAULT_MAX_BYTES:
            with tempfile.NamedTemporaryFile(prefix="pi-bash-", suffix=".log", delete=False, mode="w", encoding="utf-8") as handle:
                handle.write(output)
                temp_file_path = handle.name

        truncation = truncate_tail(output)
        rendered = truncation.content or "(no output)"
        details: dict[str, object] | None = None

        if truncation.truncated:
            details = {"truncation": truncation.to_dict()}
            if temp_file_path is not None:
                details["fullOutputPath"] = temp_file_path
            start_line = truncation.total_lines - truncation.output_lines + 1
            end_line = truncation.total_lines
            rendered += (
                f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines} "
                f"({format_size(DEFAULT_MAX_BYTES)} limit).]"
            )

        if exit_code != 0:
            raise ToolExecutionError(f"{rendered}\n\nCommand exited with code {exit_code}")

        return ToolResult(content=[{"type": "text", "text": rendered}], details=details)

    def run_from_dict(self, payload: dict[str, object]) -> ToolResult:
        timeout = int(payload["timeout"]) if "timeout" in payload and payload["timeout"] is not None else None
        return self.run(command=str(payload["command"]), timeout=timeout)
