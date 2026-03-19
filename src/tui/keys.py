from __future__ import annotations

import re
from dataclasses import dataclass


_kitty_protocol_active = False
_last_event_type = "press"


def set_kitty_protocol_active(active: bool) -> None:
    global _kitty_protocol_active
    _kitty_protocol_active = active


def is_kitty_protocol_active() -> bool:
    return _kitty_protocol_active


LEGACY_SEQUENCE_KEY_IDS: dict[str, str] = {
    "\x1b[A": "up",
    "\x1bOA": "up",
    "\x1b[B": "down",
    "\x1bOB": "down",
    "\x1b[C": "right",
    "\x1bOC": "right",
    "\x1b[D": "left",
    "\x1bOD": "left",
    "\x1b[H": "home",
    "\x1bOH": "home",
    "\x1b[F": "end",
    "\x1bOF": "end",
    "\x1b[1~": "home",
    "\x1b[4~": "end",
    "\x1b[2~": "insert",
    "\x1b[3~": "delete",
    "\x1b[5~": "pageUp",
    "\x1b[6~": "pageDown",
    "\x1bOP": "f1",
    "\x1bOQ": "f2",
    "\x1bOR": "f3",
    "\x1bOS": "f4",
    "\x1b[15~": "f5",
    "\x1b[17~": "f6",
    "\x1b[18~": "f7",
    "\x1b[19~": "f8",
    "\x1b[20~": "f9",
    "\x1b[21~": "f10",
    "\x1b[23~": "f11",
    "\x1b[24~": "f12",
    "\x1bb": "alt+left",
    "\x1bf": "alt+right",
    "\x1bp": "alt+up",
    "\x1bn": "alt+down",
    "\x1b[Z": "shift+tab",
}

_SPECIAL_CHARS = {
    "\x1b": "escape",
    "\r": "enter",
    "\t": "tab",
    " ": "space",
    "\x7f": "backspace",
}

_CTRL_CHAR_MAP = {
    1: "a",
    2: "b",
    3: "c",
    4: "d",
    5: "e",
    6: "f",
    7: "g",
    8: "h",
    9: "tab",
    10: "j",
    11: "k",
    12: "l",
    13: "enter",
    14: "n",
    15: "o",
    16: "p",
    17: "q",
    18: "r",
    19: "s",
    20: "t",
    21: "u",
    22: "v",
    23: "w",
    24: "x",
    25: "y",
    26: "z",
    27: "escape",
    28: "\\",
    29: "]",
    30: "^",
    31: "-",
}


@dataclass(frozen=True)
class _KeyHelper:
    escape: str = "escape"
    esc: str = "esc"
    enter: str = "enter"
    return_: str = "return"
    tab: str = "tab"
    space: str = "space"
    backspace: str = "backspace"
    delete: str = "delete"
    insert: str = "insert"
    clear: str = "clear"
    home: str = "home"
    end: str = "end"
    pageUp: str = "pageUp"
    pageDown: str = "pageDown"
    up: str = "up"
    down: str = "down"
    left: str = "left"
    right: str = "right"
    f1: str = "f1"
    f2: str = "f2"
    f3: str = "f3"
    f4: str = "f4"
    f5: str = "f5"
    f6: str = "f6"
    f7: str = "f7"
    f8: str = "f8"
    f9: str = "f9"
    f10: str = "f10"
    f11: str = "f11"
    f12: str = "f12"
    backtick: str = "`"
    hyphen: str = "-"
    equals: str = "="
    leftbracket: str = "["
    rightbracket: str = "]"
    backslash: str = "\\"
    semicolon: str = ";"
    quote: str = "'"
    comma: str = ","
    period: str = "."
    slash: str = "/"

    @staticmethod
    def ctrl(key: str) -> str:
        return f"ctrl+{key}"

    @staticmethod
    def shift(key: str) -> str:
        return f"shift+{key}"

    @staticmethod
    def alt(key: str) -> str:
        return f"alt+{key}"

    @staticmethod
    def ctrlShift(key: str) -> str:
        return f"ctrl+shift+{key}"

    @staticmethod
    def ctrlAlt(key: str) -> str:
        return f"ctrl+alt+{key}"

    @staticmethod
    def shiftAlt(key: str) -> str:
        return f"shift+alt+{key}"

    @staticmethod
    def ctrlShiftAlt(key: str) -> str:
        return f"ctrl+shift+alt+{key}"


Key = _KeyHelper()


def decode_kitty_printable(data: str) -> str | None:
    match = re.match(r"^\x1b\[(\d+)(?::\d*)?(?::\d+)?(?:;(\d+))?(?::(\d+))?u$", data)
    if not match:
        return None
    codepoint = int(match.group(1))
    modifier_value = int(match.group(2) or "1") - 1
    event_type = int(match.group(3) or "1")
    global _last_event_type
    _last_event_type = {1: "press", 2: "repeat", 3: "release"}.get(event_type, "press")
    parts: list[str] = []
    if modifier_value & 4:
        parts.append("ctrl")
    if modifier_value & 2:
        parts.append("alt")
    if modifier_value & 1:
        parts.append("shift")
    try:
        special_names = {
            9: "tab",
            13: "enter",
            27: "escape",
            32: "space",
            127: "backspace",
        }
        char = special_names.get(codepoint, chr(codepoint))
    except ValueError:
        return None
    if parts:
        normalized = char.lower() if len(char) == 1 else char
        return "+".join(parts + [normalized])
    return char


def parse_key(data: str) -> str | None:
    global _last_event_type
    _last_event_type = "press"
    if data in LEGACY_SEQUENCE_KEY_IDS:
        return LEGACY_SEQUENCE_KEY_IDS[data]

    kitty = decode_kitty_printable(data)
    if kitty is not None:
        return kitty

    if data in _SPECIAL_CHARS:
        key_id = _SPECIAL_CHARS[data]
        return "escape" if key_id == "esc" else key_id

    if len(data) == 1:
        code = ord(data)
        if code in _CTRL_CHAR_MAP and code < 32:
            base = _CTRL_CHAR_MAP[code]
            if base in {"tab", "enter", "escape"}:
                return f"ctrl+{base}"
            return f"ctrl+{base}"
        if data.isupper() and data.lower() != data:
            return f"shift+{data.lower()}"
        return data

    if data.startswith("\x1b") and len(data) == 2:
        nested = parse_key(data[1])
        if nested is None:
            return None
        if nested.startswith(("ctrl+", "shift+", "alt+")):
            return f"alt+{nested}"
        return f"alt+{nested}"

    return None


def matches_key(data: str, key_id: str) -> bool:
    parsed = parse_key(data)
    if parsed is None:
        return False
    normalized_expected = "escape" if key_id == "esc" else "enter" if key_id == "return" else key_id
    normalized_parsed = "escape" if parsed == "esc" else "enter" if parsed == "return" else parsed
    return normalized_parsed == normalized_expected


def is_key_release(data: str) -> bool:
    if "\x1b[200~" in data:
        return False
    return ":3" in data


def is_key_repeat(data: str) -> bool:
    if "\x1b[200~" in data:
        return False
    return ":2" in data
