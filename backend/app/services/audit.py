"""Append-only, hash-chained audit log (SPEC §4.12)."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.db.models.identity import AuditEvent

GENESIS = "0" * 64
PLATFORM_CHAIN = "platform"


@dataclass(frozen=True)
class RequestMeta:
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""


request_meta: ContextVar[RequestMeta] = ContextVar("request_meta", default=RequestMeta())  # noqa: B039 - frozen dataclass


@dataclass(frozen=True)
class Actor:
    type: str  # user | platform_admin | system
    user_id: uuid.UUID | None = None
    label: str = ""

    @staticmethod
    def system(label: str = "system") -> Actor:
        return Actor("system", None, label)


def _content(e: AuditEvent) -> str:
    return json.dumps(
        {
            "chain": e.chain_key,
            "seq": e.seq,
            "tenant": str(e.tenant_id) if e.tenant_id else None,
            "at": e.occurred_at.isoformat(),
            "actor": [
                e.actor_type,
                str(e.actor_user_id) if e.actor_user_id else None,
                e.actor_label,
            ],
            "action": e.action,
            "object": [e.object_type, e.object_id],
            "summary": e.summary,
            "request": [e.request_id, e.ip, e.user_agent],
            "prev": e.prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def compute_hash(e: AuditEvent) -> str:
    return hashlib.sha256(_content(e).encode()).hexdigest()


def record(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    actor: Actor,
    action: str,
    object_type: str = "",
    object_id: str | uuid.UUID = "",
    summary: dict[str, Any] | None = None,
) -> AuditEvent:
    """Write one event in the caller's transaction. Never pass raw rows or secrets in summary."""
    chain = str(tenant_id) if tenant_id else PLATFORM_CHAIN
    # Serialise writers per chain so seq and prev_hash are gap-free.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 42))"), {"k": "audit:" + chain}
    )
    last = db.execute(
        select(AuditEvent.seq, AuditEvent.hash)
        .where(AuditEvent.chain_key == chain)
        .order_by(AuditEvent.seq.desc())
        .limit(1)
    ).first()
    meta = request_meta.get()
    event = AuditEvent(
        tenant_id=tenant_id,
        chain_key=chain,
        seq=(last.seq + 1) if last else 1,
        occurred_at=utcnow(),
        actor_type=actor.type,
        actor_user_id=actor.user_id,
        actor_label=actor.label[:254],
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        summary=summary or {},
        request_id=meta.request_id,
        ip=meta.ip,
        user_agent=meta.user_agent[:400],
        prev_hash=last.hash if last else GENESIS,
        hash="",
    )
    event.hash = compute_hash(event)
    db.add(event)
    db.flush()
    return event


@dataclass(frozen=True)
class ChainCheck:
    chain_key: str
    events: int
    ok: bool
    first_bad_seq: int | None = None


def verify_chain(db: Session, chain_key: str) -> ChainCheck:
    prev = GENESIS
    expected_seq = 1
    count = 0
    rows = db.execute(
        select(AuditEvent).where(AuditEvent.chain_key == chain_key).order_by(AuditEvent.seq)
    ).scalars()
    for e in rows:
        count += 1
        if e.seq != expected_seq or e.prev_hash != prev or compute_hash(e) != e.hash:
            return ChainCheck(chain_key, count, False, e.seq)
        prev = e.hash
        expected_seq += 1
    return ChainCheck(chain_key, count, True)


def _register_verification_job() -> None:
    from app.workers.jobs import JobContext, handler

    @handler("verify_audit_chain")
    def verify_job(db: Session, ctx: JobContext) -> dict[str, Any]:
        import structlog

        assert ctx.tenant_id is not None
        check = verify_chain(db, str(ctx.tenant_id))
        if not check.ok:
            # Alert (SPEC §12): logged at error level for the log-based alert policy.
            structlog.get_logger("audit").error(
                "audit_chain_broken",
                tenant_id=str(ctx.tenant_id),
                first_bad_seq=check.first_bad_seq,
            )
        return {"ok": check.ok, "events": check.events, "first_bad_seq": check.first_bad_seq}


_register_verification_job()
