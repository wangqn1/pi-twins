# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Callable

from .fuzzy import fuzzy_filter
from .keybindings import get_editor_keybindings
from .keys import decode_kitty_printable
from .kill_ring import KillRing
from .tui import CURSOR_MARKER, Component, TUI
from .undo_stack import UndoStack
from .utils import apply_background_to_line, truncate_to_width, visible_width, wrap_text_with_ansi


@dataclass
class Text(Component):
    text: str = ""
    padding_x: int = 1
    padding_y: int = 1
    custom_bg_fn: Callable[[str], str] | None = None
    wants_key_release: bool = False
    _cached_text: str | None = None
    _cached_width: int | None = None
    _cached_lines: list[str] | None = None

    def set_text(self, text: str) -> None:
        self.text = text
        self.invalidate()

    def set_custom_bg_fn(self, custom_bg_fn: Callable[[str], str] | None = None) -> None:
        self.custom_bg_fn = custom_bg_fn
        self.invalidate()

    def invalidate(self) -> None:
        self._cached_text = None
        self._cached_width = None
        self._cached_lines = None

    def handle_input(self, data: str) -> None:
        del data

    def render(self, width: int) -> list[str]:
        if self._cached_lines is not None and self._cached_text == self.text and self._cached_width == width:
            return self._cached_lines
        if not self.text or not self.text.strip():
            self._cached_text = self.text
            self._cached_width = width
            self._cached_lines = []
            return []

        normalized = self.text.replace("\t", "   ")
        content_width = max(1, width - self.padding_x * 2)
        wrapped_lines = wrap_text_with_ansi(normalized, content_width)
        left_margin = " " * self.padding_x
        right_margin = " " * self.padding_x
        content_lines: list[str] = []
        for line in wrapped_lines:
            line_with_margins = left_margin + line + right_margin
            if self.custom_bg_fn:
                content_lines.append(apply_background_to_line(line_with_margins, width, self.custom_bg_fn))
            else:
                pad = max(0, width - visible_width(line_with_margins))
                content_lines.append(line_with_margins + (" " * pad))

        empty_line = " " * width
        empty_lines = [
            apply_background_to_line(empty_line, width, self.custom_bg_fn) if self.custom_bg_fn else empty_line
            for _ in range(self.padding_y)
        ]
        result = [*empty_lines, *content_lines, *empty_lines]
        self._cached_text = self.text
        self._cached_width = width
        self._cached_lines = result
        return result or [""]


@dataclass
class Spacer(Component):
    lines: int = 1
    wants_key_release: bool = False

    def set_lines(self, lines: int) -> None:
        self.lines = lines

    def invalidate(self) -> None:
        return None

    def handle_input(self, data: str) -> None:
        del data

    def render(self, width: int) -> list[str]:
        del width
        return ["" for _ in range(self.lines)]


@dataclass
class TruncatedText(Component):
    text: str
    padding_x: int = 0
    padding_y: int = 0
    wants_key_release: bool = False

    def invalidate(self) -> None:
        return None

    def handle_input(self, data: str) -> None:
        del data

    def render(self, width: int) -> list[str]:
        result: list[str] = []
        empty_line = " " * width
        result.extend(empty_line for _ in range(self.padding_y))
        available_width = max(1, width - self.padding_x * 2)
        single_line_text = self.text.split("\n", 1)[0]
        display_text = truncate_to_width(single_line_text, available_width)
        line_with_padding = (" " * self.padding_x) + display_text + (" " * self.padding_x)
        pad = max(0, width - visible_width(line_with_padding))
        result.append(line_with_padding + (" " * pad))
        result.extend(empty_line for _ in range(self.padding_y))
        return result


@dataclass
class Box(Component):
    padding_x: int = 1
    padding_y: int = 1
    bg_fn: Callable[[str], str] | None = None
    children: list[Component] = field(default_factory=list)
    wants_key_release: bool = False
    _cache: dict[str, object] | None = None

    def add_child(self, component: Component) -> None:
        self.children.append(component)
        self._cache = None

    def remove_child(self, component: Component) -> None:
        if component in self.children:
            self.children.remove(component)
            self._cache = None

    def clear(self) -> None:
        self.children.clear()
        self._cache = None

    def set_bg_fn(self, bg_fn: Callable[[str], str] | None = None) -> None:
        self.bg_fn = bg_fn

    def invalidate(self) -> None:
        self._cache = None
        for child in self.children:
            child.invalidate()

    def handle_input(self, data: str) -> None:
        del data

    def render(self, width: int) -> list[str]:
        if not self.children:
            return []
        content_width = max(1, width - self.padding_x * 2)
        left_pad = " " * self.padding_x
        child_lines: list[str] = []
        for child in self.children:
            for line in child.render(content_width):
                child_lines.append(left_pad + line)
        if not child_lines:
            return []
        bg_sample = self.bg_fn("test") if self.bg_fn else None
        if self._cache and self._cache["width"] == width and self._cache["bg_sample"] == bg_sample and self._cache["child_lines"] == child_lines:
            return self._cache["lines"]  # type: ignore[return-value]

        result: list[str] = []
        for _ in range(self.padding_y):
            result.append(self._apply_bg("", width))
        for line in child_lines:
            result.append(self._apply_bg(line, width))
        for _ in range(self.padding_y):
            result.append(self._apply_bg("", width))
        self._cache = {"width": width, "bg_sample": bg_sample, "child_lines": child_lines, "lines": result}
        return result

    def _apply_bg(self, line: str, width: int) -> str:
        pad = max(0, width - visible_width(line))
        padded = line + (" " * pad)
        return apply_background_to_line(padded, width, self.bg_fn) if self.bg_fn else padded


