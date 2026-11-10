"""Idempotency-Key handling for creating POSTs (SPEC §6): 24 h per tenant + user + route."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import AppError
from app.db.models.identity import IdempotencyKey

TTL = timedelta(hours=24)


@dataclass(frozen=True)
class Stored:
    status: int
    body: dict[str, Any]


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def begin(db: Session, ctx: Any, route: str, key: str | None, payload: Any) -> Stored | None:
    """Reserve the key. Returns the stored response when this is a replay."""
    if key is None:
        return None
    if not 8 <= len(key) <= 200:
        raise AppError(
            422,
            "IDEMPOTENCY_KEY_INVALID",
            "Invalid Idempotency-Key",
            "Use 8–200 characters, e.g. a UUID.",
        )
    tenant_id, user_id = ctx.tenant_uuid, ctx.user.id
    db.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id, IdempotencyKey.created_at < utcnow() - TTL
        )
    )
    request_hash = _hash(payload)
    db.execute(
        insert(IdempotencyKey)
        .values(
            tenant_id=tenant_id,
            user_id=user_id,
            route=route,
            key=key,
            request_hash=request_hash,
            created_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "user_id", "route", "key"])
    )
    row = db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.route == route,
            IdempotencyKey.key == key,
        )
    ).scalar_one()
    if row.request_hash != request_hash:
        raise AppError(
            422,
            "IDEMPOTENCY_KEY_REUSED",
            "Idempotency-Key reused",
            "This key was already used with a different request.",
        )
    if row.status_code is not None and row.response_body is not None:
        return Stored(row.status_code, row.response_body)
    return None


def finish(
    db: Session, ctx: Any, route: str, key: str | None, status: int, body: dict[str, Any]
) -> None:
    if key is None:
        return
    row = db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == ctx.tenant_uuid,
            IdempotencyKey.user_id == ctx.user.id,
            IdempotencyKey.route == route,
            IdempotencyKey.key == key,
        )
    ).scalar_one()
    row.status_code, row.response_body = status, body
