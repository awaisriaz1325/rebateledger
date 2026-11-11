"""Tier tracker and accrual estimates for open periods (SPEC §4.9). Every projected
number here is an ESTIMATE and is labelled as such in the API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import today_in
from app.db.models.business import (
    Agreement,
    AgreementVersion,
    PurchaseLineRow,
    Supplier,
    VersionStatus,
)
from app.db.models.identity import Tenant
from app.engine.calculate import calculate
from app.engine.models import CalcOptions, ComponentType, Measure, Period, ThresholdComparison
from app.engine.periods import clip, periods_overlapping
from app.services import agreements as agreement_svc
from app.services.agreement_terms import snapshot_for

CENT = Decimal("0.01")


@dataclass(frozen=True)
class TierRow:
    agreement_id: uuid.UUID
    agreement_name: str
    supplier_name: str
    period_start: date
    period_end: date
    measure_kind: str
    current_measure: Decimal
    current_tier: int | None
    next_tier: int | None
    next_threshold: Decimal | None
    gap: Decimal | None
    days_remaining: int
    days_elapsed: int
    projected_measure: Decimal
    projected_reaches_next: bool
    potential_additional: Decimal | None
    expected_to_date: Decimal | None
    needs_review: bool
    data_as_of: date | None


def _latest_purchase(db: Session, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> date | None:
    return db.execute(
        select(
            func.max(
                func.greatest(
                    PurchaseLineRow.invoice_date,
                    PurchaseLineRow.ship_date,
                    PurchaseLineRow.receipt_date,
                )
            )
        ).where(
            PurchaseLineRow.tenant_id == tenant_id,
            PurchaseLineRow.supplier_id == supplier_id,
            PurchaseLineRow.voided.is_(False),
        )
    ).scalar()


def tracker(db: Session, tenant: Tenant, today: date | None = None) -> list[TierRow]:
    now = today or today_in(tenant.timezone)
    rows: list[TierRow] = []
    versions = db.execute(
        select(AgreementVersion, Agreement, Supplier)
        .join(Agreement, Agreement.id == AgreementVersion.agreement_id)
        .join(Supplier, Supplier.id == Agreement.supplier_id)
        .where(
            Agreement.tenant_id == tenant.id,
            Agreement.status == "active",
            AgreementVersion.status == VersionStatus.ACTIVE.value,
        )
    ).all()
    for version, agreement, supplier in versions:
        snap = snapshot_for(db, version, agreement)
        if not snap.effective_period.contains(now):
            continue
        periods = periods_overlapping(
            snap.period_type, snap.fiscal_year_start_month, now, now, snap.custom_periods
        )
        if not periods:
            continue
        full = periods[0]
        window = clip(full, snap.effective_from, snap.effective_period.end)
        if window is None:
            continue
        lines = agreement_svc.purchase_lines(
            db, tenant.id, agreement.supplier_id, date(full.start.year - 1, 1, 1), full.end
        )
        result = calculate(
            snap,
            window,
            lines,
            agreement_svc.baselines(db, tenant.id, agreement.id),
            CalcOptions(
                data_coverage_start=agreement_svc.data_coverage_start(
                    db, tenant.id, agreement.supplier_id
                ),
                full_period=Period(full.start, full.end, full.label),
            ),
        )
        m = result.measure
        days_total = window.days
        elapsed = max((min(now, window.end) - window.start).days + 1, 1)
        projected = (m * days_total / elapsed).quantize(CENT, ROUND_HALF_UP)
        tiered = [
            c
            for c in snap.components
            if c.type
            in (
                ComponentType.TIERED_ALL_UNITS,
                ComponentType.TIERED_INCREMENTAL,
                ComponentType.FIXED_BONUS,
            )
        ]
        next_tier = next_threshold = gap = potential = None
        current_tier = result.tier_reached
        for comp in tiered:
            thresholds = (
                [t.threshold for t in comp.tiers] if comp.tiers else [comp.threshold or Decimal(0)]
            )
            for idx, thr in enumerate(thresholds):
                met = m >= thr if snap.threshold_comparison is ThresholdComparison.GTE else m > thr
                if not met:
                    next_tier, next_threshold = idx + 1, thr
                    gap = (
                        (thr - m)
                        if snap.threshold_comparison is ThresholdComparison.GTE
                        else (thr - m) + CENT
                    )
                    potential = _potential(comp, idx, thr, snap.measure)
                    break
            if next_threshold is not None:
                break
        rows.append(
            TierRow(
                agreement_id=agreement.id,
                agreement_name=agreement.name,
                supplier_name=supplier.name,
                period_start=window.start,
                period_end=window.end,
                measure_kind=snap.measure.value,
                current_measure=m,
                current_tier=current_tier,
                next_tier=next_tier,
                next_threshold=next_threshold,
                gap=gap,
                days_remaining=max((window.end - now).days, 0),
                days_elapsed=elapsed,
                projected_measure=projected,
                projected_reaches_next=next_threshold is not None and projected >= next_threshold,
                potential_additional=potential,
                expected_to_date=result.expected,
                needs_review=result.needs_review,
                data_as_of=_latest_purchase(db, tenant.id, agreement.supplier_id),
            )
        )
    rows.sort(key=lambda r: (r.gap is None, r.gap or Decimal(0)))
    return rows


def _potential(comp: object, idx: int, threshold: Decimal, measure: Measure) -> Decimal | None:
    """Additional rebate at the moment the next tier is reached (estimate, spend measure)."""
    from app.engine.models import Component

    assert isinstance(comp, Component)
    if comp.type is ComponentType.FIXED_BONUS:
        return comp.amount
    if comp.type is ComponentType.TIERED_ALL_UNITS and measure is Measure.SPEND:
        next_rate = comp.tiers[idx].rate
        if next_rate is None:
            return None
        current_rate = comp.tiers[idx - 1].rate if idx > 0 else Decimal(0)
        return ((next_rate - (current_rate or Decimal(0))) * threshold).quantize(
            CENT, ROUND_HALF_UP
        )
    return None  # incremental tiers only change the rate on future volume
