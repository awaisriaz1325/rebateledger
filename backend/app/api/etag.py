"""Optimistic locking with ETag / If-Match (SPEC §6)."""

from __future__ import annotations

from app.core.errors import AppError


def etag(row_version: int) -> str:
    return f'"v{row_version}"'


def check_if_match(header: str | None, current: int) -> int:
    """428 if missing, 412 if stale. Returns the version the client saw."""
    if header is None:
        raise AppError(
            428,
            "PRECONDITION_REQUIRED",
            "If-Match header required",
            "Send the ETag you received as If-Match.",
        )
    value = header.strip().removeprefix("W/")
    if value != etag(current):
        raise AppError(
            412,
            "PRECONDITION_FAILED",
            "Changed by someone else",
            "This item was changed by someone else. Reload to see the latest version, then try again.",
        )
    return current
