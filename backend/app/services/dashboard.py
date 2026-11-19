"""Dashboard aggregates (SPEC §4.10). Identified ≠ recovered: recovered comes only from
credits linked to claims; projected amounts are never reported as recovered."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import today_in
from app.db.models.business import (
    Agreement,
    AgreementVersion,
    CreditLineRow,
    PurchaseLineRow,
    Supplier,
    VersionStatus,
)
from app.db.models.identity import Tenant
from app.db.models.runs import TERMINAL_CLAIM, CalculationRun, Claim, ClaimRecovery, RunStatus
from app.engine.reconcile import ReconStatus
from app.services.reconciliation import live_items
from app.services.tiers import opportunities, tracker

ZERO = Decimal("0.00")
BUCKETS = ((0, 30, "0-30"), (31, 60, "31-60"), (61, 90, "61-90"), (91, 10**6, "90+"))


def getting_started(db: Session, tenant: Tenant, open_discrepancies: int) -> list[dict[str, Any]]:
    """Setup checklist (v1.3 Phase 24). Every step is derived from data; nothing is ticked by hand.

    "Review" is done once a claim exists, or once a run found nothing short-paid or missing.
    """
    tid = tenant.id

    def count(q: Any) -> int:
        return int(db.execute(q).scalar_one())

    def exists(q: Any) -> bool:
        return bool(db.execute(select(q.exists())).scalar())

    suppliers = count(
        select(func.count()).where(Supplier.tenant_id == tid, Supplier.merged_into_id.is_(None))
    )
    agreements = count(
        select(func.count()).where(Agreement.tenant_id == tid, Agreement.status == "active")
    )
    active = count(
        select(func.count(func.distinct(AgreementVersion.agreement_id))).where(
            AgreementVersion.tenant_id == tid,
            AgreementVersion.status == VersionStatus.ACTIVE.value,
        )
    )
    purchases = exists(
        select(PurchaseLineRow.id).where(
            PurchaseLineRow.tenant_id == tid, PurchaseLineRow.voided.is_(False)
        )
    )
    credits = exists(
        select(CreditLineRow.id).where(
            CreditLineRow.tenant_id == tid, CreditLineRow.voided.is_(False)
        )
    )
    ran = exists(
        select(CalculationRun.id).where(
            CalculationRun.tenant_id == tid, CalculationRun.status == RunStatus.SUCCEEDED.value
        )
    )
    claimed = exists(select(Claim.id).where(Claim.tenant_id == tid))

    def step(key: str, label: str, done: bool, link: str, n: int | None = None) -> dict[str, Any]:
        return {"key": key, "label": label, "done": done, "count": n, "link": link}

    return [
        step("suppliers", "Add your suppliers", suppliers > 0, "/app/suppliers/new", suppliers),
        step("purchases", "Import purchase history", purchases, "/app/imports/new?type=purchases"),
        step(
            "agreements",
            "Add rebate agreements",
            agreements > 0,
            "/app/agreements/import",
            agreements,
        ),
        step("activate", "Activate the agreements", active > 0, "/app/agreements", active),
        step("run", "Run the first calculation", ran, "/app/runs"),
        step("credits", "Import supplier credits", credits, "/app/imports/new?type=credits"),
        step(
            "review",
            "Review discrepancies and claim what is owed",
            claimed or (ran and open_discrepancies == 0),
            "/app/discrepancies",
        ),
    ]


def kpis(db: Session, tenant: Tenant) -> dict[str, Any]:
    today = today_in(tenant.timezone)
    items = live_items(db, tenant, today=today)
    open_variance = ZERO
    by_supplier: dict[str, Decimal] = {}
    review = 0
    discrepancies = 0
    for li in items:
        st = li.item.status
        if st in (ReconStatus.SHORT_PAID, ReconStatus.MISSING):
            discrepancies += 1
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
    tier_rows = tracker(db, tenant, today)  # computed once (about 0.7 s at 100k lines)
    top_opportunities = opportunities(db, tenant, today, rows=tier_rows)[:3]
    tiers = [
        t
        for t in tier_rows
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
    from datetime import timedelta

    from app.exports.reports import rate_totals

    rates = rate_totals(db, tenant, today - timedelta(days=364), today, items)
    return {
        "as_of": today.isoformat(),
        "rebate_rate": {
            "earned_pct": None if rates["earned_pct"] is None else format(rates["earned_pct"], "f"),
            "received_pct": None
            if rates["received_pct"] is None
            else format(rates["received_pct"], "f"),
            "link": "/app/reports?report=rebate_rate",
        },
        "getting_started": getting_started(db, tenant, discrepancies),
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
        "top_opportunities": top_opportunities,
        "data_freshness": {
            "threshold_days": tenant.data_freshness_days,
            "suppliers": freshness,
            "link": "/app/suppliers",
        },
        "has_results": bool(items),
    }
