"""Stale-result detection (SPEC §4.7): when an input of the latest run changes, its
affected results are marked stale with a reason and the user is prompted to re-run.

Triggers: new import overlapping the period, a voided batch the run used, a new
active version (or version decision), and credit allocation changes. Past runs are
never altered beyond the stale marker.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import ColumnElement, and_, func, select, update
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.db.models.business import BaselineRow, ImportBatch, PurchaseLineRow
from app.db.models.runs import PeriodResultRow, RunInput

BASELINE_REACH = timedelta(days=400)
"""Lines can feed computed baselines of periods up to ~one year later."""


def _mark(db: Session, tenant_id: uuid.UUID, condition: ColumnElement[bool], reason: str) -> int:
    result = db.execute(
        update(PeriodResultRow)
        .where(
            PeriodResultRow.tenant_id == tenant_id, PeriodResultRow.stale_at.is_(None), condition
        )
        .values(stale_at=utcnow(), stale_reason=reason[:200])
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


def mark_stale_for_agreement(
    db: Session, tenant_id: uuid.UUID, agreement_id: uuid.UUID, reason: str
) -> int:
    return _mark(db, tenant_id, PeriodResultRow.agreement_id == agreement_id, reason)


def mark_stale_for_period(
    db: Session, tenant_id: uuid.UUID, agreement_id: uuid.UUID, start: date, end: date, reason: str
) -> int:
    return _mark(
        db,
        tenant_id,
        and_(
            PeriodResultRow.agreement_id == agreement_id,
            PeriodResultRow.period_start == start,
            PeriodResultRow.period_end == end,
        ),
        reason,
    )


def mark_stale_for_supplier_range(
    db: Session, tenant_id: uuid.UUID, supplier_id: uuid.UUID, start: date, end: date, reason: str
) -> int:
    """Conservative: results overlapping the dates, or whose baseline could include them."""
    return _mark(
        db,
        tenant_id,
        and_(
            PeriodResultRow.supplier_id == supplier_id,
            PeriodResultRow.period_end >= start,
            PeriodResultRow.period_start <= end + BASELINE_REACH,
        ),
        reason,
    )


def mark_stale_for_batch(
    db: Session, tenant_id: uuid.UUID, batch_id: uuid.UUID, reason: str
) -> int:
    """A batch was committed (new data overlapping periods) or voided (a run used it)."""
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        return 0
    count = 0
    if batch.voided_at is not None:
        used_by = select(RunInput.run_id).where(
            RunInput.tenant_id == tenant_id, RunInput.kind == "batch", RunInput.ref_id == batch_id
        )
        count += _mark(db, tenant_id, PeriodResultRow.run_id.in_(used_by), reason)
    if batch.import_type == "purchases":
        spans = db.execute(
            select(
                PurchaseLineRow.supplier_id,
                func.min(
                    func.least(
                        PurchaseLineRow.invoice_date,
                        PurchaseLineRow.ship_date,
                        PurchaseLineRow.receipt_date,
                    )
                ),
                func.max(
                    func.greatest(
                        PurchaseLineRow.invoice_date,
                        PurchaseLineRow.ship_date,
                        PurchaseLineRow.receipt_date,
                    )
                ),
            )
            .where(PurchaseLineRow.tenant_id == tenant_id, PurchaseLineRow.batch_id == batch_id)
            .group_by(PurchaseLineRow.supplier_id)
        ).all()
        for supplier_id, lo, hi in spans:
            if lo is not None and hi is not None:
                count += mark_stale_for_supplier_range(db, tenant_id, supplier_id, lo, hi, reason)
    elif batch.import_type == "baselines":
        for agreement_id, lo, hi in db.execute(
            select(
                BaselineRow.agreement_id,
                func.min(BaselineRow.period_start),
                func.max(BaselineRow.period_end),
            )
            .where(BaselineRow.tenant_id == tenant_id, BaselineRow.batch_id == batch_id)
            .group_by(BaselineRow.agreement_id)
        ).all():
            count += _mark(
                db,
                tenant_id,
                and_(
                    PeriodResultRow.agreement_id == agreement_id,
                    PeriodResultRow.full_period_start <= hi,
                    PeriodResultRow.full_period_end >= lo,
                ),
                reason,
            )
    return count
