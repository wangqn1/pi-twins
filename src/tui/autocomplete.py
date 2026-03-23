# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .fuzzy import fuzzy_filter


PATH_DELIMITERS = {" ", "\t", '"', "'", "="}


@dataclass(frozen=True)
class AutocompleteItem:
    value: str
    label: str
    description: str | None = None


class SlashCommand(Protocol):
    name: str
    description: str | None

    def get_argument_completions(self, argument_prefix: str) -> list[AutocompleteItem] | None: ...


class AutocompleteProvider(Protocol):
    def get_suggestions(self, lines: list[str], cursor_line: int, cursor_col: int) -> dict[str, object] | None: ...

    def apply_completion(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        item: AutocompleteItem,
        prefix: str,
    ) -> dict[str, object]: ...


def _find_last_delimiter(text: str) -> int:
    for index in range(len(text) - 1, -1, -1):
        if text[index] in PATH_DELIMITERS:
            return index
    return -1


def _find_unclosed_quote_start(text: str) -> int | None:
    in_quotes = False
    quote_start = -1
    for index, char in enumerate(text):
        if char == '"':
            in_quotes = not in_quotes
            if in_quotes:
                quote_start = index
    return quote_start if in_quotes else None


def _build_completion_value(path: str, *, is_at_prefix: bool, is_quoted_prefix: bool) -> str:
    needs_quotes = is_quoted_prefix or " " in path
    prefix = "@" if is_at_prefix else ""
    if not needs_quotes:
        return f"{prefix}{path}"
    return f'{prefix}"{path}"'


