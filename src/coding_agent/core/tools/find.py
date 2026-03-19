from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .path_utils import resolve_to_cwd
from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_head
from .types import ToolExecutionError, ToolResult

DEFAULT_LIMIT = 1000


@dataclass
class FindTool:
    cwd: str

    def _run_fd(self, pattern: str, root: Path, limit: int) -> list[str]:
        fd = shutil.which("fd")
        if fd is None:
            raise FileNotFoundError("fd not found")

        args = [fd, "--glob", "--color=never", "--hidden", "--max-results", str(limit), pattern, str(root)]
        process = subprocess.run(args, capture_output=True, text=True)
        if process.returncode not in (0, 1):
            raise ToolExecutionError(process.stderr.strip() or f"fd exited with code {process.returncode}")
        lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
        results: list[str] = []
        for line in lines:
            file_path = Path(line)
            try:
                results.append(file_path.relative_to(root).as_posix())
            except ValueError:
                results.append(file_path.as_posix())
        return results

    def _run_python_fallback(self, pattern: str, root: Path, limit: int) -> list[str]:
        if root.is_file():
            return [root.name] if root.match(pattern) else []
        matches: list[str] = []
        for candidate in root.rglob("*"):
            if ".git/" in candidate.as_posix() or "node_modules/" in candidate.as_posix():
                continue
            if not candidate.match(pattern):
                continue
            matches.append(candidate.relative_to(root).as_posix())
            if len(matches) >= limit:
                break
        return matches

    def run(self, *, pattern: str, path: str | None = None, limit: int = DEFAULT_LIMIT) -> ToolResult:
        root = Path(resolve_to_cwd(path or ".", self.cwd))
        if not root.exists():
            raise ToolExecutionError(f"Path not found: {root}")

        effective_limit = max(limit, 1)
        try:
            results = self._run_fd(pattern, root, effective_limit)
        except (FileNotFoundError, ToolExecutionError):
            results = self._run_python_fallback(pattern, root, effective_limit)

        if not results:
            return ToolResult(content=[{"type": "text", "text": "No files found matching pattern"}])

        limit_reached = len(results) >= effective_limit
        raw = "\n".join(results)
        truncation = truncate_head(raw, max_lines=10**9)
        output = truncation.content
        details: dict[str, object] = {}
        notices: list[str] = []

        if limit_reached:
            notices.append(f"{effective_limit} results limit reached")
            details["resultLimitReached"] = effective_limit
        if truncation.truncated:
            notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
            details["truncation"] = truncation.to_dict()
        if notices:
            output += f"\n\n[{' . '.join(notices)}]"

        return ToolResult(content=[{"type": "text", "text": output}], details=details or None)

    def run_from_dict(self, payload: dict[str, object]) -> ToolResult:
        return self.run(
            pattern=str(payload["pattern"]),
            path=str(payload["path"]) if "path" in payload and payload["path"] is not None else None,
            limit=int(payload["limit"]) if "limit" in payload and payload["limit"] is not None else DEFAULT_LIMIT,
        )
