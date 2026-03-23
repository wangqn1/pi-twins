# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable


ESC = "\x1b"
BRACKETED_PASTE_START = "\x1b[200~"
BRACKETED_PASTE_END = "\x1b[201~"


def _is_complete_csi_sequence(data: str) -> str:
    if not data.startswith(f"{ESC}["):
        return "complete"
    if len(data) < 3:
        return "incomplete"

    payload = data[2:]
    last_char = payload[-1]
    last_code = ord(last_char)
    if 0x40 <= last_code <= 0x7E:
        if payload.startswith("<"):
            if len(payload) >= 2 and last_char in {"M", "m"}:
                parts = payload[1:-1].split(";")
                if len(parts) == 3 and all(part.isdigit() for part in parts):
                    return "complete"
            return "incomplete"
        return "complete"
    return "incomplete"


def _is_complete_osc_sequence(data: str) -> str:
    if not data.startswith(f"{ESC}]"):
        return "complete"
    return "complete" if data.endswith(f"{ESC}\\") or data.endswith("\x07") else "incomplete"


def _is_complete_dcs_sequence(data: str) -> str:
    if not data.startswith(f"{ESC}P"):
        return "complete"
    return "complete" if data.endswith(f"{ESC}\\") else "incomplete"


def _is_complete_apc_sequence(data: str) -> str:
    if not data.startswith(f"{ESC}_"):
        return "complete"
    return "complete" if data.endswith(f"{ESC}\\") else "incomplete"


def is_complete_sequence(data: str) -> str:
    if not data.startswith(ESC):
        return "not-escape"
    if len(data) == 1:
        return "incomplete"
    after_esc = data[1:]
    if after_esc.startswith("["):
        if after_esc.startswith("[M"):
            return "complete" if len(data) >= 6 else "incomplete"
        return _is_complete_csi_sequence(data)
    if after_esc.startswith("]"):
        return _is_complete_osc_sequence(data)
    if after_esc.startswith("P"):
        return _is_complete_dcs_sequence(data)
    if after_esc.startswith("_"):
        return _is_complete_apc_sequence(data)
    if after_esc.startswith("O"):
        return "complete" if len(after_esc) >= 2 else "incomplete"
    return "complete" if len(after_esc) == 1 else "complete"


def extract_complete_sequences(buffer: str) -> tuple[list[str], str]:
    sequences: list[str] = []
    pos = 0
    while pos < len(buffer):
        remaining = buffer[pos:]
        if remaining.startswith(ESC):
            seq_end = 1
            while seq_end <= len(remaining):
                candidate = remaining[:seq_end]
                status = is_complete_sequence(candidate)
                if status == "complete":
                    sequences.append(candidate)
                    pos += seq_end
                    break
                if status == "incomplete":
                    seq_end += 1
                    continue
                sequences.append(candidate)
                pos += seq_end
                break
            else:
                return sequences, remaining
        else:
            sequences.append(remaining[0])
            pos += 1
    return sequences, ""


@dataclass
class StdinBufferOptions:
    timeout: float = 0.01


class StdinBuffer:
    def __init__(self, options: StdinBufferOptions | None = None) -> None:
        self.options = options or StdinBufferOptions()
        self.buffer = ""
        self.paste_mode = False
        self.paste_buffer = ""
        self._timer: threading.Timer | None = None
        self._data_handlers: list[Callable[[str], None]] = []
        self._paste_handlers: list[Callable[[str], None]] = []

    def on_data(self, handler: Callable[[str], None]) -> None:
        self._data_handlers.append(handler)

    def on_paste(self, handler: Callable[[str], None]) -> None:
        self._paste_handlers.append(handler)

    def process(self, data: str | bytes) -> None:
        self._cancel_timer()

        if isinstance(data, bytes):
            if len(data) == 1 and data[0] > 127:
                chunk = f"\x1b{chr(data[0] - 128)}"
            else:
                chunk = data.decode("utf-8", errors="replace")
        else:
            chunk = data

        if not chunk and not self.buffer:
            self._emit_data("")
            return

        self.buffer += chunk

        if self.paste_mode:
            self.paste_buffer += self.buffer
            self.buffer = ""
            self._process_paste_buffer()
            return

        start_index = self.buffer.find(BRACKETED_PASTE_START)
        if start_index != -1:
            if start_index > 0:
                sequences, _ = extract_complete_sequences(self.buffer[:start_index])
                for sequence in sequences:
                    self._emit_data(sequence)
            self.buffer = self.buffer[start_index + len(BRACKETED_PASTE_START) :]
            self.paste_mode = True
            self.paste_buffer = self.buffer
            self.buffer = ""
            self._process_paste_buffer()
            return

        sequences, remainder = extract_complete_sequences(self.buffer)
        self.buffer = remainder
        for sequence in sequences:
            self._emit_data(sequence)
        if self.buffer:
            self._timer = threading.Timer(self.options.timeout, self._flush_from_timer)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> list[str]:
        self._cancel_timer()
        if not self.buffer:
            return []
        sequences = [self.buffer]
        self.buffer = ""
        return sequences

    def clear(self) -> None:
        self._cancel_timer()
        self.buffer = ""
        self.paste_mode = False
        self.paste_buffer = ""

    def get_buffer(self) -> str:
        return self.buffer

    def destroy(self) -> None:
        self.clear()

    def _emit_data(self, value: str) -> None:
        for handler in list(self._data_handlers):
            handler(value)

    def _emit_paste(self, value: str) -> None:
        for handler in list(self._paste_handlers):
            handler(value)

    def _process_paste_buffer(self) -> None:
        end_index = self.paste_buffer.find(BRACKETED_PASTE_END)
        if end_index == -1:
            return
        pasted_content = self.paste_buffer[:end_index]
        remaining = self.paste_buffer[end_index + len(BRACKETED_PASTE_END) :]
        self.paste_mode = False
        self.paste_buffer = ""
        self._emit_paste(pasted_content)
        if remaining:
            self.process(remaining)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _flush_from_timer(self) -> None:
        self._timer = None
        for sequence in self.flush():
            self._emit_data(sequence)
