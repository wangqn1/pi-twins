from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Callable, Protocol


class Terminal(Protocol):
    def start(self, on_input: Callable[[str], None], on_resize: Callable[[], None]) -> None: ...

    def stop(self) -> None: ...

    def drain_input(self, max_ms: int = 1000, idle_ms: int = 50) -> None: ...

    def write(self, data: str) -> None: ...

    @property
    def columns(self) -> int: ...

    @property
    def rows(self) -> int: ...

    @property
    def kitty_protocol_active(self) -> bool: ...

    def move_by(self, lines: int) -> None: ...

    def hide_cursor(self) -> None: ...

    def show_cursor(self) -> None: ...

    def clear_line(self) -> None: ...

    def clear_from_cursor(self) -> None: ...

    def clear_screen(self) -> None: ...

    def set_title(self, title: str) -> None: ...


@dataclass
class MemoryTerminal:
    width: int = 80
    height: int = 24
    output: io.StringIO = field(default_factory=io.StringIO)
    cursor_hidden: bool = False
    started: bool = False
    title: str = ""
    kitty_enabled: bool = False

    def start(self, on_input: Callable[[str], None], on_resize: Callable[[], None]) -> None:
        self.started = True
        self._on_input = on_input
        self._on_resize = on_resize

    def stop(self) -> None:
        self.started = False

    def drain_input(self, max_ms: int = 1000, idle_ms: int = 50) -> None:
        del max_ms, idle_ms

    def write(self, data: str) -> None:
        self.output.write(data)

    @property
    def columns(self) -> int:
        return self.width

    @property
    def rows(self) -> int:
        return self.height

    @property
    def kitty_protocol_active(self) -> bool:
        return self.kitty_enabled

    def move_by(self, lines: int) -> None:
        if lines > 0:
            self.write(f"\x1b[{lines}B")
        elif lines < 0:
            self.write(f"\x1b[{-lines}A")

    def hide_cursor(self) -> None:
        self.cursor_hidden = True
        self.write("\x1b[?25l")

    def show_cursor(self) -> None:
        self.cursor_hidden = False
        self.write("\x1b[?25h")

    def clear_line(self) -> None:
        self.write("\x1b[K")

    def clear_from_cursor(self) -> None:
        self.write("\x1b[J")

    def clear_screen(self) -> None:
        self.write("\x1b[2J\x1b[H")

    def set_title(self, title: str) -> None:
        self.title = title
        self.write(f"\x1b]0;{title}\x07")

    def feed_input(self, data: str) -> None:
        self._on_input(data)

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._on_resize()

    def get_output(self) -> str:
        return self.output.getvalue()


ProcessTerminal = MemoryTerminal
