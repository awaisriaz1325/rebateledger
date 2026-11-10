"""The only place backend services read the wall clock (patchable in tests)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def today_in(timezone: str) -> date:
    """'Today' in a tenant's timezone (SPEC §4.7.2 due-date rule)."""
    return utcnow().astimezone(ZoneInfo(timezone)).date()
