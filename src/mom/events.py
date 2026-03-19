from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


@dataclass
class ImmediateEvent:
    channel_id: str
    text: str
    type: str = "immediate"


@dataclass
class OneShotEvent:
    channel_id: str
    text: str
    at: str
    type: str = "one-shot"


@dataclass
class PeriodicEvent:
    channel_id: str
    text: str
    schedule: str
    timezone: str
    type: str = "periodic"


MomEvent = ImmediateEvent | OneShotEvent | PeriodicEvent


def _parse_field(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            values.update(range(minimum, maximum + 1))
            continue
        if "/" in part:
            base, step_raw = part.split("/", 1)
            step = int(step_raw)
            base_values = _parse_field(base or "*", minimum, maximum)
            values.update(value for value in sorted(base_values) if (value - minimum) % step == 0)
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            start = int(start_raw)
            end = int(end_raw)
            values.update(range(start, end + 1))
            continue
        value = int(part)
        if value < minimum or value > maximum:
            raise ValueError(f"Cron field value out of range: {value}")
        values.add(value)
    return values


def next_cron_occurrence(schedule: str, timezone: str, now: float | None = None) -> float:
    parts = schedule.split()
    if len(parts) != 5:
        raise ValueError("Cron schedule must contain 5 fields")
    minute_values = _parse_field(parts[0], 0, 59)
    hour_values = _parse_field(parts[1], 0, 23)
    day_values = _parse_field(parts[2], 1, 31)
    month_values = _parse_field(parts[3], 1, 12)
    weekday_values = _parse_field(parts[4], 0, 6)

    tz = ZoneInfo(timezone)
    current = time.time() if now is None else now
    from datetime import datetime, timedelta

    cursor = datetime.fromtimestamp(current, tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        weekday = (cursor.weekday() + 1) % 7
        if (
            cursor.minute in minute_values
            and cursor.hour in hour_values
            and cursor.day in day_values
            and cursor.month in month_values
            and weekday in weekday_values
        ):
            return cursor.timestamp()
        cursor += timedelta(minutes=1)
    raise ValueError(f"Could not compute next cron occurrence for schedule: {schedule}")


class EventsWatcher:
    def __init__(self, events_dir: str, slack: Any, *, poll_interval: float = 0.2) -> None:
        self.events_dir = Path(events_dir)
        self.slack = slack
        self.poll_interval = poll_interval
        self.start_time = time.time()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._known_files: set[str] = set()
        self._timers: dict[str, threading.Timer] = {}

    def start(self) -> None:
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.scan_once()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        self._known_files.clear()

    def scan_once(self) -> None:
        self.events_dir.mkdir(parents=True, exist_ok=True)
        files = {path.name for path in self.events_dir.glob("*.json")}

        for filename in list(self._known_files - files):
            self._cancel(filename)
            self._known_files.discard(filename)

        for filename in sorted(files):
            self._handle_file(filename)

    def _watch_loop(self) -> None:
        while not self._stop_event.is_set():
            self.scan_once()
            self._stop_event.wait(self.poll_interval)

    def _handle_file(self, filename: str) -> None:
        path = self.events_dir / filename
        if not path.exists():
            return
        if filename in self._known_files:
            return

        event = self._parse_event(path, filename)
        self._known_files.add(filename)
        if event is None:
            self._delete_file(filename)
            return

        if isinstance(event, ImmediateEvent):
            if path.stat().st_mtime < self.start_time:
                self._delete_file(filename)
                return
            self._execute(filename, event, delete_after=True)
            return

        if isinstance(event, OneShotEvent):
            from datetime import datetime

            target = datetime.fromisoformat(event.at.replace("Z", "+00:00")).timestamp()
            if target <= time.time():
                self._delete_file(filename)
                return
            timer = threading.Timer(target - time.time(), lambda: self._execute(filename, event, delete_after=True))
            self._timers[filename] = timer
            timer.daemon = True
            timer.start()
            return

        if isinstance(event, PeriodicEvent):
            try:
                next_run = next_cron_occurrence(event.schedule, event.timezone)
            except Exception:  # noqa: BLE001
                self._delete_file(filename)
                return

            timer = threading.Timer(next_run - time.time(), lambda: self._execute_periodic(filename, event))
            self._timers[filename] = timer
            timer.daemon = True
            timer.start()

    def _execute_periodic(self, filename: str, event: PeriodicEvent) -> None:
        self._execute(filename, event, delete_after=False)
        if self._stop_event.is_set():
            return
        next_run = next_cron_occurrence(event.schedule, event.timezone, now=time.time())
        timer = threading.Timer(max(0.0, next_run - time.time()), lambda: self._execute_periodic(filename, event))
        self._timers[filename] = timer
        timer.daemon = True
        timer.start()

    def _parse_event(self, path: Path, filename: str) -> MomEvent | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(payload, dict):
            return None
        event_type = payload.get("type")
        channel_id = payload.get("channelId")
        text = payload.get("text")
        if not all(isinstance(value, str) and value for value in [event_type, channel_id, text]):
            return None
        if event_type == "immediate":
            return ImmediateEvent(channel_id=channel_id, text=text)
        if event_type == "one-shot" and isinstance(payload.get("at"), str):
            return OneShotEvent(channel_id=channel_id, text=text, at=str(payload["at"]))
        if event_type == "periodic" and isinstance(payload.get("schedule"), str) and isinstance(payload.get("timezone"), str):
            return PeriodicEvent(channel_id=channel_id, text=text, schedule=str(payload["schedule"]), timezone=str(payload["timezone"]))
        return None

    def _execute(self, filename: str, event: MomEvent, *, delete_after: bool) -> None:
        schedule_info = "immediate"
        if isinstance(event, OneShotEvent):
            schedule_info = event.at
        elif isinstance(event, PeriodicEvent):
            schedule_info = event.schedule

        synthetic_event = {
            "type": "mention",
            "channel": event.channel_id,
            "user": "EVENT",
            "text": f"[EVENT:{filename}:{event.type}:{schedule_info}] {event.text}",
            "ts": str(int(time.time() * 1000)),
        }
        enqueued = bool(self.slack.enqueue_event(synthetic_event))
        if delete_after or not enqueued:
            self._delete_file(filename)

    def _cancel(self, filename: str) -> None:
        timer = self._timers.pop(filename, None)
        if timer is not None:
            timer.cancel()

    def _delete_file(self, filename: str) -> None:
        self._cancel(filename)
        try:
            (self.events_dir / filename).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        self._known_files.discard(filename)


def create_events_watcher(workspace_dir: str, slack: Any) -> EventsWatcher:
    return EventsWatcher(str(Path(workspace_dir) / "events"), slack)
