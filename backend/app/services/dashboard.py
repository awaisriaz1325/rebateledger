"""Dashboard aggregates (SPEC §4.10). Identified ≠ recovered: recovered comes only from
credits linked to claims; projected amounts are never reported as recovered."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import today_in
from app.db.models.business import CreditLineRow, PurchaseLineRow, Supplier
from app.db.models.identity import Tenant
from app.db.models.runs import TERMINAL_CLAIM, Claim, ClaimRecovery
from app.engine.reconcile import ReconStatus
from app.services.reconciliation import live_items
from app.services.tiers import tracker

ZERO = Decimal("0.00")
BUCKETS = ((0, 30, "0-30"), (31, 60, "31-60"), (61, 90, "61-90"), (91, 10**6, "90+"))


def kpis(db: Session, tenant: Tenant) -> dict[str, Any]:
    today = today_in(tenant.timezone)
    items = live_items(db, tenant, today=today)
    open_variance = ZERO
    by_supplier: dict[str, Decimal] = {}
    review = 0
    for li in items:
        st = li.item.status
        if st is ReconStatus.NEEDS_REVIEW:
            review += 1
        if st in (ReconStatus.SHORT_PAID, ReconStatus.MISSING) and li.item.variance is not None:
            gap = -li.item.variance
            open_variance += gap
            by_supplier[li.supplier_name] = by_supplier.get(li.supplier_name, ZERO) + gap
    year_start = date(today.year, 1, 1)
    recovered = db.execute(
        select(func.coalesce(func.sum(ClaimRecovery.amount), 0))
        .join(CreditLineRow, CreditLineRow.id == ClaimRecovery.credit_id)
        .where(
            ClaimRecovery.tenant_id == tenant.id,
            CreditLineRow.credit_date >= year_start,
            CreditLineRow.credit_date <= today,
        )
    ).scalar_one()
    claims = (
        db.execute(
            select(Claim).where(
                Claim.tenant_id == tenant.id, Claim.status.not_in([s.value for s in TERMINAL_CLAIM])
            )
        )
        .scalars()
        .all()
    )
    aging_count = {label: 0 for _, _, label in BUCKETS}
    aging_amount = {label: ZERO for _, _, label in BUCKETS}
    for c in claims:
        start = c.submitted_at.date() if c.submitted_at else c.created_at.date()
        age = (today - start).days
        for lo, hi, label in BUCKETS:
            if lo <= age <= hi:
                aging_count[label] += 1
                aging_amount[label] += c.claimed_amount
                break
    tiers = [
        t
        for t in tracker(db, tenant, today)
        if t.gap is not None
        and t.next_threshold
        and t.gap <= t.next_threshold * tenant.tier_alert_pct
    ]
    freshness = []
    latest: dict[Any, date | None] = dict(
        db.execute(
            select(
                PurchaseLineRow.supplier_id,
                func.max(
                    func.greatest(
                        PurchaseLineRow.invoice_date,
                        PurchaseLineRow.ship_date,
                        PurchaseLineRow.receipt_date,
                    )
                ),
            )
            .where(PurchaseLineRow.tenant_id == tenant.id, PurchaseLineRow.voided.is_(False))
            .group_by(PurchaseLineRow.supplier_id)
        ).all()
    )
    for s in db.execute(
        select(Supplier)
        .where(
            Supplier.tenant_id == tenant.id,
            Supplier.merged_into_id.is_(None),
            Supplier.status == "active",
        )
        .order_by(Supplier.name)
    ).scalars():
        d = latest.get(s.id)
        days_old = None if d is None else (today - d).days
        freshness.append(
            {
                "supplier_id": str(s.id),
                "supplier_name": s.name,
                "latest_purchase_date": d.isoformat() if d else None,
                "days_old": days_old,
                "stale": d is None
                or (days_old is not None and days_old > tenant.data_freshness_days),
            }
        )
    top = sorted(by_supplier.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "as_of": today.isoformat(),
        "identified_open_variance": {
            "amount": format(open_variance, "f"),
            "link": "/app/discrepancies?status=SHORT_PAID,MISSING",
        },
        "recovered_this_year": {
            "amount": format(Decimal(recovered).quantize(Decimal("0.01")), "f"),
            "link": "/app/claims?recovered=year",
        },
        "open_claims": {
            "count": len(claims),
            "amount": format(sum((c.claimed_amount for c in claims), ZERO), "f"),
            "aging": {
                k: {"count": aging_count[k], "amount": format(aging_amount[k], "f")}
                for k in aging_count
            },
            "link": "/app/claims?open=true",
        },
        "needs_review": {"count": review, "link": "/app/results?status=NEEDS_REVIEW"},
        "top_suppliers_by_open_variance": [
            {"supplier_name": n, "amount": format(a, "f")} for n, a in top
        ],
        "tier_opportunities": {"count": len(tiers), "link": "/app/tiers"},
        "data_freshness": {
            "threshold_days": tenant.data_freshness_days,
            "suppliers": freshness,
            "link": "/app/suppliers",
        },
        "has_results": bool(items),
    }
