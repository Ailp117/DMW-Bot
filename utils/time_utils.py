from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE_NAME = "Europe/Berlin"
BERLIN_TIMEZONE = ZoneInfo(DEFAULT_TIMEZONE_NAME)


def berlin_now() -> datetime:
    return datetime.now(BERLIN_TIMEZONE)


def berlin_now_utc() -> datetime:
    return berlin_now().astimezone(UTC)

