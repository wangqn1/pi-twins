from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import sleep
from typing import Any, Callable, TypeVar

T = TypeVar("T")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_ERROR_PATTERN = (
    "overloaded",
    "rate limit",
    "too many requests",
    "service unavailable",
    "server error",
    "internal error",
    "connection error",
    "connection refused",
    "other side closed",
    "fetch failed",
    "upstream connect",
    "reset before headers",
    "terminated",
    "retry delay",
)


@dataclass
class HTTPRequestError(RuntimeError):
    message: str
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    network_error: bool = False

    def __post_init__(self) -> None:
        super().__init__(self.message)


def _lower_headers(headers: dict[str, str]) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in headers.items()}


def parse_retry_after_ms(headers: dict[str, str]) -> int | None:
    normalized = _lower_headers(headers)
    retry_after = normalized.get("retry-after")
    if retry_after is None:
        return None

    seconds = None
    try:
        seconds = float(retry_after)
    except ValueError:
        seconds = None
    if seconds is not None:
        return max(0, int(seconds * 1000))

    try:
        dt = parsedate_to_datetime(retry_after)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta_ms = int((dt - datetime.now(timezone.utc)).total_seconds() * 1000)
    return max(0, delta_ms)


def is_retryable_error(error: Exception) -> bool:
    if isinstance(error, HTTPRequestError):
        if error.network_error:
            return True
        if error.status in RETRYABLE_STATUS_CODES:
            return True
        lowered = error.message.lower()
        return any(pattern in lowered for pattern in RETRYABLE_ERROR_PATTERN)

    lowered = str(error).lower()
    return any(pattern in lowered for pattern in RETRYABLE_ERROR_PATTERN)


def request_with_retry(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay_ms: int = 2000,
    max_retry_delay_ms: int = 60000,
    sleep_fn: Callable[[float], None] = sleep,
) -> T:
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if not is_retryable_error(exc) or attempt >= max_retries:
                raise

            retry_after_ms = parse_retry_after_ms(exc.headers) if isinstance(exc, HTTPRequestError) else None
            delay_ms = retry_after_ms if retry_after_ms is not None else base_delay_ms * (2**attempt)
            if max_retry_delay_ms > 0 and delay_ms > max_retry_delay_ms:
                delay_seconds = int((delay_ms + 999) / 1000)
                cap_seconds = int((max_retry_delay_ms + 999) / 1000)
                raise RuntimeError(
                    f"Server requested {delay_seconds}s retry delay (max: {cap_seconds}s). {exc}"
                ) from exc

            if delay_ms > 0:
                sleep_fn(delay_ms / 1000)
            attempt += 1
