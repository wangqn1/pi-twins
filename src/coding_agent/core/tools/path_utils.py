from __future__ import annotations

import os
import unicodedata
from pathlib import Path

UNICODE_SPACES = {
    "\u00A0",
    "\u2000",
    "\u2001",
    "\u2002",
    "\u2003",
    "\u2004",
    "\u2005",
    "\u2006",
    "\u2007",
    "\u2008",
    "\u2009",
    "\u200A",
    "\u202F",
    "\u205F",
    "\u3000",
}


def _normalize_unicode_spaces(value: str) -> str:
    return "".join(" " if c in UNICODE_SPACES else c for c in value)


def _normalize_at_prefix(value: str) -> str:
    return value[1:] if value.startswith("@") else value


def expand_path(value: str) -> str:
    value = _normalize_unicode_spaces(_normalize_at_prefix(value))
    if value == "~":
        return str(Path.home())
    if value.startswith("~/"):
        return str(Path.home() / value[2:])
    return value


def resolve_to_cwd(value: str, cwd: str) -> str:
    expanded = expand_path(value)
    path = Path(expanded)
    if path.is_absolute():
        return str(path)
    return str((Path(cwd) / path).resolve())


def _try_macos_screenshot_variant(path: str) -> str:
    return path.replace(" AM.", "\u202FAM.").replace(" PM.", "\u202FPM.")


def _try_nfd_variant(path: str) -> str:
    return unicodedata.normalize("NFD", path)


def _try_curly_quote_variant(path: str) -> str:
    return path.replace("'", "\u2019")


def resolve_read_path(value: str, cwd: str) -> str:
    resolved = resolve_to_cwd(value, cwd)
    if os.path.exists(resolved):
        return resolved

    candidates = [
        _try_macos_screenshot_variant(resolved),
        _try_curly_quote_variant(resolved),
    ]

    nfd = _try_nfd_variant(resolved)
    candidates.append(nfd)
    candidates.append(_try_curly_quote_variant(nfd))

    for candidate in candidates:
        if candidate != resolved and os.path.exists(candidate):
            return candidate
    return resolved
