from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tui import (
    AutocompleteItem,
    Box,
    CancellableLoader,
    CombinedAutocompleteProvider,
    CURSOR_MARKER,
    DefaultTextStyle,
    Editor,
    EditorTheme,
    EditorKeybindingsManager,
    Input,
    Key,
    KillRing,
    Loader,
    Markdown,
    MarkdownTheme,
    MemoryTerminal,
    SelectItem,
    SelectList,
    SettingItem,
    SettingsList,
    Spacer,
    StdinBuffer,
    TUI,
    Text,
    TextChunk,
    TruncatedText,
    Container,
    TuiBuffer,
    UndoStack,
    decode_kitty_printable,
    extract_complete_sequences,
    fuzzy_filter,
    fuzzy_match,
    is_key_release,
    is_key_repeat,
    matches_key,
    parse_key,
    set_kitty_protocol_active,
    truncate_to_width,
    visible_width,
    word_wrap_line,
)


@dataclass
class _Label:
    text: str
    focused: bool = False
    wants_key_release: bool = False
    inputs: list[str] | None = None

    def render(self, width: int) -> list[str]:
        return [self.text[:width]]

    def invalidate(self) -> None:
        return None

    def handle_input(self, data: str) -> None:
        if self.inputs is None:
            self.inputs = []
        self.inputs.append(data)


def test_fuzzy_match_and_filter_rank_results() -> None:
    assert fuzzy_match("abc", "a_b_c").matches is True
    assert fuzzy_match("10x", "x10").matches is True
    items = ["pods start", "mom start", "pods stop"]
    result = fuzzy_filter(items, "po st", lambda item: item)
    assert result == ["pods start", "pods stop"]


def test_extract_complete_sequences_handles_escape_and_plain_text() -> None:
    sequences, remainder = extract_complete_sequences("\x1b[Aab")
    assert sequences == ["\x1b[A", "a", "b"]
    assert remainder == ""


def test_stdin_buffer_emits_paste_and_partial_escape() -> None:
    buffer = StdinBuffer()
    events: list[tuple[str, str]] = []
    buffer.on_data(lambda value: events.append(("data", value)))
    buffer.on_paste(lambda value: events.append(("paste", value)))

    buffer.process("\x1b")
    assert events == []
    assert buffer.flush() == ["\x1b"]

    buffer.process("\x1b[200~hello world\x1b[201~")
    assert events[-1] == ("paste", "hello world")


def test_visible_width_and_truncate_to_width_ignore_ansi() -> None:
    text = "\x1b[31mhello\x1b[0m世界"
    assert visible_width(text) == 9
    assert truncate_to_width(text, 7, "...").endswith("...")


def test_tui_buffer_and_container_render_lines() -> None:
    buffer = TuiBuffer()
    buffer.write("a\nb")
    assert buffer.lines == ["a", "b"]

    container = Container()
    container.add_child(_Label("one"))
    container.add_child(_Label("two"))
    assert container.render(10) == ["one", "two"]


def test_tui_renders_to_memory_terminal_and_forwards_input() -> None:
    terminal = MemoryTerminal(width=20, height=5)
    tui = TUI(terminal)
    label = _Label("hello")
    tui.add_child(label)
    tui.set_focus(label)
    tui.start()

    output = terminal.get_output()
    assert "\x1b[2J\x1b[H" in output
    assert "hello" in output
    assert terminal.cursor_hidden is True

    terminal.feed_input("x")
    assert label.inputs == ["x"]

    overlay = tui.show_overlay(_Label("modal"))
    tui.render_now()
    assert "modal" in terminal.get_output()
    assert overlay.is_focused() is True

    overlay.hide()
    tui.stop()
    assert terminal.cursor_hidden is False


def test_parse_key_matches_legacy_meta_and_kitty_sequences() -> None:
    set_kitty_protocol_active(True)
    assert parse_key("\x1b[A") == "up"
    assert parse_key("\x03") == "ctrl+c"
    assert parse_key("A") == "shift+a"
    assert parse_key("\x1bb") == "alt+left"
    assert decode_kitty_printable("\x1b[97;5u") == "ctrl+a"
    assert matches_key("\x1b[97;5u", "ctrl+a") is True
    assert is_key_repeat("\x1b[97;5:2u") is True
    assert is_key_release("\x1b[97;5:3u") is True


