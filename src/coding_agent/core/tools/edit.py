from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

from .path_utils import resolve_to_cwd
from .types import ToolExecutionError, ToolResult


def _detect_line_ending(content: str) -> str:
    if "\r\n" in content:
        return "\r\n"
    return "\n"


def _restore_line_ending(content: str, line_ending: str) -> str:
    if line_ending == "\n":
        return content
    return content.replace("\n", line_ending)


def _strip_bom(content: str) -> tuple[str, str]:
    if content.startswith("\ufeff"):
        return "\ufeff", content[1:]
    return "", content


def _first_changed_line(old: str, new: str) -> int | None:
    old_lines = old.split("\n")
    new_lines = new.split("\n")
    max_len = max(len(old_lines), len(new_lines))
    for i in range(max_len):
        old_line = old_lines[i] if i < len(old_lines) else None
        new_line = new_lines[i] if i < len(new_lines) else None
        if old_line != new_line:
            return i + 1
    return None


@dataclass
class EditTool:
    cwd: str

    def run(self, *, path: str, old_text: str, new_text: str) -> ToolResult:
        absolute_path = Path(resolve_to_cwd(path, self.cwd))
        if not absolute_path.exists():
            raise ToolExecutionError(f"File not found: {path}")

        raw = absolute_path.read_text(encoding="utf-8")
        bom, content = _strip_bom(raw)
        line_ending = _detect_line_ending(content)
        normalized_content = content.replace("\r\n", "\n")
        normalized_old = old_text.replace("\r\n", "\n")
        normalized_new = new_text.replace("\r\n", "\n")

        occurrences = normalized_content.count(normalized_old)
        if occurrences == 0:
            raise ToolExecutionError(
                f"Could not find the exact text in {path}. The old text must match exactly including all whitespace."
            )
        if occurrences > 1:
            raise ToolExecutionError(
                f"Found {occurrences} occurrences of the text in {path}. The text must be unique; add more context."
            )

        replaced = normalized_content.replace(normalized_old, normalized_new, 1)
        if replaced == normalized_content:
            raise ToolExecutionError(f"No changes made to {path}.")

        final = bom + _restore_line_ending(replaced, line_ending)
        absolute_path.write_text(final, encoding="utf-8")

        diff = "".join(
            unified_diff(
                normalized_content.splitlines(keepends=True),
                replaced.splitlines(keepends=True),
                fromfile=path,
                tofile=path,
            )
        )
        return ToolResult(
            content=[{"type": "text", "text": f"Successfully replaced text in {path}."}],
            details={"diff": diff, "firstChangedLine": _first_changed_line(normalized_content, replaced)},
        )

    def run_from_dict(self, payload: dict[str, object]) -> ToolResult:
        return self.run(path=str(payload["path"]), old_text=str(payload["oldText"]), new_text=str(payload["newText"]))
