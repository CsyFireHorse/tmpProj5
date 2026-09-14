"""Timestamp coercion. Every provider spells time differently."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def from_epoch(value: Any) -> datetime | None:
    """Accept seconds or milliseconds since the epoch."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    # Anything past ~2001 in seconds is below this bound; above it the value is
    # milliseconds.
    if number > 1e11:
        number /= 1000.0
    try:
        return datetime.fromtimestamp(number, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def from_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def coerce(value: Any) -> datetime | None:
    """Best-effort: ISO strings, epoch seconds, epoch millis, or nested dicts."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, dict):
        for key in ("created", "start", "timestamp", "createdAt", "time"):
            if key in value:
                found = coerce(value[key])
                if found:
                    return found
        return None
    return from_iso(value) or from_epoch(value)


def max_time(*values: datetime | None) -> datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def min_time(*values: datetime | None) -> datetime | None:
    present = [v for v in values if v is not None]
    return min(present) if present else None
