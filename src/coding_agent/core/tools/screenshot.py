# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import base64
import mimetypes
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .path_utils import resolve_to_cwd
from .types import ToolExecutionError, ToolResult

SUPPORTED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


CaptureRunner = Callable[[list[str]], None]


def _default_capture_runner(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)  # noqa: S603


@dataclass
class ScreenshotTool:
    cwd: str
    capture_runner: CaptureRunner = _default_capture_runner

    def run(self, *, path: str, interactive: bool = False) -> ToolResult:
        if platform.system() != "Darwin":
            raise ToolExecutionError("The screenshot tool is only available on macOS")

        absolute_path = Path(resolve_to_cwd(path, self.cwd))
        absolute_path.parent.mkdir(parents=True, exist_ok=True)

        args = ["screencapture", "-x"]
        if interactive:
            args.append("-i")
        args.append(absolute_path.as_posix())

        try:
            self.capture_runner(args)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise ToolExecutionError(stderr or "Failed to capture screenshot") from exc
        except FileNotFoundError as exc:
            raise ToolExecutionError("screencapture command not found") from exc

        if not absolute_path.exists():
            raise ToolExecutionError(f"Screenshot file was not created: {absolute_path.as_posix()}")

        mime_type, _ = mimetypes.guess_type(absolute_path.as_posix())
        if mime_type not in SUPPORTED_IMAGE_MIMES:
            mime_type = "image/png"

        encoded = base64.b64encode(absolute_path.read_bytes()).decode("ascii")
        return ToolResult(
            content=[
                {"type": "text", "text": f"Captured screenshot to {absolute_path.as_posix()} [{mime_type}]"},
                {"type": "image", "data": encoded, "mimeType": mime_type},
            ],
            details={"path": absolute_path.as_posix(), "interactive": bool(interactive)},
        )

    def run_from_dict(self, payload: dict[str, object]) -> ToolResult:
        return self.run(
            path=str(payload["path"]),
            interactive=bool(payload["interactive"]) if "interactive" in payload else False,
        )