class CombinedAutocompleteProvider:
    def __init__(self, commands: list[SlashCommand | AutocompleteItem] | None = None, base_path: str | None = None) -> None:
        self.commands = commands or []
        self.base_path = base_path or os.getcwd()

    def get_suggestions(self, lines: list[str], cursor_line: int, cursor_col: int) -> dict[str, object] | None:
        current_line = lines[cursor_line] if cursor_line < len(lines) else ""
        text_before_cursor = current_line[:cursor_col]

        at_prefix = self.extract_at_prefix(text_before_cursor)
        if at_prefix is not None:
            raw_prefix, is_at_prefix, is_quoted_prefix = self.parse_path_prefix(at_prefix)
            items = self.get_fuzzy_file_suggestions(raw_prefix, is_quoted_prefix=is_quoted_prefix)
            return {"items": items, "prefix": at_prefix} if items else None

        if text_before_cursor.startswith("/"):
            space_index = text_before_cursor.find(" ")
            if space_index == -1:
                prefix = text_before_cursor[1:]
                command_items = [
                    AutocompleteItem(
                        value=getattr(command, "name", getattr(command, "value", "")),
                        label=getattr(command, "name", getattr(command, "label", "")),
                        description=getattr(command, "description", None),
                    )
                    for command in self.commands
                ]
                items = fuzzy_filter(command_items, prefix, lambda item: item.value)
                return {"items": items, "prefix": text_before_cursor} if items else None

            command_name = text_before_cursor[1:space_index]
            argument_text = text_before_cursor[space_index + 1 :]
            for command in self.commands:
                name = getattr(command, "name", getattr(command, "value", ""))
                if name != command_name or not hasattr(command, "get_argument_completions"):
                    continue
                items = command.get_argument_completions(argument_text)  # type: ignore[attr-defined]
                return {"items": items, "prefix": argument_text} if items else None
            return None

        path_prefix = self.extract_path_prefix(text_before_cursor, force_extract=False)
        if path_prefix is not None:
            items = self.get_file_suggestions(path_prefix)
            return {"items": items, "prefix": path_prefix} if items else None
        return None

    def apply_completion(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        item: AutocompleteItem,
        prefix: str,
    ) -> dict[str, object]:
        current_line = lines[cursor_line] if cursor_line < len(lines) else ""
        before_prefix = current_line[: cursor_col - len(prefix)]
        after_cursor = current_line[cursor_col:]
        is_slash_command = prefix.startswith("/") and before_prefix.strip() == "" and "/" not in prefix[1:]
        if is_slash_command:
            new_line = f"{before_prefix}/{item.value} {after_cursor}"
            new_cursor = len(before_prefix) + len(item.value) + 2
        else:
            suffix = " " if prefix.startswith("@") and not item.label.endswith("/") else ""
            new_line = before_prefix + item.value + suffix + after_cursor
            new_cursor = len(before_prefix) + len(item.value) + len(suffix)
            if item.label.endswith("/") and item.value.endswith('"'):
                new_cursor -= 1
        new_lines = list(lines)
        new_lines[cursor_line] = new_line
        return {"lines": new_lines, "cursorLine": cursor_line, "cursorCol": new_cursor}

    def should_trigger_file_completion(self, lines: list[str], cursor_line: int, cursor_col: int) -> bool:
        current_line = lines[cursor_line] if cursor_line < len(lines) else ""
        text_before_cursor = current_line[:cursor_col]
        return not (text_before_cursor.strip().startswith("/") and " " not in text_before_cursor.strip())

    def get_force_file_suggestions(self, lines: list[str], cursor_line: int, cursor_col: int) -> dict[str, object] | None:
        if not self.should_trigger_file_completion(lines, cursor_line, cursor_col):
            return None
        current_line = lines[cursor_line] if cursor_line < len(lines) else ""
        prefix = self.extract_path_prefix(current_line[:cursor_col], force_extract=True)
        if prefix is None:
            return None
        items = self.get_file_suggestions(prefix)
        return {"items": items, "prefix": prefix} if items else None

    def extract_at_prefix(self, text: str) -> str | None:
        quote_start = _find_unclosed_quote_start(text)
        if quote_start is not None:
            if quote_start > 0 and text[quote_start - 1] == "@":
                return text[quote_start - 1 :]
        last_delimiter = _find_last_delimiter(text)
        token_start = 0 if last_delimiter == -1 else last_delimiter + 1
        token = text[token_start:]
        if token.startswith('@"') or token.startswith("@"):
            return token
        return None

    def extract_path_prefix(self, text: str, force_extract: bool = False) -> str | None:
        last_delimiter = _find_last_delimiter(text)
        prefix = text if last_delimiter == -1 else text[last_delimiter + 1 :]
        if force_extract:
            return prefix
        if "/" in prefix or prefix.startswith(".") or prefix.startswith("~/"):
            return prefix
        if prefix == "" and text.endswith(" "):
            return prefix
        return None

    def parse_path_prefix(self, prefix: str) -> tuple[str, bool, bool]:
        if prefix.startswith('@"'):
            return prefix[2:], True, True
        if prefix.startswith('"'):
            return prefix[1:], False, True
        if prefix.startswith("@"):
            return prefix[1:], True, False
        return prefix, False, False

    def expand_home_path(self, path: str) -> str:
        if path == "~":
            return str(Path.home())
        if path.startswith("~/"):
            return str(Path.home() / path[2:])
        return path

    def get_file_suggestions(self, prefix: str) -> list[AutocompleteItem]:
        raw_prefix, is_at_prefix, is_quoted_prefix = self.parse_path_prefix(prefix)
        expanded_prefix = self.expand_home_path(raw_prefix)

        if raw_prefix in {"", "./", "../", "~", "~/", "/"} or raw_prefix.endswith("/"):
            search_dir = Path(expanded_prefix) if expanded_prefix.startswith("/") else Path(self.base_path) / expanded_prefix
            search_prefix = ""
        else:
            directory = Path(expanded_prefix).parent
            if not str(directory) or str(directory) == ".":
                directory = Path(self.base_path)
            elif not str(directory).startswith("/"):
                directory = Path(self.base_path) / directory
            search_dir = directory
            search_prefix = Path(expanded_prefix).name

        try:
            entries = list(search_dir.iterdir())
        except OSError:
            return []

        suggestions: list[AutocompleteItem] = []
        for entry in sorted(entries, key=lambda item: (not item.is_dir(), item.name.lower())):
            if not entry.name.lower().startswith(search_prefix.lower()):
                continue
            if raw_prefix.endswith("/"):
                relative_path = raw_prefix + entry.name
            elif "/" in raw_prefix:
                parent = Path(raw_prefix).parent
                relative_path = str(parent / entry.name) if str(parent) != "." else entry.name
            elif raw_prefix.startswith("~"):
                relative_path = f"~/{entry.name}"
            else:
                relative_path = entry.name
            completion_path = f"{relative_path}/" if entry.is_dir() else relative_path
            suggestions.append(
                AutocompleteItem(
                    value=_build_completion_value(completion_path, is_at_prefix=is_at_prefix, is_quoted_prefix=is_quoted_prefix),
                    label=entry.name + ("/" if entry.is_dir() else ""),
                )
            )
        return suggestions

    def get_fuzzy_file_suggestions(self, query: str, *, is_quoted_prefix: bool) -> list[AutocompleteItem]:
        scoped_base = Path(self.base_path)
        scoped_query = query
        if "/" in query:
            base_prefix, _, tail = query.rpartition("/")
            candidate_base = Path(self.expand_home_path(base_prefix or "."))
            if not candidate_base.is_absolute():
                candidate_base = Path(self.base_path) / candidate_base
            if candidate_base.is_dir():
                scoped_base = candidate_base
                scoped_query = tail

        entries: list[tuple[str, bool]] = []
        for root, dirs, files in os.walk(scoped_base):
            dirs[:] = [directory for directory in dirs if directory != ".git"]
            rel_root = os.path.relpath(root, scoped_base)
            for directory in dirs:
                rel_path = directory if rel_root == "." else os.path.join(rel_root, directory)
                entries.append((rel_path + "/", True))
            for file_name in files:
                rel_path = file_name if rel_root == "." else os.path.join(rel_root, file_name)
                entries.append((rel_path, False))

        ranked = fuzzy_filter(entries, scoped_query, lambda item: item[0])[:20]
        suggestions: list[AutocompleteItem] = []
        for rel_path, is_directory in ranked:
            display_path = rel_path.replace("\\", "/")
            label = Path(display_path.rstrip("/")).name + ("/" if is_directory else "")
            suggestions.append(
                AutocompleteItem(
                    value=_build_completion_value(display_path, is_at_prefix=True, is_quoted_prefix=is_quoted_prefix),
                    label=label,
                    description=display_path.rstrip("/"),
                )
            )
        return suggestions
