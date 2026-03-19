from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .terminal import Terminal


class Component(Protocol):
    wants_key_release: bool

    def render(self, width: int) -> list[str]: ...

    def invalidate(self) -> None: ...

    def handle_input(self, data: str) -> None: ...


class Focusable(Protocol):
    focused: bool


CURSOR_MARKER = "\x1b_pi:c\x07"


def is_focusable(component: Component | None) -> bool:
    return component is not None and hasattr(component, "focused")


class Container:
    def __init__(self) -> None:
        self.children: list[Component] = []

    def add_child(self, component: Component) -> None:
        self.children.append(component)

    def remove_child(self, component: Component) -> None:
        if component in self.children:
            self.children.remove(component)

    def clear(self) -> None:
        self.children.clear()

    def invalidate(self) -> None:
        for child in self.children:
            child.invalidate()

    def render(self, width: int) -> list[str]:
        lines: list[str] = []
        for child in self.children:
            lines.extend(child.render(width))
        return lines


@dataclass
class OverlayHandle:
    hide: Callable[[], None]
    set_hidden: Callable[[bool], None]
    is_hidden: Callable[[], bool]
    focus: Callable[[], None]
    unfocus: Callable[[], None]
    is_focused: Callable[[], bool]


class TUI(Container):
    def __init__(self, terminal: Terminal, show_hardware_cursor: bool = False) -> None:
        super().__init__()
        self.terminal = terminal
        self.show_hardware_cursor = show_hardware_cursor
        self.previous_lines: list[str] = []
        self.focused_component: Component | None = None
        self.input_listeners: list[Callable[[str], dict[str, str | bool] | None]] = []
        self.overlays: list[dict[str, object]] = []
        self.started = False

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        self.terminal.start(self.handle_input, self.request_render)
        if not self.show_hardware_cursor:
            self.terminal.hide_cursor()
        self.render_now()

    def stop(self) -> None:
        if not self.started:
            return
        self.started = False
        if not self.show_hardware_cursor:
            self.terminal.show_cursor()
        self.terminal.stop()

    def add_input_listener(self, listener: Callable[[str], dict[str, str | bool] | None]) -> Callable[[], None]:
        self.input_listeners.append(listener)

        def remove() -> None:
            if listener in self.input_listeners:
                self.input_listeners.remove(listener)

        return remove

    def set_focus(self, component: Component | None) -> None:
        if is_focusable(self.focused_component):
            setattr(self.focused_component, "focused", False)
        self.focused_component = component
        if is_focusable(component):
            setattr(component, "focused", True)

    def show_overlay(self, component: Component, *, hidden: bool = False, capture_focus: bool = True) -> OverlayHandle:
        overlay = {"component": component, "hidden": hidden, "pre_focus": self.focused_component, "capture_focus": capture_focus}
        self.overlays.append(overlay)
        if capture_focus:
            self.set_focus(component)

        def hide() -> None:
            if overlay in self.overlays:
                self.overlays.remove(overlay)
            if capture_focus:
                self.set_focus(overlay["pre_focus"])  # type: ignore[arg-type]
            self.request_render()

        def set_hidden(value: bool) -> None:
            overlay["hidden"] = value
            self.request_render()

        def is_hidden() -> bool:
            return bool(overlay["hidden"])

        def focus() -> None:
            if capture_focus:
                self.set_focus(component)

        def unfocus() -> None:
            if capture_focus:
                self.set_focus(overlay["pre_focus"])  # type: ignore[arg-type]

        def is_focused() -> bool:
            return self.focused_component is component

        return OverlayHandle(hide=hide, set_hidden=set_hidden, is_hidden=is_hidden, focus=focus, unfocus=unfocus, is_focused=is_focused)

    def request_render(self) -> None:
        self.render_now()

    def render_now(self) -> list[str]:
        lines = self.render(self.terminal.columns)
        for overlay in self.overlays:
            if overlay["hidden"]:
                continue
            component = overlay["component"]
            if isinstance(component, Container):
                lines.extend(component.render(self.terminal.columns))
            else:
                lines.extend(component.render(self.terminal.columns))  # type: ignore[union-attr]
        output = "\n".join(lines)
        if lines != self.previous_lines:
            self.terminal.clear_screen()
            if output:
                self.terminal.write(output)
            self.previous_lines = list(lines)
        return lines

    def handle_input(self, data: str) -> None:
        forwarded = data
        for listener in list(self.input_listeners):
            result = listener(forwarded) or {}
            if result.get("consume"):
                return
            if isinstance(result.get("data"), str):
                forwarded = str(result["data"])
        if self.focused_component is not None and hasattr(self.focused_component, "handle_input"):
            self.focused_component.handle_input(forwarded)
