# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Generic, TypeVar


S = TypeVar("S")


@dataclass
class UndoStack(Generic[S]):
    stack: list[S] = field(default_factory=list)

    def push(self, state: S) -> None:
        self.stack.append(deepcopy(state))

    def pop(self) -> S | None:
        return self.stack.pop() if self.stack else None

    def clear(self) -> None:
        self.stack.clear()

    @property
    def length(self) -> int:
        return len(self.stack)
