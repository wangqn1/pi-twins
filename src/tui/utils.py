# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import re
import unicodedata


ANSI_CSI_FINALS = set("mGKHJABCD")


def extract_ansi_code(text: str, pos: int) -> tuple[str, int] | None:
    if pos >= len(text) or text[pos] != "\x1b":
        return None
    if pos + 1 >= len(text):
        return None

    next_char = text[pos + 1]
    if next_char == "[":
        idx = pos + 2
        while idx < len(text) and text[idx] not in ANSI_CSI_FINALS:
            idx += 1
        if idx < len(text):
            return text[pos : idx + 1], idx + 1 - pos
        return None
    if next_char in {"]", "_"}:
        idx = pos + 2
        while idx < len(text):
            if text[idx] == "\x07":
                return text[pos : idx + 1], idx + 1 - pos
            if text[idx] == "\x1b" and idx + 1 < len(text) and text[idx + 1] == "\\":
                return text[pos : idx + 2], idx + 2 - pos
            idx += 1
    return None


def _strip_ansi(text: str) -> str:
    output: list[str] = []
    idx = 0
    while idx < len(text):
        ansi = extract_ansi_code(text, idx)
        if ansi is not None:
            _, length = ansi
            idx += length
            continue
        output.append(text[idx])
        idx += 1
    return "".join(output)


def _char_width(char: str) -> int:
    if not char:
        return 0
    if char == "\t":
        return 3
    if unicodedata.category(char)[0] == "C":
        return 0
    if unicodedata.combining(char):
        return 0
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return 2
    return 1


def visible_width(text: str) -> int:
    clean = _strip_ansi(text)
    return sum(_char_width(char) for char in clean)


def truncate_to_width(text: str, width: int, suffix: str = "") -> str:
    if width <= 0:
        return ""
    if visible_width(text) <= width:
        return text

    suffix_width = visible_width(suffix)
    target = max(0, width - suffix_width)
    output: list[str] = []
    current_width = 0
    idx = 0
    while idx < len(text) and current_width < target:
        ansi = extract_ansi_code(text, idx)
        if ansi is not None:
            code, length = ansi
            output.append(code)
            idx += length
            continue
        char = text[idx]
        char_width = _char_width(char)
        if current_width + char_width > target:
            break
        output.append(char)
        current_width += char_width
        idx += 1
    return "".join(output) + suffix


def wrap_text_with_ansi(text: str, width: int) -> list[str]:
    if width <= 0:
        return [""]
    normalized = text.replace("\t", "   ")
    raw_lines = normalized.splitlines() or [normalized]
    wrapped: list[str] = []
    for raw_line in raw_lines:
        line = raw_line
        if line == "":
            wrapped.append("")
            continue
        while visible_width(line) > width:
            wrapped.append(truncate_to_width(line, width))
            stripped = _strip_ansi(truncate_to_width(line, width))
            cut_chars = len(stripped)
            line = _strip_ansi(line)[cut_chars:]
        wrapped.append(line)
    return wrapped or [""]


def apply_background_to_line(line: str, width: int, bg_fn) -> str:  # noqa: ANN001
    padded = line
    current_width = visible_width(line)
    if current_width < width:
        padded = line + (" " * (width - current_width))
    return bg_fn(padded)
