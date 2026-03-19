from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

EventHandler = Callable[[Any], Any]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def emit(self, channel: str, data: Any) -> None:
        for handler in list(self._handlers.get(channel, [])):
            try:
                handler(data)
            except Exception:  # noqa: BLE001
                continue

    def on(self, channel: str, handler: EventHandler) -> Callable[[], None]:
        self._handlers[channel].append(handler)

        def unsubscribe() -> None:
            handlers = self._handlers.get(channel)
            if handlers is None:
                return
            if handler in handlers:
                handlers.remove(handler)
            if not handlers:
                self._handlers.pop(channel, None)

        return unsubscribe

    def clear(self) -> None:
        self._handlers.clear()


def create_event_bus() -> EventBus:
    return EventBus()
