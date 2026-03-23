# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KillRing:
    ring: list[str] = field(default_factory=list)

    def push(self, text: str, *, prepend: bool, accumulate: bool = False) -> None:
        if not text:
            return
        if accumulate and self.ring:
            last = self.ring.pop()
            self.ring.append(text + last if prepend else last + text)
            return
        self.ring.append(text)

    def peek(self) -> str | None:
        return self.ring[-1] if self.ring else None

    def rotate(self) -> None:
        if len(self.ring) > 1:
            self.ring.insert(0, self.ring.pop())

    @property
    def length(self) -> int:
        return len(self.ring)