class Loader(Text):
    def __init__(
        self,
        ui: TUI,
        spinner_color_fn: Callable[[str], str],
        message_color_fn: Callable[[str], str],
        message: str = "Loading...",
    ) -> None:
        super().__init__("", 1, 0)
        self.frames = ["|", "/", "-", "\\"]
        self.current_frame = 0
        self.interval: threading.Timer | None = None
        self.ui = ui
        self.spinner_color_fn = spinner_color_fn
        self.message_color_fn = message_color_fn
        self.message = message
        self.start()

    def render(self, width: int) -> list[str]:
        return ["", *super().render(width)]

    def start(self) -> None:
        self.update_display()

    def stop(self) -> None:
        if self.interval is not None:
            self.interval.cancel()
            self.interval = None

    def tick(self) -> None:
        self.current_frame = (self.current_frame + 1) % len(self.frames)
        self.update_display()

    def set_message(self, message: str) -> None:
        self.message = message
        self.update_display()

    def update_display(self) -> None:
        frame = self.frames[self.current_frame]
        self.set_text(f"{self.spinner_color_fn(frame)} {self.message_color_fn(self.message)}")
        self.ui.request_render()


class CancellableLoader(Loader):
    def __init__(
        self,
        ui: TUI,
        spinner_color_fn: Callable[[str], str],
        message_color_fn: Callable[[str], str],
        message: str = "Loading...",
    ) -> None:
        super().__init__(ui, spinner_color_fn, message_color_fn, message)
        self.aborted = False
        self.on_abort: Callable[[], None] | None = None

    def handle_input(self, data: str) -> None:
        if get_editor_keybindings().matches(data, "selectCancel"):
            self.aborted = True
            if self.on_abort is not None:
                self.on_abort()

    def dispose(self) -> None:
        self.stop()


def _is_whitespace_char(value: str) -> bool:
    return bool(value) and value.isspace()


def _is_punctuation_char(value: str) -> bool:
    return bool(value) and not value.isalnum() and not value.isspace()


def _prev_char_boundary(text: str, cursor: int) -> int:
    return max(0, cursor - 1)


def _next_char_boundary(text: str, cursor: int) -> int:
    return min(len(text), cursor + 1)


@dataclass
class Input(Component):
    value: str = ""
    cursor: int = 0
    focused: bool = False
    wants_key_release: bool = False
    on_submit: Callable[[str], None] | None = None
    on_escape: Callable[[], None] | None = None
    paste_buffer: str = ""
    is_in_paste: bool = False
    kill_ring: KillRing = field(default_factory=KillRing)
    last_action: str | None = None
    undo_stack: UndoStack[dict[str, int | str]] = field(default_factory=UndoStack)

    def get_value(self) -> str:
        return self.value

    def set_value(self, value: str) -> None:
        self.value = value
        self.cursor = min(self.cursor, len(self.value))

    def invalidate(self) -> None:
        return None

    def handle_input(self, data: str) -> None:
        if "\x1b[200~" in data:
            self.is_in_paste = True
            self.paste_buffer = ""
            data = data.replace("\x1b[200~", "")
        if self.is_in_paste:
            self.paste_buffer += data
            end_index = self.paste_buffer.find("\x1b[201~")
            if end_index != -1:
                paste_content = self.paste_buffer[:end_index]
                self.handle_paste(paste_content)
                remaining = self.paste_buffer[end_index + 6 :]
                self.is_in_paste = False
                self.paste_buffer = ""
                if remaining:
                    self.handle_input(remaining)
            return

        kb = get_editor_keybindings()
        if kb.matches(data, "selectCancel"):
            if self.on_escape is not None:
                self.on_escape()
            return
        if kb.matches(data, "undo"):
            self.undo()
            return
        if kb.matches(data, "submit") or data == "\n":
            if self.on_submit is not None:
                self.on_submit(self.value)
            return
        if kb.matches(data, "deleteCharBackward"):
            self.handle_backspace()
            return
        if kb.matches(data, "deleteCharForward"):
            self.handle_forward_delete()
            return
        if kb.matches(data, "deleteWordBackward"):
            self.delete_word_backwards()
            return
        if kb.matches(data, "deleteWordForward"):
            self.delete_word_forward()
            return
        if kb.matches(data, "deleteToLineStart"):
            self.delete_to_line_start()
            return
        if kb.matches(data, "deleteToLineEnd"):
            self.delete_to_line_end()
            return
        if kb.matches(data, "yank"):
            self.yank()
            return
        if kb.matches(data, "yankPop"):
            self.yank_pop()
            return
        if kb.matches(data, "cursorLeft"):
            self.last_action = None
            self.cursor = _prev_char_boundary(self.value, self.cursor)
            return
        if kb.matches(data, "cursorRight"):
            self.last_action = None
            self.cursor = _next_char_boundary(self.value, self.cursor)
            return
        if kb.matches(data, "cursorLineStart"):
            self.last_action = None
            self.cursor = 0
            return
        if kb.matches(data, "cursorLineEnd"):
            self.last_action = None
            self.cursor = len(self.value)
            return
        if kb.matches(data, "cursorWordLeft"):
            self.move_word_backwards()
            return
        if kb.matches(data, "cursorWordRight"):
            self.move_word_forwards()
            return

        kitty_printable = decode_kitty_printable(data)
        if kitty_printable is not None and len(kitty_printable) == 1:
            self.insert_character(kitty_printable)
            return

        has_control = any((ord(char) < 32 or ord(char) == 0x7F or (0x80 <= ord(char) <= 0x9F)) for char in data)
        if not has_control:
            self.insert_character(data)

    def render(self, width: int) -> list[str]:
        content_width = max(1, width - 2)
        value = self.value
        cursor = min(self.cursor, len(value))
        start = 0
        while visible_width(value[start:cursor]) > max(0, content_width - 1):
            start += 1
        visible = value[start:]
        while visible_width(visible) > content_width:
            visible = visible[:-1]
        if self.focused:
            marker_index = cursor - start
            visible = visible[:marker_index] + CURSOR_MARKER + visible[marker_index:]
        line = " " + visible
        pad = max(0, width - visible_width(line.replace(CURSOR_MARKER, "")))
        return [line + (" " * pad)]

    def insert_character(self, char: str) -> None:
        if _is_whitespace_char(char) or self.last_action != "type-word":
            self.push_undo()
        self.last_action = "type-word"
        self.value = self.value[: self.cursor] + char + self.value[self.cursor :]
        self.cursor += len(char)

    def handle_backspace(self) -> None:
        self.last_action = None
        if self.cursor == 0:
            return
        self.push_undo()
        previous = _prev_char_boundary(self.value, self.cursor)
        self.value = self.value[:previous] + self.value[self.cursor :]
        self.cursor = previous

    def handle_forward_delete(self) -> None:
        self.last_action = None
        if self.cursor >= len(self.value):
            return
        self.push_undo()
        next_pos = _next_char_boundary(self.value, self.cursor)
        self.value = self.value[: self.cursor] + self.value[next_pos:]

    def delete_to_line_start(self) -> None:
        if self.cursor == 0:
            return
        self.push_undo()
        deleted = self.value[: self.cursor]
        self.kill_ring.push(deleted, prepend=True, accumulate=self.last_action == "kill")
        self.last_action = "kill"
        self.value = self.value[self.cursor :]
        self.cursor = 0

    def delete_to_line_end(self) -> None:
        if self.cursor >= len(self.value):
            return
        self.push_undo()
        deleted = self.value[self.cursor :]
        self.kill_ring.push(deleted, prepend=False, accumulate=self.last_action == "kill")
        self.last_action = "kill"
        self.value = self.value[: self.cursor]

    def delete_word_backwards(self) -> None:
        if self.cursor == 0:
            return
        was_kill = self.last_action == "kill"
        self.push_undo()
        old_cursor = self.cursor
        self.move_word_backwards()
        delete_from = self.cursor
        self.cursor = old_cursor
        deleted = self.value[delete_from:self.cursor]
        self.kill_ring.push(deleted, prepend=True, accumulate=was_kill)
        self.last_action = "kill"
        self.value = self.value[:delete_from] + self.value[self.cursor :]
        self.cursor = delete_from

    def delete_word_forward(self) -> None:
        if self.cursor >= len(self.value):
            return
        was_kill = self.last_action == "kill"
        self.push_undo()
        old_cursor = self.cursor
        self.move_word_forwards()
        delete_to = self.cursor
        self.cursor = old_cursor
        deleted = self.value[self.cursor:delete_to]
        self.kill_ring.push(deleted, prepend=False, accumulate=was_kill)
        self.last_action = "kill"
        self.value = self.value[: self.cursor] + self.value[delete_to:]

    def move_word_backwards(self) -> None:
        self.last_action = None
        if self.cursor == 0:
            return
        position = self.cursor
        while position > 0 and _is_whitespace_char(self.value[position - 1]):
            position -= 1
        while position > 0 and _is_punctuation_char(self.value[position - 1]):
            position -= 1
        while position > 0 and not _is_whitespace_char(self.value[position - 1]) and not _is_punctuation_char(self.value[position - 1]):
            position -= 1
        self.cursor = position

    def move_word_forwards(self) -> None:
        self.last_action = None
        position = self.cursor
        length = len(self.value)
        while position < length and _is_whitespace_char(self.value[position]):
            position += 1
        while position < length and _is_punctuation_char(self.value[position]):
            position += 1
        while position < length and not _is_whitespace_char(self.value[position]) and not _is_punctuation_char(self.value[position]):
            position += 1
        self.cursor = position

    def yank(self) -> None:
        text = self.kill_ring.peek()
        if not text:
            return
        self.push_undo()
        self.value = self.value[: self.cursor] + text + self.value[self.cursor :]
        self.cursor += len(text)
        self.last_action = "yank"

    def yank_pop(self) -> None:
        if self.last_action != "yank" or self.kill_ring.length <= 1:
            return
        self.push_undo()
        previous = self.kill_ring.peek() or ""
        self.value = self.value[: self.cursor - len(previous)] + self.value[self.cursor :]
        self.cursor -= len(previous)
        self.kill_ring.rotate()
        current = self.kill_ring.peek() or ""
        self.value = self.value[: self.cursor] + current + self.value[self.cursor :]
        self.cursor += len(current)
        self.last_action = "yank"

    def handle_paste(self, content: str) -> None:
        if not content:
            return
        self.push_undo()
        self.value = self.value[: self.cursor] + content + self.value[self.cursor :]
        self.cursor += len(content)
        self.last_action = None

    def push_undo(self) -> None:
        self.undo_stack.push({"value": self.value, "cursor": self.cursor})

    def undo(self) -> None:
        previous = self.undo_stack.pop()
        if previous is None:
            return
        self.value = str(previous["value"])
        self.cursor = int(previous["cursor"])
        self.last_action = None


