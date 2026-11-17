"""Look-back recovery audit (v1.2 Phase 20; free in pilots, ADR 0019).

Before running a multi-year calculation, show where the chosen range is not covered: months
without any active or superseded agreement version, and purchase history that starts later
than the range. Gaps are listed, never filled with guesses.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models.business import Agreement, AgreementVersion, Supplier, VersionStatus
from app.db.models.identity import Tenant
from app.exports.reports import AUDIT_MAX_DAYS
from app.services import claims as claim_svc
from app.services import reconciliation as recon
from app.services.agreements import data_coverage_start

DAY = timedelta(days=1)


@dataclass
class SupplierCoverage:
    supplier_id: uuid.UUID
    name: str
    agreements: int
    gaps: list[tuple[date, date]] = field(default_factory=list)
    data_from: date | None = None
    #: No purchase lines at all, or the first one is after the audit start.
    history_starts_late: bool = False


def check_range(start: date, end: date) -> None:
    if end < start:
        raise AppError(422, "RANGE_INVALID", "Invalid range", "The end date is before the start.")
    if (end - start).days > AUDIT_MAX_DAYS:
        raise AppError(
            422, "RANGE_TOO_LONG", "Range too long", "An audit may cover at most three years."
        )


def gaps(intervals: list[tuple[date, date]], start: date, end: date) -> list[tuple[date, date]]:
    """Parts of [start, end] covered by none of the closed intervals (pure)."""
    out = []
    cursor = start
    for a, b in sorted(intervals):
        if b < cursor:
            continue
        if a > end:
            break
        if a > cursor:
            out.append((cursor, a - DAY))
        cursor = max(cursor, b + DAY)
        if cursor > end:
            return out
    if cursor <= end:
        out.append((cursor, end))
    return out


def coverage(
    db: Session, tenant: Tenant, start: date, end: date, supplier_id: uuid.UUID | None = None
) -> list[SupplierCoverage]:
    check_range(start, end)
    q = select(Supplier).where(Supplier.tenant_id == tenant.id, Supplier.merged_into_id.is_(None))
    if supplier_id:
        q = q.where(Supplier.id == supplier_id)
    supplier_rows = list(db.execute(q.order_by(Supplier.name)).scalars())
    versions = db.execute(
        select(
            Agreement.supplier_id,
            Agreement.id,
            AgreementVersion.effective_from,
            AgreementVersion.effective_to,
        )
        .join(AgreementVersion, AgreementVersion.agreement_id == Agreement.id)
        .where(
            Agreement.tenant_id == tenant.id,
            Agreement.status == "active",
            AgreementVersion.status.in_(
                [VersionStatus.ACTIVE.value, VersionStatus.SUPERSEDED.value]
            ),
        )
    ).all()
    by_supplier: dict[uuid.UUID, list[tuple[uuid.UUID, date, date]]] = {}
    for sid, aid, frm, to in versions:
        by_supplier.setdefault(sid, []).append((aid, frm, to or end))
    out = []
    for s in supplier_rows:
        vs = by_supplier.get(s.id, [])
        if not vs and supplier_id is None:
            continue  # a supplier without agreements has nothing to audit
        overlapping = [(a, f, t) for a, f, t in vs if f <= end and t >= start]
        data_from = data_coverage_start(db, tenant.id, s.id)
        out.append(
            SupplierCoverage(
                supplier_id=s.id,
                name=s.name,
                agreements=len({a for a, _, _ in overlapping}),
                gaps=gaps([(f, t) for _, f, t in overlapping], start, end),
                data_from=data_from,
                history_starts_late=data_from is None or data_from > start,
            )
        )
    return out


def create_claims(db: Session, ctx: Any, result_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """One claim per supplier from the selected shortfalls (all or nothing)."""
    assert ctx.tenant is not None
    items = {li.result.id: li for li in recon.live_items(db, ctx.tenant)}
    by_supplier: dict[uuid.UUID, list[uuid.UUID]] = {}
    for rid in dict.fromkeys(result_ids):
        li = items.get(rid)
        if li is None:
            raise AppError(404, "NOT_FOUND", "Not found", "A selected period no longer exists.")
        by_supplier.setdefault(li.result.supplier_id, []).append(rid)
    if not by_supplier:
        raise AppError(422, "NO_DISCREPANCIES", "Nothing selected", "Select at least one period.")
    created = []
    for rids in by_supplier.values():
        claim = claim_svc.create(
            db,
            ctx,
            result_ids=rids,
            title=None,
            claimed_amount=None,
            reason="",
            assignee_id=None,
            due_date=None,
            follow_up_date=None,
            supplier_contact_id=None,
            channel="email",
            notes="Created from a recovery audit.",
        )
        created.append(claim.id)
    return created
