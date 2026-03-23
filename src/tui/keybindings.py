# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass, field

from .keys import matches_key


DEFAULT_EDITOR_KEYBINDINGS: dict[str, list[str]] = {
    "cursorUp": ["up"],
    "cursorDown": ["down"],
    "cursorLeft": ["left", "ctrl+b"],
    "cursorRight": ["right", "ctrl+f"],
    "cursorWordLeft": ["alt+left", "ctrl+left", "alt+b"],
    "cursorWordRight": ["alt+right", "ctrl+right", "alt+f"],
    "cursorLineStart": ["home", "ctrl+a"],
    "cursorLineEnd": ["end", "ctrl+e"],
    "jumpForward": ["ctrl+]"],
    "jumpBackward": ["ctrl+alt+]"],
    "pageUp": ["pageUp"],
    "pageDown": ["pageDown"],
    "deleteCharBackward": ["backspace"],
    "deleteCharForward": ["delete", "ctrl+d"],
    "deleteWordBackward": ["ctrl+w", "alt+backspace"],
    "deleteWordForward": ["alt+d", "alt+delete"],
    "deleteToLineStart": ["ctrl+u"],
    "deleteToLineEnd": ["ctrl+k"],
    "newLine": ["shift+enter"],
    "submit": ["enter"],
    "tab": ["tab"],
    "selectUp": ["up"],
    "selectDown": ["down"],
    "selectPageUp": ["pageUp"],
    "selectPageDown": ["pageDown"],
    "selectConfirm": ["enter"],
    "selectCancel": ["escape", "ctrl+c"],
    "copy": ["ctrl+c"],
    "yank": ["ctrl+y"],
    "yankPop": ["alt+y"],
    "undo": ["ctrl+-"],
    "expandTools": ["ctrl+o"],
    "treeFoldOrUp": ["ctrl+left", "alt+left"],
    "treeUnfoldOrDown": ["ctrl+right", "alt+right"],
    "toggleSessionPath": ["ctrl+p"],
    "toggleSessionSort": ["ctrl+s"],
    "renameSession": ["ctrl+r"],
    "deleteSession": ["ctrl+d"],
    "deleteSessionNoninvasive": ["ctrl+backspace"],
}


@dataclass
class EditorKeybindingsManager:
    config: dict[str, str | list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.action_to_keys: dict[str, list[str]] = {}
        self.build_maps(self.config)

    def build_maps(self, config: dict[str, str | list[str]]) -> None:
        self.action_to_keys = {action: list(keys) for action, keys in DEFAULT_EDITOR_KEYBINDINGS.items()}
        for action, keys in config.items():
            self.action_to_keys[action] = [keys] if isinstance(keys, str) else list(keys)

    def matches(self, data: str, action: str) -> bool:
        return any(matches_key(data, key) for key in self.action_to_keys.get(action, []))

    def get_keys(self, action: str) -> list[str]:
        return list(self.action_to_keys.get(action, []))

    def set_config(self, config: dict[str, str | list[str]]) -> None:
        self.config = dict(config)
        self.build_maps(self.config)


_global_editor_keybindings: EditorKeybindingsManager | None = None


def get_editor_keybindings() -> EditorKeybindingsManager:
    global _global_editor_keybindings
    if _global_editor_keybindings is None:
        _global_editor_keybindings = EditorKeybindingsManager()
    return _global_editor_keybindings


def set_editor_keybindings(manager: EditorKeybindingsManager) -> None:
    global _global_editor_keybindings
    _global_editor_keybindings = manager
