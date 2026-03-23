# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .path_utils import resolve_to_cwd
from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_head, truncate_line
from .types import ToolExecutionError, ToolResult

DEFAULT_LIMIT = 100


@dataclass
class GrepTool:
    cwd: str

    def _format_block(
        self,
        *,
        file_path: Path,
        root: Path,
        line_number: int,
        context: int,
        lines_truncated_ref: list[bool],
    ) -> list[str]:
        if root.is_dir():
            try:
                rel = file_path.relative_to(root).as_posix()
            except ValueError:
                rel = file_path.name
        else:
            rel = file_path.name

        try:
            lines = file_path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        except Exception:
            return [f"{rel}:{line_number}: (unable to read file)"]

        start = max(1, line_number - context) if context > 0 else line_number
        end = min(len(lines), line_number + context) if context > 0 else line_number
        block: list[str] = []

        for current in range(start, end + 1):
            line = lines[current - 1]
            rendered, cut = truncate_line(line)
            if cut:
                lines_truncated_ref[0] = True
            if current == line_number:
                block.append(f"{rel}:{current}: {rendered}")
            else:
                block.append(f"{rel}-{current}- {rendered}")
        return block

    def _run_rg(
        self,
        *,
        pattern: str,
        root: Path,
        glob: str | None,
        ignore_case: bool,
        literal: bool,
        context: int,
        limit: int,
    ) -> tuple[list[str], bool, bool]:
        rg = shutil.which("rg")
        if rg is None:
            raise FileNotFoundError("rg not found")

        args = [rg, "--json", "--line-number", "--color=never", "--hidden"]
        if ignore_case:
            args.append("--ignore-case")
        if literal:
            args.append("--fixed-strings")
        if glob:
            args.extend(["--glob", glob])
        args.extend([pattern, str(root)])

        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        matches: list[tuple[Path, int]] = []
        match_limit_reached = False

        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            file_path = event.get("data", {}).get("path", {}).get("text")
            line_number = event.get("data", {}).get("line_number")
            if not file_path or not isinstance(line_number, int):
                continue
            matches.append((Path(file_path), line_number))
            if len(matches) >= limit:
                match_limit_reached = True
                process.kill()
                break

        stderr = process.stderr.read() if process.stderr else ""
        process.wait()
        if process.returncode not in (0, 1, -9):
            raise ToolExecutionError(stderr.strip() or f"ripgrep exited with code {process.returncode}")

        lines_truncated = [False]
        output_lines: list[str] = []
        for file_path, line_number in matches:
            output_lines.extend(
                self._format_block(
                    file_path=file_path,
                    root=root,
                    line_number=line_number,
                    context=context,
                    lines_truncated_ref=lines_truncated,
                )
            )
        return output_lines, match_limit_reached, lines_truncated[0]

    def _run_python_fallback(
        self,
        *,
        pattern: str,
        root: Path,
        glob: str | None,
        ignore_case: bool,
        literal: bool,
        context: int,
        limit: int,
    ) -> tuple[list[str], bool, bool]:
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(re.escape(pattern) if literal else pattern, flags=flags)
        output_lines: list[str] = []
        lines_truncated = [False]
        match_count = 0
        match_limit_reached = False

        if root.is_file():
            candidates = [root]
        else:
            candidates = [
                p
                for p in root.rglob("*")
                if p.is_file() and ".git/" not in p.as_posix() and "node_modules/" not in p.as_posix()
            ]
            if glob:
                candidates = [p for p in candidates if p.match(glob)]

        for file_path in candidates:
            try:
                lines = file_path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").split("\n")
            except Exception:
                continue
            for idx, line in enumerate(lines, start=1):
                if regex.search(line) is None:
                    continue
                output_lines.extend(
                    self._format_block(
                        file_path=file_path,
                        root=root,
                        line_number=idx,
                        context=context,
                        lines_truncated_ref=lines_truncated,
                    )
                )
                match_count += 1
                if match_count >= limit:
                    match_limit_reached = True
                    return output_lines, match_limit_reached, lines_truncated[0]
        return output_lines, match_limit_reached, lines_truncated[0]

    def run(
        self,
        *,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        ignore_case: bool = False,
        literal: bool = False,
        context: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> ToolResult:
        root = Path(resolve_to_cwd(path or ".", self.cwd))
        if not root.exists():
            raise ToolExecutionError(f"Path not found: {root}")

        try:
            output_lines, match_limit_reached, lines_truncated = self._run_rg(
                pattern=pattern,
                root=root,
                glob=glob,
                ignore_case=ignore_case,
                literal=literal,
                context=max(context, 0),
                limit=max(limit, 1),
            )
        except (FileNotFoundError, ToolExecutionError):
            output_lines, match_limit_reached, lines_truncated = self._run_python_fallback(
                pattern=pattern,
                root=root,
                glob=glob,
                ignore_case=ignore_case,
                literal=literal,
                context=max(context, 0),
                limit=max(limit, 1),
            )

        if not output_lines:
            return ToolResult(content=[{"type": "text", "text": "No matches found"}])

        raw = "\n".join(output_lines)
        truncation = truncate_head(raw, max_lines=10**9)
        output = truncation.content
        details: dict[str, object] = {}
        notices: list[str] = []

        if match_limit_reached:
            notices.append(f"{limit} matches limit reached")
            details["matchLimitReached"] = limit
        if truncation.truncated:
            notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
            details["truncation"] = truncation.to_dict()
        if lines_truncated:
            notices.append("Some lines truncated to 500 chars. Use read for full lines")
            details["linesTruncated"] = True
        if notices:
            output += f"\n\n[{' . '.join(notices)}]"

        return ToolResult(content=[{"type": "text", "text": output}], details=details or None)

    def run_from_dict(self, payload: dict[str, object]) -> ToolResult:
        return self.run(
            pattern=str(payload["pattern"]),
            path=str(payload["path"]) if "path" in payload and payload["path"] is not None else None,
            glob=str(payload["glob"]) if "glob" in payload and payload["glob"] is not None else None,
            ignore_case=bool(payload["ignoreCase"]) if "ignoreCase" in payload else False,
            literal=bool(payload["literal"]) if "literal" in payload else False,
            context=int(payload["context"]) if "context" in payload and payload["context"] is not None else 0,
            limit=int(payload["limit"]) if "limit" in payload and payload["limit"] is not None else DEFAULT_LIMIT,
        )
