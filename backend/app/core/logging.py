"""Structured JSON logs with scrubbing (SPEC §8.4, §12). Log IDs, never data."""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

SENSITIVE_KEYS = re.compile(
    r"pass(word)?|secret|token|cookie|authorization|session|csrf|api[_-]?key|recovery|otp|code$",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_email(value: str) -> str:
    return "email:" + hashlib.sha256(value.lower().encode()).hexdigest()[:12]


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return EMAIL.sub(lambda m: mask_email(m.group(0)), value)
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if SENSITIVE_KEYS.search(str(k)) else _scrub_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_scrub_value(v) for v in value]
    return value


def scrub(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event):
        if key == "event":
            continue
        event[key] = "[REDACTED]" if SENSITIVE_KEYS.search(key) else _scrub_value(event[key])
    return event


def configure_logging(json_logs: bool = True, level: int = logging.INFO) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
        scrub,  # after formatting, so exception text is scrubbed too
    ]
    processors.append(
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
