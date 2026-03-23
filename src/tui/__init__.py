# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass, field

from .autocomplete import AutocompleteItem, AutocompleteProvider, CombinedAutocompleteProvider, SlashCommand
from .components import (
    Box,
    CancellableLoader,
    DefaultTextStyle,
    Editor,
    EditorTheme,
    Input,
    Loader,
    Markdown,
    MarkdownTheme,
    SelectItem,
    SelectList,
    SettingItem,
    SettingsList,
    Spacer,
    Text,
    TextChunk,
    TruncatedText,
    word_wrap_line,
)
from .editor_component import EditorComponent
from .fuzzy import FuzzyMatch, fuzzy_filter, fuzzy_match
from .kill_ring import KillRing
from .keybindings import DEFAULT_EDITOR_KEYBINDINGS, EditorKeybindingsManager, get_editor_keybindings, set_editor_keybindings
from .keys import Key, decode_kitty_printable, is_key_release, is_key_repeat, is_kitty_protocol_active, matches_key, parse_key, set_kitty_protocol_active
from .stdin_buffer import StdinBuffer, StdinBufferOptions, extract_complete_sequences, is_complete_sequence
from .terminal import MemoryTerminal, ProcessTerminal, Terminal
from .tui import CURSOR_MARKER, Component, Container, Focusable, OverlayHandle, TUI, is_focusable
from .undo_stack import UndoStack
from .utils import extract_ansi_code, truncate_to_width, visible_width, wrap_text_with_ansi


@dataclass
class TuiBuffer:
    lines: list[str] = field(default_factory=list)

    def write(self, text: str) -> None:
        self.lines.extend(text.splitlines() or [""])


__all__ = [
    "CURSOR_MARKER",
    "Component",
    "Container",
    "AutocompleteItem",
    "AutocompleteProvider",
    "Box",
    "CancellableLoader",
    "CombinedAutocompleteProvider",
    "DefaultTextStyle",
    "DEFAULT_EDITOR_KEYBINDINGS",
    "Editor",
    "EditorComponent",
    "EditorTheme",
    "EditorKeybindingsManager",
    "Focusable",
    "FuzzyMatch",
    "Input",
    "Key",
    "KillRing",
    "Loader",
    "Markdown",
    "MarkdownTheme",
    "MemoryTerminal",
    "OverlayHandle",
    "ProcessTerminal",
    "SlashCommand",
    "SelectItem",
    "SelectList",
    "SettingItem",
    "SettingsList",
    "Spacer",
    "StdinBuffer",
    "StdinBufferOptions",
    "TUI",
    "Terminal",
    "Text",
    "TextChunk",
    "TruncatedText",
    "TuiBuffer",
    "UndoStack",
    "decode_kitty_printable",
    "extract_ansi_code",
    "extract_complete_sequences",
    "fuzzy_filter",
    "fuzzy_match",
    "get_editor_keybindings",
    "is_complete_sequence",
    "is_focusable",
    "is_key_release",
    "is_key_repeat",
    "is_kitty_protocol_active",
    "matches_key",
    "parse_key",
    "set_editor_keybindings",
    "set_kitty_protocol_active",
    "truncate_to_width",
    "visible_width",
    "word_wrap_line",
    "wrap_text_with_ansi",
]
