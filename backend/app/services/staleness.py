"""Stale-result detection hooks (SPEC §4.7). Runs are added in Phase 4; until then
there is nothing to mark, but callers already report every input change here."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session


def mark_stale_for_agreement(
    db: Session, tenant_id: uuid.UUID, agreement_id: uuid.UUID, reason: str
) -> int:
    return 0


def mark_stale_for_batch(
    db: Session, tenant_id: uuid.UUID, batch_id: uuid.UUID, reason: str
) -> int:
    return 0


def mark_stale_for_supplier_range(
    db: Session,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    start: object,
    end: object,
    reason: str,
) -> int:
    return 0
