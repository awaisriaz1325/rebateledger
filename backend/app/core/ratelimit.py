"""Redis fixed-window rate limits (SPEC §4.1 anti-abuse, §6 429 + Retry-After)."""

from __future__ import annotations

import hashlib
from functools import lru_cache

import redis

from app.core.config import get_settings
from app.core.errors import AppError


@lru_cache(maxsize=1)
def client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url.get_secret_value())


def _key(scope: str, ident: str) -> str:
    # Identifiers (emails, IPs) are hashed so Redis never holds them in clear text.
    return "rl:rate:" + scope + ":" + hashlib.sha256(ident.lower().encode()).hexdigest()[:32]


def hit(scope: str, ident: str, limit: int, window_seconds: int) -> None:
    """Count one attempt; raise 429 once the window's limit is exceeded."""
    key = _key(scope, ident)
    pipe = client().pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds, nx=True)
    pipe.ttl(key)
    count, _, ttl = pipe.execute()
    if int(count) > limit:
        retry = max(int(ttl), 1)
        raise AppError(
            429,
            "RATE_LIMITED",
            "Too many requests",
            f"Too many attempts. Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
        )


def reset(scope: str, ident: str) -> None:
    client().delete(_key(scope, ident))