@dataclass(frozen=True)
class SelectItem:
    value: str
    label: str
    description: str | None = None


@dataclass
class SelectList(Component):
    items: list[SelectItem]
    max_visible: int
    theme: dict[str, Callable[[str], str]]
    filtered_items: list[SelectItem] = field(init=False)
    selected_index: int = 0
    wants_key_release: bool = False
    on_select: Callable[[SelectItem], None] | None = None
    on_cancel: Callable[[], None] | None = None
    on_selection_change: Callable[[SelectItem], None] | None = None

    def __post_init__(self) -> None:
        self.filtered_items = list(self.items)

    def set_filter(self, filter_value: str) -> None:
        lowered = filter_value.lower()
        self.filtered_items = [item for item in self.items if item.value.lower().startswith(lowered)]
        self.selected_index = 0

    def set_selected_index(self, index: int) -> None:
        if not self.filtered_items:
            self.selected_index = 0
            return
        self.selected_index = max(0, min(index, len(self.filtered_items) - 1))

    def invalidate(self) -> None:
        return None

    def render(self, width: int) -> list[str]:
        if not self.filtered_items:
            return [self.theme["noMatch"]("  No matching commands")]
        lines: list[str] = []
        start_index = max(0, min(self.selected_index - (self.max_visible // 2), len(self.filtered_items) - self.max_visible))
        end_index = min(start_index + self.max_visible, len(self.filtered_items))
        for index in range(start_index, end_index):
            item = self.filtered_items[index]
            description = " ".join((item.description or "").split())
            if index == self.selected_index:
                if description and width > 40:
                    value = truncate_to_width(item.label or item.value, min(30, width - 6))
                    spacing = " " * max(1, 32 - len(value))
                    remaining = width - 2 - len(value) - len(spacing)
                    line = self.theme["selectedText"](f"→ {value}{spacing}{truncate_to_width(description, remaining)}")
                else:
                    line = self.theme["selectedText"](f"→ {truncate_to_width(item.label or item.value, width - 4)}")
            else:
                if description and width > 40:
                    value = truncate_to_width(item.label or item.value, min(30, width - 6))
                    spacing = " " * max(1, 32 - len(value))
                    remaining = width - 2 - len(value) - len(spacing)
                    line = "  " + value + self.theme["description"](spacing + truncate_to_width(description, remaining))
                else:
                    line = "  " + truncate_to_width(item.label or item.value, width - 4)
            lines.append(line)
        if start_index > 0 or end_index < len(self.filtered_items):
            lines.append(self.theme["scrollInfo"](truncate_to_width(f"  ({self.selected_index + 1}/{len(self.filtered_items)})", width - 2)))
        return lines

    def handle_input(self, key_data: str) -> None:
        kb = get_editor_keybindings()
        if not self.filtered_items:
            if kb.matches(key_data, "selectCancel") and self.on_cancel is not None:
                self.on_cancel()
            return
        if kb.matches(key_data, "selectUp"):
            self.selected_index = len(self.filtered_items) - 1 if self.selected_index == 0 else self.selected_index - 1
            self._notify_selection_change()
        elif kb.matches(key_data, "selectDown"):
            self.selected_index = 0 if self.selected_index == len(self.filtered_items) - 1 else self.selected_index + 1
            self._notify_selection_change()
        elif kb.matches(key_data, "selectConfirm"):
            selected = self.filtered_items[self.selected_index]
            if self.on_select is not None:
                self.on_select(selected)
        elif kb.matches(key_data, "selectCancel"):
            if self.on_cancel is not None:
                self.on_cancel()

    def _notify_selection_change(self) -> None:
        if self.on_selection_change is not None and self.filtered_items:
            self.on_selection_change(self.filtered_items[self.selected_index])

    def get_selected_item(self) -> SelectItem | None:
        return self.filtered_items[self.selected_index] if self.filtered_items else None


@dataclass
class SettingItem:
    id: str
    label: str
    current_value: str
    description: str | None = None
    values: list[str] | None = None
    submenu: Callable[[str, Callable[[str | None], None]], Component] | None = None


@dataclass
class SettingsList(Component):
    items: list[SettingItem]
    max_visible: int
    theme: dict[str, object]
    on_change: Callable[[str, str], None]
    on_cancel: Callable[[], None]
    enable_search: bool = False
    selected_index: int = 0
    filtered_items: list[SettingItem] = field(init=False)
    search_input: Input | None = field(init=False, default=None)
    submenu_component: Component | None = None
    submenu_item_index: int | None = None
    wants_key_release: bool = False

    def __post_init__(self) -> None:
        self.filtered_items = list(self.items)
        if self.enable_search:
            self.search_input = Input()

    def update_value(self, item_id: str, new_value: str) -> None:
        for item in self.items:
            if item.id == item_id:
                item.current_value = new_value
                return

    def invalidate(self) -> None:
        if self.submenu_component is not None:
            self.submenu_component.invalidate()

    def render(self, width: int) -> list[str]:
        if self.submenu_component is not None:
            return self.submenu_component.render(width)
        return self.render_main_list(width)

    def render_main_list(self, width: int) -> list[str]:
        lines: list[str] = []
        if self.enable_search and self.search_input is not None:
            lines.extend(self.search_input.render(width))
            lines.append("")
        if not self.items:
            lines.append(self.theme["hint"]("  No settings available"))  # type: ignore[index]
            if self.enable_search:
                self.add_hint_line(lines, width)
            return lines
        display_items = self.filtered_items if self.enable_search else self.items
        if not display_items:
            lines.append(truncate_to_width(self.theme["hint"]("  No matching settings"), width))  # type: ignore[index]
            self.add_hint_line(lines, width)
            return lines
        start_index = max(0, min(self.selected_index - (self.max_visible // 2), len(display_items) - self.max_visible))
        end_index = min(start_index + self.max_visible, len(display_items))
        max_label_width = min(30, max(visible_width(item.label) for item in self.items))
        for index in range(start_index, end_index):
            item = display_items[index]
            is_selected = index == self.selected_index
            prefix = self.theme["cursor"] if is_selected else "  "  # type: ignore[index]
            prefix_width = visible_width(prefix)
            label_padded = item.label + (" " * max(0, max_label_width - visible_width(item.label)))
            label_text = self.theme["label"](label_padded, is_selected)  # type: ignore[index]
            separator = "  "
            used_width = prefix_width + max_label_width + visible_width(separator)
            value_max_width = width - used_width - 2
            value_text = self.theme["value"](truncate_to_width(item.current_value, value_max_width), is_selected)  # type: ignore[index]
            lines.append(truncate_to_width(prefix + label_text + separator + value_text, width))
        if start_index > 0 or end_index < len(display_items):
            lines.append(self.theme["hint"](truncate_to_width(f"  ({self.selected_index + 1}/{len(display_items)})", width - 2)))  # type: ignore[index]
        selected_item = display_items[self.selected_index] if display_items else None
        if selected_item and selected_item.description:
            lines.append("")
            for line in wrap_text_with_ansi(selected_item.description, width - 4):
                lines.append(self.theme["description"](f"  {line}"))  # type: ignore[index]
        self.add_hint_line(lines, width)
        return lines

    def handle_input(self, data: str) -> None:
        if self.submenu_component is not None:
            if hasattr(self.submenu_component, "handle_input"):
                self.submenu_component.handle_input(data)
            return
        kb = get_editor_keybindings()
        display_items = self.filtered_items if self.enable_search else self.items
        if kb.matches(data, "selectUp"):
            if display_items:
                self.selected_index = len(display_items) - 1 if self.selected_index == 0 else self.selected_index - 1
        elif kb.matches(data, "selectDown"):
            if display_items:
                self.selected_index = 0 if self.selected_index == len(display_items) - 1 else self.selected_index + 1
        elif kb.matches(data, "selectConfirm") or data == " ":
            self.activate_item()
        elif kb.matches(data, "selectCancel"):
            self.on_cancel()
        elif self.enable_search and self.search_input is not None:
            sanitized = data.replace(" ", "")
            if not sanitized:
                return
            self.search_input.handle_input(sanitized)
            self.apply_filter(self.search_input.get_value())

    def activate_item(self) -> None:
        item = (self.filtered_items if self.enable_search else self.items)[self.selected_index]
        if item.submenu is not None:
            self.submenu_item_index = self.selected_index
            self.submenu_component = item.submenu(item.current_value, self._submenu_done)
            return
        if item.values:
            current_index = item.values.index(item.current_value) if item.current_value in item.values else -1
            next_index = (current_index + 1) % len(item.values)
            new_value = item.values[next_index]
            item.current_value = new_value
            self.on_change(item.id, new_value)

    def _submenu_done(self, selected_value: str | None = None) -> None:
        if selected_value is not None:
            item = (self.filtered_items if self.enable_search else self.items)[self.selected_index]
            item.current_value = selected_value
            self.on_change(item.id, selected_value)
        self.close_submenu()

    def close_submenu(self) -> None:
        self.submenu_component = None
        if self.submenu_item_index is not None:
            self.selected_index = self.submenu_item_index
            self.submenu_item_index = None

    def apply_filter(self, query: str) -> None:
        self.filtered_items = fuzzy_filter(self.items, query, lambda item: item.label)
        self.selected_index = 0

    def add_hint_line(self, lines: list[str], width: int) -> None:
        lines.append("")
        hint = "  Type to search · Enter/Space to change · Esc to cancel" if self.enable_search else "  Enter/Space to change · Esc to cancel"
        lines.append(truncate_to_width(self.theme["hint"](hint), width))  # type: ignore[index]


@dataclass
class DefaultTextStyle:
    color: Callable[[str], str] | None = None
    bg_color: Callable[[str], str] | None = None
    bold: bool = False
    italic: bool = False
    strikethrough: bool = False
    underline: bool = False


@dataclass
class MarkdownTheme:
    heading: Callable[[str], str]
    link: Callable[[str], str]
    link_url: Callable[[str], str]
    code: Callable[[str], str]
    code_block: Callable[[str], str]
    code_block_border: Callable[[str], str]
    quote: Callable[[str], str]
    quote_border: Callable[[str], str]
    hr: Callable[[str], str]
    list_bullet: Callable[[str], str]
    bold: Callable[[str], str]
    italic: Callable[[str], str]
    strikethrough: Callable[[str], str]
    underline: Callable[[str], str]
    highlight_code: Callable[[str, str | None], list[str]] | None = None
    code_block_indent: str = "  "


@dataclass
class Markdown(Component):
    text: str
    padding_x: int
    padding_y: int
    theme: MarkdownTheme
    default_text_style: DefaultTextStyle | None = None
    wants_key_release: bool = False
    _cached_text: str | None = None
    _cached_width: int | None = None
    _cached_lines: list[str] | None = None

    def set_text(self, text: str) -> None:
        self.text = text
        self.invalidate()

    def invalidate(self) -> None:
        self._cached_text = None
        self._cached_width = None
        self._cached_lines = None

    def handle_input(self, data: str) -> None:
        del data

    def render(self, width: int) -> list[str]:
        if self._cached_lines is not None and self._cached_text == self.text and self._cached_width == width:
            return self._cached_lines
        content_width = max(1, width - self.padding_x * 2)
        if not self.text or not self.text.strip():
            self._cached_text = self.text
            self._cached_width = width
            self._cached_lines = []
            return []

        normalized = self.text.replace("\t", "   ")
        rendered_lines = self._render_blocks(normalized.splitlines(), content_width)
        left_margin = " " * self.padding_x
        right_margin = " " * self.padding_x
        bg_fn = self.default_text_style.bg_color if self.default_text_style else None
        content_lines: list[str] = []
        for line in rendered_lines:
            if line == "":
                line_with_margins = left_margin + right_margin
            else:
                line_with_margins = left_margin + line + right_margin
            if bg_fn:
                content_lines.append(apply_background_to_line(line_with_margins, width, bg_fn))
            else:
                pad = max(0, width - visible_width(line_with_margins))
                content_lines.append(line_with_margins + (" " * pad))

        empty_line = " " * width
        empty_lines = [apply_background_to_line(empty_line, width, bg_fn) if bg_fn else empty_line for _ in range(self.padding_y)]
        result = [*empty_lines, *content_lines, *empty_lines]
        self._cached_text = self.text
        self._cached_width = width
        self._cached_lines = result
        return result or [""]

    def _apply_default_style(self, text: str) -> str:
        if self.default_text_style is None:
            return text
        styled = text
        if self.default_text_style.color:
            styled = self.default_text_style.color(styled)
        if self.default_text_style.bold:
            styled = self.theme.bold(styled)
        if self.default_text_style.italic:
            styled = self.theme.italic(styled)
        if self.default_text_style.strikethrough:
            styled = self.theme.strikethrough(styled)
        if self.default_text_style.underline:
            styled = self.theme.underline(styled)
        return styled

    def _render_inline(self, text: str) -> str:
        text = self._apply_default_style(text)
        text = re.sub(r"`([^`]+)`", lambda m: self.theme.code(m.group(1)), text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f"{self.theme.link(m.group(1))} {self.theme.link_url(f'({m.group(2)})')}", text)
        text = re.sub(r"\*\*([^*]+)\*\*", lambda m: self.theme.bold(m.group(1)), text)
        text = re.sub(r"__([^_]+)__", lambda m: self.theme.underline(m.group(1)), text)
        text = re.sub(r"\*([^*]+)\*", lambda m: self.theme.italic(m.group(1)), text)
        text = re.sub(r"~~([^~]+)~~", lambda m: self.theme.strikethrough(m.group(1)), text)
        return text

    def _render_blocks(self, lines: list[str], width: int) -> list[str]:
        output: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if stripped == "":
                if output and output[-1] != "":
                    output.append("")
                index += 1
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                heading_text = self._render_inline(heading_match.group(2))
                if level == 1:
                    output.append(self.theme.heading(self.theme.bold(self.theme.underline(heading_text))))
                elif level == 2:
                    output.append(self.theme.heading(self.theme.bold(heading_text)))
                else:
                    output.append(self.theme.heading(self.theme.bold(f"{'#' * level} {heading_text}")))
                output.append("")
                index += 1
                continue

            if re.match(r"^(```|~~~)", stripped):
                fence = stripped[:3]
                lang = stripped[3:].strip() or None
                code_lines: list[str] = []
                index += 1
                while index < len(lines) and not lines[index].strip().startswith(fence):
                    code_lines.append(lines[index])
                    index += 1
                if index < len(lines):
                    index += 1
                output.append(self.theme.code_block_border(f"```{lang or ''}"))
                if self.theme.highlight_code:
                    for rendered in self.theme.highlight_code("\n".join(code_lines), lang):
                        output.append(f"{self.theme.code_block_indent}{rendered}")
                else:
                    for code_line in code_lines:
                        output.append(f"{self.theme.code_block_indent}{self.theme.code_block(code_line)}")
                output.append(self.theme.code_block_border("```"))
                output.append("")
                continue

            if re.match(r"^([-*_])(?:\s*\1){2,}$", stripped):
                output.append(self.theme.hr("-" * max(3, width)))
                output.append("")
                index += 1
                continue

            if stripped.startswith(">"):
                quote_lines: list[str] = []
                while index < len(lines) and lines[index].strip().startswith(">"):
                    quote_lines.append(lines[index].strip()[1:].lstrip())
                    index += 1
                for quote_line in quote_lines:
                    for wrapped in wrap_text_with_ansi(self._render_inline(quote_line), max(1, width - 2)):
                        output.append(self.theme.quote_border("│ ") + self.theme.quote(wrapped))
                output.append("")
                continue

            list_match = re.match(r"^((?:[-+*])|(?:\d+\.))\s+(.*)$", stripped)
            if list_match:
                while index < len(lines):
                    current = lines[index].strip()
                    match = re.match(r"^((?:[-+*])|(?:\d+\.))\s+(.*)$", current)
                    if not match:
                        break
                    bullet = self.theme.list_bullet(match.group(1))
                    item_text = self._render_inline(match.group(2))
                    wrapped = wrap_text_with_ansi(item_text, max(1, width - 3))
                    for wrapped_index, wrapped_line in enumerate(wrapped):
                        prefix = f"{bullet} " if wrapped_index == 0 else "  "
                        output.append(prefix + wrapped_line)
                    index += 1
                output.append("")
                continue

            paragraph_lines = [stripped]
            index += 1
            while index < len(lines):
                current = lines[index].strip()
                if current == "":
                    break
                if re.match(r"^(#{1,6})\s+", current) or current.startswith(">") or re.match(r"^(```|~~~)", current) or re.match(r"^((?:[-+*])|(?:\d+\.))\s+", current):
                    break
                paragraph_lines.append(current)
                index += 1
            paragraph = self._render_inline(" ".join(paragraph_lines))
            output.extend(wrap_text_with_ansi(paragraph, width))
            output.append("")

        while output and output[-1] == "":
            output.pop()
        return output


@dataclass(frozen=True)
class TextChunk:
    text: str
    start_index: int
    end_index: int


def word_wrap_line(line: str, max_width: int) -> list[TextChunk]:
    if not line or max_width <= 0:
        return [TextChunk(text="", start_index=0, end_index=0)]
    if visible_width(line) <= max_width:
        return [TextChunk(text=line, start_index=0, end_index=len(line))]

    chunks: list[TextChunk] = []
    current = ""
    chunk_start = 0
    last_space_break: tuple[int, int] | None = None

    for index, char in enumerate(line):
        candidate = current + char
        if char.isspace():
            last_space_break = (index + 1, visible_width(candidate))
        if visible_width(candidate) > max_width and current:
            if last_space_break is not None and last_space_break[0] > chunk_start:
                break_index = last_space_break[0]
                chunk_text = line[chunk_start:break_index].rstrip()
                chunks.append(TextChunk(text=chunk_text, start_index=chunk_start, end_index=break_index))
                chunk_start = break_index
                current = line[chunk_start:index + 1].lstrip()
                last_space_break = None
            else:
                chunks.append(TextChunk(text=current, start_index=chunk_start, end_index=index))
                chunk_start = index
                current = char
        else:
            current = candidate

    chunks.append(TextChunk(text=line[chunk_start:], start_index=chunk_start, end_index=len(line)))
    return chunks


@dataclass
class EditorTheme:
    border_color: Callable[[str], str]
    select_list: dict[str, Callable[[str], str]]


@dataclass
class Editor(Component):
    tui: TUI
    theme: EditorTheme
    padding_x: int = 0
    autocomplete_max_visible: int = 5
    focused: bool = False
    wants_key_release: bool = False
    on_submit: Callable[[str], None] | None = None
    on_change: Callable[[str], None] | None = None
    disable_submit: bool = False
    border_color: Callable[[str], str] | None = None
    lines: list[str] = field(default_factory=lambda: [""])
    cursor_line: int = 0
    cursor_col: int = 0
    last_width: int = 80
    scroll_offset: int = 0
    autocomplete_provider: object | None = None
    autocomplete_list: SelectList | None = None
    autocomplete_state: str | None = None
    autocomplete_prefix: str = ""
    history: list[str] = field(default_factory=list)
    history_index: int = -1
    kill_ring: KillRing = field(default_factory=KillRing)
    last_action: str | None = None
    undo_stack: UndoStack[dict[str, object]] = field(default_factory=UndoStack)

    def __post_init__(self) -> None:
        if self.border_color is None:
            self.border_color = self.theme.border_color

    def invalidate(self) -> None:
        return None

    def get_text(self) -> str:
        return "\n".join(self.lines)

    def get_expanded_text(self) -> str:
        return self.get_text()

    def set_text(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        self.lines = normalized.split("\n") or [""]
        if not self.lines:
            self.lines = [""]
        self.cursor_line = len(self.lines) - 1
        self.cursor_col = len(self.lines[self.cursor_line])
        self.scroll_offset = 0
        if self.on_change is not None:
            self.on_change(self.get_text())

    def set_text_internal(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        self.lines = normalized.split("\n") or [""]
        if not self.lines:
            self.lines = [""]
        self.cursor_line = len(self.lines) - 1
        self.cursor_col = len(self.lines[self.cursor_line])
        self.scroll_offset = 0
        if self.on_change is not None:
            self.on_change(self.get_text())

    def add_to_history(self, text: str) -> None:
        trimmed = text.strip()
        if not trimmed:
            return
        if self.history and self.history[0] == trimmed:
            return
        self.history.insert(0, trimmed)
        if len(self.history) > 100:
            self.history.pop()

    def is_editor_empty(self) -> bool:
        return len(self.lines) == 1 and self.lines[0] == ""

    def navigate_history(self, direction: int) -> None:
        if not self.history:
            return
        new_index = self.history_index - direction
        if new_index < -1 or new_index >= len(self.history):
            return
        self.history_index = new_index
        if self.history_index == -1:
            self.set_text_internal("")
        else:
            self.set_text_internal(self.history[self.history_index])

    def set_padding_x(self, padding: int) -> None:
        self.padding_x = max(0, int(padding))

    def set_autocomplete_max_visible(self, max_visible: int) -> None:
        self.autocomplete_max_visible = max(3, min(20, int(max_visible)))
        if self.autocomplete_list is not None:
            self.autocomplete_list.max_visible = self.autocomplete_max_visible

    def set_autocomplete_provider(self, provider) -> None:  # noqa: ANN001
        self.autocomplete_provider = provider

    def insert_text_at_cursor(self, text: str) -> None:
        self.push_undo_snapshot()
        for char in text:
            if char == "\n":
                current = self.lines[self.cursor_line]
                before = current[: self.cursor_col]
                after = current[self.cursor_col :]
                self.lines[self.cursor_line] = before
                self.lines.insert(self.cursor_line + 1, after)
                self.cursor_line += 1
                self.cursor_col = 0
            else:
                line = self.lines[self.cursor_line]
                self.lines[self.cursor_line] = line[: self.cursor_col] + char + line[self.cursor_col :]
                self.cursor_col += 1
        self.history_index = -1
        if self.on_change is not None:
            self.on_change(self.get_text())

    def handle_input(self, data: str) -> None:
        kb = get_editor_keybindings()

        if self.autocomplete_state and self.autocomplete_list is not None:
            if kb.matches(data, "selectCancel"):
                self.clear_autocomplete()
                return
            if kb.matches(data, "selectUp") or kb.matches(data, "selectDown"):
                self.autocomplete_list.handle_input(data)
                return
            if kb.matches(data, "selectConfirm"):
                selected = self.autocomplete_list.get_selected_item()
                if selected is not None and self.autocomplete_provider is not None:
                    applied = self.autocomplete_provider.apply_completion(  # type: ignore[attr-defined]
                        self.lines,
                        self.cursor_line,
                        self.cursor_col,
                        selected,
                        self.autocomplete_prefix,
                    )
                    self.lines = list(applied["lines"])
                    self.cursor_line = int(applied["cursorLine"])
                    self.cursor_col = int(applied["cursorCol"])
                    self.clear_autocomplete()
                    if self.on_change is not None:
                        self.on_change(self.get_text())
                return

        if kb.matches(data, "submit") and not self.disable_submit:
            if self.on_submit is not None:
                self.on_submit(self.get_text())
            return
        if kb.matches(data, "newLine"):
            self.insert_text_at_cursor("\n")
            return
        if kb.matches(data, "undo"):
            self.undo()
            return
        if kb.matches(data, "deleteCharBackward"):
            self.backspace()
            return
        if kb.matches(data, "deleteCharForward"):
            self.delete_forward()
            return
        if kb.matches(data, "cursorLeft"):
            self.move_left()
            return
        if kb.matches(data, "cursorRight"):
            self.move_right()
            return
        if kb.matches(data, "cursorUp"):
            if self.history and (self.is_editor_empty() or self.cursor_line == 0):
                self.navigate_history(-1)
                return
            self.move_vertical(-1)
            return
        if kb.matches(data, "cursorDown"):
            if self.history_index != -1 and self.cursor_line == len(self.lines) - 1:
                self.navigate_history(1)
                return
            self.move_vertical(1)
            return
        if kb.matches(data, "cursorLineStart"):
            self.cursor_col = 0
            return
        if kb.matches(data, "cursorLineEnd"):
            self.cursor_col = len(self.lines[self.cursor_line])
            return
        if kb.matches(data, "tab"):
            if self.try_open_autocomplete(force=True):
                return
            self.insert_text_at_cursor("\t")
            return

        kitty = decode_kitty_printable(data)
        if kitty is not None and len(kitty) == 1:
            self.insert_text_at_cursor(kitty)
            self.try_open_autocomplete(force=False)
            return

        if data == "\n":
            self.insert_text_at_cursor("\n")
            return

        has_control = any((ord(ch) < 32 or ord(ch) == 0x7F or (0x80 <= ord(ch) <= 0x9F)) for ch in data)
        if not has_control:
            self.insert_text_at_cursor(data)
            self.try_open_autocomplete(force=False)

    def render(self, width: int) -> list[str]:
        max_padding = max(0, (width - 1) // 2)
        padding_x = min(self.padding_x, max_padding)
        content_width = max(1, width - padding_x * 2)
        layout_width = max(1, content_width - (0 if padding_x else 1))
        self.last_width = layout_width

        horizontal = (self.border_color or (lambda text: text))("─")
        layout_lines = self.layout_text(layout_width)
        cursor_line_index = next((index for index, line in enumerate(layout_lines) if line["has_cursor"]), 0)
        terminal_rows = self.tui.terminal.rows
        max_visible = max(5, int(terminal_rows * 0.3))
        if cursor_line_index < self.scroll_offset:
            self.scroll_offset = cursor_line_index
        elif cursor_line_index >= self.scroll_offset + max_visible:
            self.scroll_offset = cursor_line_index - max_visible + 1
        max_scroll = max(0, len(layout_lines) - max_visible)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))
        visible_lines = layout_lines[self.scroll_offset : self.scroll_offset + max_visible]

        result: list[str] = []
        left_padding = " " * padding_x
        right_padding = left_padding
        if self.scroll_offset > 0:
            indicator = f"─── ↑ {self.scroll_offset} more "
            result.append((self.border_color or (lambda text: text))(indicator + ("─" * max(0, width - visible_width(indicator)))))
        else:
            result.append(horizontal * width)

        emit_cursor = self.focused and not self.autocomplete_state
        for layout in visible_lines:
            display_text = layout["text"]
            line_visible_width = visible_width(display_text)
            if layout["has_cursor"]:
                marker = CURSOR_MARKER if emit_cursor else ""
                cursor_pos = int(layout["cursor_pos"])
                before = display_text[:cursor_pos]
                after = display_text[cursor_pos:]
                if after:
                    display_text = before + marker + "\x1b[7m" + after[0] + "\x1b[0m" + after[1:]
                else:
                    display_text = before + marker + "\x1b[7m \x1b[0m"
                    line_visible_width += 1
            padding = " " * max(0, content_width - line_visible_width)
            result.append(f"{left_padding}{display_text}{padding}{right_padding}")

        lines_below = len(layout_lines) - (self.scroll_offset + len(visible_lines))
        if lines_below > 0:
            indicator = f"─── ↓ {lines_below} more "
            result.append((self.border_color or (lambda text: text))(indicator + ("─" * max(0, width - visible_width(indicator)))))
        else:
            result.append(horizontal * width)

        if self.autocomplete_state and self.autocomplete_list is not None:
            for line in self.autocomplete_list.render(content_width):
                line_width = visible_width(line)
                result.append(f"{left_padding}{line}{' ' * max(0, content_width - line_width)}{right_padding}")
        return result

    def layout_text(self, width: int) -> list[dict[str, object]]:
        layout_lines: list[dict[str, object]] = []
        for line_index, line in enumerate(self.lines):
            chunks = word_wrap_line(line, width)
            if not chunks:
                chunks = [TextChunk(text="", start_index=0, end_index=0)]
            for chunk in chunks:
                has_cursor = line_index == self.cursor_line and chunk.start_index <= self.cursor_col <= chunk.end_index
                cursor_pos = self.cursor_col - chunk.start_index if has_cursor else None
                layout_lines.append({"text": chunk.text, "has_cursor": has_cursor, "cursor_pos": cursor_pos})
        if not layout_lines:
            layout_lines.append({"text": "", "has_cursor": True, "cursor_pos": 0})
        return layout_lines

    def clear_autocomplete(self) -> None:
        self.autocomplete_state = None
        self.autocomplete_list = None
        self.autocomplete_prefix = ""

    def try_open_autocomplete(self, *, force: bool) -> bool:
        if self.autocomplete_provider is None:
            return False
        if force:
            suggestions = self.autocomplete_provider.get_force_file_suggestions(self.lines, self.cursor_line, self.cursor_col)  # type: ignore[attr-defined]
            self.autocomplete_state = "force" if suggestions else None
        else:
            suggestions = self.autocomplete_provider.get_suggestions(self.lines, self.cursor_line, self.cursor_col)  # type: ignore[attr-defined]
            self.autocomplete_state = "regular" if suggestions else None
        if not suggestions:
            self.clear_autocomplete()
            return False
        items = list(suggestions["items"])
        self.autocomplete_prefix = str(suggestions["prefix"])
        self.autocomplete_list = SelectList(items=items, max_visible=self.autocomplete_max_visible, theme=self.theme.select_list)
        return True

    def move_left(self) -> None:
        if self.cursor_col > 0:
            self.cursor_col -= 1
        elif self.cursor_line > 0:
            self.cursor_line -= 1
            self.cursor_col = len(self.lines[self.cursor_line])

    def move_right(self) -> None:
        if self.cursor_col < len(self.lines[self.cursor_line]):
            self.cursor_col += 1
        elif self.cursor_line < len(self.lines) - 1:
            self.cursor_line += 1
            self.cursor_col = 0

    def move_vertical(self, direction: int) -> None:
        next_line = self.cursor_line + direction
        if 0 <= next_line < len(self.lines):
            self.cursor_line = next_line
            self.cursor_col = min(self.cursor_col, len(self.lines[self.cursor_line]))

    def backspace(self) -> None:
        if self.cursor_col > 0:
            self.push_undo_snapshot()
            line = self.lines[self.cursor_line]
            self.lines[self.cursor_line] = line[: self.cursor_col - 1] + line[self.cursor_col :]
            self.cursor_col -= 1
        elif self.cursor_line > 0:
            self.push_undo_snapshot()
            previous = self.lines[self.cursor_line - 1]
            current = self.lines.pop(self.cursor_line)
            self.cursor_line -= 1
            self.cursor_col = len(previous)
            self.lines[self.cursor_line] = previous + current
        if self.on_change is not None:
            self.on_change(self.get_text())

    def delete_forward(self) -> None:
        line = self.lines[self.cursor_line]
        if self.cursor_col < len(line):
            self.push_undo_snapshot()
            self.lines[self.cursor_line] = line[: self.cursor_col] + line[self.cursor_col + 1 :]
        elif self.cursor_line < len(self.lines) - 1:
            self.push_undo_snapshot()
            next_line = self.lines.pop(self.cursor_line + 1)
            self.lines[self.cursor_line] = line + next_line
        if self.on_change is not None:
            self.on_change(self.get_text())

    def push_undo_snapshot(self) -> None:
        self.undo_stack.push(
            {
                "lines": list(self.lines),
                "cursor_line": self.cursor_line,
                "cursor_col": self.cursor_col,
            }
        )

    def undo(self) -> None:
        previous = self.undo_stack.pop()
        if previous is None:
            return
        self.lines = list(previous["lines"])  # type: ignore[arg-type]
        self.cursor_line = int(previous["cursor_line"])
        self.cursor_col = int(previous["cursor_col"])
        if self.on_change is not None:
            self.on_change(self.get_text())