def test_editor_keybindings_manager_overrides_defaults() -> None:
    manager = EditorKeybindingsManager({"submit": ["ctrl+j"], "cursorLeft": "alt+h"})
    assert manager.matches("\n", "submit") is True
    assert manager.get_keys("cursorLeft") == ["alt+h"]
    assert manager.matches("\x1bh", "cursorLeft") is True


class _SlashCommand:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description

    def get_argument_completions(self, argument_prefix: str) -> list[AutocompleteItem] | None:
        if argument_prefix.startswith("mo"):
            return [AutocompleteItem(value="model", label="model")]
        return None


def test_combined_autocomplete_provider_handles_commands_and_paths(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")

    provider = CombinedAutocompleteProvider(commands=[_SlashCommand("help"), _SlashCommand("open")], base_path=tmp_path.as_posix())

    command = provider.get_suggestions(["/he"], 0, 3)
    assert command is not None
    command_items = command["items"]
    assert isinstance(command_items, list)
    assert command_items[0].value == "help"

    applied = provider.apply_completion(["/he"], 0, 3, command_items[0], command["prefix"])
    assert applied["lines"] == ["/help "]

    path_suggestions = provider.get_suggestions(["src/m"], 0, 5)
    assert path_suggestions is not None
    path_items = path_suggestions["items"]
    assert isinstance(path_items, list)
    assert any(item.label == "main.py" for item in path_items)

    force = provider.get_force_file_suggestions([""], 0, 0)
    assert force is not None


def test_combined_autocomplete_provider_handles_at_file_fuzzy_search(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "manual.md").write_text("# manual\n", encoding="utf-8")
    (tmp_path / "module.py").write_text("pass\n", encoding="utf-8")

    provider = CombinedAutocompleteProvider(base_path=tmp_path.as_posix())
    suggestions = provider.get_suggestions(['@"man'], 0, 5)
    assert suggestions is not None
    items = suggestions["items"]
    assert isinstance(items, list)
    assert any("manual" in item.label for item in items)


def test_kill_ring_push_peek_rotate_and_accumulate() -> None:
    ring = KillRing()
    ring.push("abc", prepend=False)
    ring.push("def", prepend=False, accumulate=True)
    assert ring.peek() == "abcdef"
    ring.push("<<", prepend=True, accumulate=True)
    assert ring.peek() == "<<abcdef"
    ring.push("older", prepend=False)
    ring.rotate()
    assert ring.ring[0] == "older"
    assert ring.length == 2


def test_undo_stack_clones_state_and_pops_latest_snapshot() -> None:
    stack: UndoStack[dict[str, object]] = UndoStack()
    state = {"text": ["a"], "cursor": 1}
    stack.push(state)
    state["text"].append("b")  # type: ignore[union-attr]
    stack.push(state)

    latest = stack.pop()
    assert latest == {"text": ["a", "b"], "cursor": 1}
    latest["text"].append("c")  # type: ignore[union-attr]

    previous = stack.pop()
    assert previous == {"text": ["a"], "cursor": 1}
    assert stack.length == 0


def test_text_spacer_box_and_truncated_text_render_expected_lines() -> None:
    text = Text("hello world", padding_x=1, padding_y=1)
    text_lines = text.render(8)
    assert text_lines[0] == " " * 8
    assert any("hello" in line for line in text_lines)

    spacer = Spacer(2)
    assert spacer.render(10) == ["", ""]

    box = Box(padding_x=1, padding_y=1)
    box.add_child(Text("abc", padding_x=0, padding_y=0))
    box_lines = box.render(8)
    assert box_lines[0] == " " * 8
    assert any("abc" in line for line in box_lines)

    truncated = TruncatedText("123456789\nsecond", padding_x=1, padding_y=1)
    truncated_lines = truncated.render(6)
    assert len(truncated_lines) == 3
    assert truncated_lines[1].strip() == "1234"


def test_loader_and_cancellable_loader_update_and_abort() -> None:
    terminal = MemoryTerminal(width=20, height=5)
    tui = TUI(terminal)
    tui.start()

    loader = Loader(tui, lambda text: f"<{text}>", lambda text: text.upper(), "working")
    initial_lines = loader.render(20)
    assert any("WORKING" in line for line in initial_lines)
    loader.tick()
    ticked_lines = loader.render(20)
    assert initial_lines != ticked_lines
    loader.set_message("done")
    assert any("DONE" in line for line in loader.render(20))
    loader.stop()

    cancellable = CancellableLoader(tui, lambda text: text, lambda text: text, "cancel me")
    aborted: list[bool] = []
    cancellable.on_abort = lambda: aborted.append(True)
    cancellable.handle_input("\x1b")
    assert cancellable.aborted is True
    assert aborted == [True]
    cancellable.dispose()
    tui.stop()


def test_input_supports_editing_kill_ring_undo_and_submit() -> None:
    submitted: list[str] = []
    escaped: list[bool] = []
    input_component = Input(on_submit=submitted.append, on_escape=lambda: escaped.append(True), focused=True)

    input_component.handle_input("h")
    input_component.handle_input("i")
    assert input_component.get_value() == "hi"

    input_component.handle_input("\x01")
    input_component.handle_input("!")
    assert input_component.get_value() == "!hi"

    input_component.handle_input("\x0b")
    assert input_component.get_value() == "!"

    input_component.handle_input("\x19")
    assert input_component.get_value() == "!hi"

    input_component.handle_input("\x1b")
    assert escaped == [True]

    input_component.handle_input("\r")
    assert submitted == ["!hi"]

    rendered = input_component.render(10)[0]
    assert CURSOR_MARKER in rendered

    input_component.handle_input("\x1f")
    assert input_component.get_value() == "!"

    input_component.handle_input("\x1b[200~paste\x1b[201~")
    assert input_component.get_value().endswith("paste")

    input_component.handle_input("\x1f")
    assert input_component.get_value() == "!"


def test_select_list_filters_wraps_and_invokes_callbacks() -> None:
    theme = {
        "selectedPrefix": lambda text: text,
        "selectedText": lambda text: f"[{text}]",
        "description": lambda text: f"({text})",
        "scrollInfo": lambda text: f"<{text}>",
        "noMatch": lambda text: text,
    }
    items = [
        SelectItem(value="help", label="Help", description="show help"),
        SelectItem(value="open", label="Open"),
        SelectItem(value="close", label="Close"),
    ]
    select = SelectList(items, max_visible=2, theme=theme)
    changes: list[str] = []
    selected: list[str] = []
    cancelled: list[bool] = []
    select.on_selection_change = lambda item: changes.append(item.value)
    select.on_select = lambda item: selected.append(item.value)
    select.on_cancel = lambda: cancelled.append(True)

    select.set_filter("o")
    assert [item.value for item in select.filtered_items] == ["open"]
    select.set_filter("")
    select.handle_input("\x1b[B")
    assert changes[-1] == "open"
    select.handle_input("\r")
    assert selected == ["open"]
    select.handle_input("\x1b")
    assert cancelled == [True]
    assert select.get_selected_item() is not None


def test_settings_list_supports_cycle_search_and_submenu() -> None:
    theme = {
        "label": lambda text, selected: f">{text}<" if selected else text,
        "value": lambda text, selected: f"[{text}]" if selected else text,
        "description": lambda text: text,
        "cursor": "->",
        "hint": lambda text: text,
    }
    changes: list[tuple[str, str]] = []
    cancelled: list[bool] = []

    submenu_done: list[Callable[[str | None], None]] = []

    def submenu_factory(current: str, done):  # noqa: ANN001
        del current
        submenu_done.append(done)
        return Text("submenu", padding_x=0, padding_y=0)

    settings = SettingsList(
        items=[
            SettingItem(id="mode", label="Mode", current_value="auto", values=["auto", "manual"], description="mode desc"),
            SettingItem(id="theme", label="Theme", current_value="light", submenu=submenu_factory),
        ],
        max_visible=5,
        theme=theme,
        on_change=lambda item_id, value: changes.append((item_id, value)),
        on_cancel=lambda: cancelled.append(True),
        enable_search=True,
    )

    lines = settings.render(40)
    assert any("Mode" in line for line in lines)
    settings.handle_input("Mod")
    assert settings.filtered_items[0].id == "mode"

    settings.handle_input("\r")
    assert changes[-1] == ("mode", "manual")

    settings.apply_filter("")
    settings.handle_input("\x1b[B")
    settings.handle_input("\r")
    assert settings.submenu_component is not None
    submenu_done[-1]("dark")
    assert changes[-1] == ("theme", "dark")
    assert settings.submenu_component is None

    settings.handle_input("\x1b")
    assert cancelled == [True]


def test_markdown_renders_headings_lists_quotes_links_and_code() -> None:
    theme = MarkdownTheme(
        heading=lambda text: f"<h>{text}</h>",
        link=lambda text: f"<a>{text}</a>",
        link_url=lambda text: f"<u>{text}</u>",
        code=lambda text: f"`{text}`",
        code_block=lambda text: f"[code]{text}[/code]",
        code_block_border=lambda text: f"[border]{text}[/border]",
        quote=lambda text: f"<q>{text}</q>",
        quote_border=lambda text: f"<b>{text}</b>",
        hr=lambda text: f"<hr>{text}</hr>",
        list_bullet=lambda text: f"({text})",
        bold=lambda text: f"<strong>{text}</strong>",
        italic=lambda text: f"<em>{text}</em>",
        strikethrough=lambda text: f"<del>{text}</del>",
        underline=lambda text: f"<ins>{text}</ins>",
    )
    markdown = Markdown(
        text=(
            "# Title\n\n"
            "A [link](https://example.com) with `code` and **bold**.\n\n"
            "> quote line\n\n"
            "- item one\n- item two\n\n"
            "```py\nprint('x')\n```\n"
        ),
        padding_x=1,
        padding_y=1,
        theme=theme,
        default_text_style=DefaultTextStyle(color=lambda text: f"<c>{text}</c>"),
    )

    lines = markdown.render(60)
    joined = "\n".join(lines)
    assert "<h>" in joined
    assert "<a>link</a>" in joined
    assert "<u>(https://example.com)</u>" in joined
    assert "`code`" in joined
    assert "<strong>bold</strong>" in joined
    assert "<b>│ </b><q>" in joined
    assert "(-)" in joined or "(*)" in joined
    assert "[border]```py[/border]" in joined
    assert "[code]print('x')[/code]" in joined


def test_word_wrap_line_splits_long_line_at_boundaries() -> None:
    chunks = word_wrap_line("hello world wide", 7)
    assert [chunk.text for chunk in chunks] == ["hello", "world", "wide"]
    assert chunks[0] == TextChunk(text="hello", start_index=0, end_index=6)


def test_editor_supports_multiline_history_autocomplete_and_submit(tmp_path: Path) -> None:
    terminal = MemoryTerminal(width=40, height=12)
    tui = TUI(terminal)
    tui.start()

    theme = EditorTheme(
        border_color=lambda text: text,
        select_list={
            "selectedPrefix": lambda text: text,
            "selectedText": lambda text: f"[{text}]",
            "description": lambda text: text,
            "scrollInfo": lambda text: text,
            "noMatch": lambda text: text,
        },
    )
    submitted: list[str] = []
    changed: list[str] = []
    editor = Editor(tui=tui, theme=theme)
    editor.focused = True
    editor.on_submit = submitted.append
    editor.on_change = changed.append
    editor.set_autocomplete_provider(CombinedAutocompleteProvider(commands=[_SlashCommand("help")], base_path=tmp_path.as_posix()))

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")

    editor.handle_input("h")
    editor.handle_input("i")
    assert editor.get_text() == "hi"

    editor.handle_input("\x1b[13;2u")
    assert editor.get_text() == "hi\n"

    editor.handle_input("x")
    assert editor.get_text() == "hi\nx"

    editor.handle_input("\x1b[A")
    editor.handle_input("\x1b[H")
    editor.handle_input("!")
    assert editor.get_text() == "!hi\nx"

    editor.set_text("/h")
    editor.handle_input("e")
    assert editor.autocomplete_list is not None
    editor.handle_input("\r")
    assert editor.get_text() == "/help "

    editor.add_to_history("first prompt")
    editor.add_to_history("second prompt")
    editor.set_text("")
    editor.handle_input("\x1b[A")
    assert editor.get_text() == "second prompt"

    editor.set_text("submit me")
    editor.handle_input("\r")
    assert submitted[-1] == "submit me"

    rendered = "\n".join(editor.render(40))
    assert CURSOR_MARKER in rendered or "\x1b[7m" in rendered
    assert changed
    tui.stop()
