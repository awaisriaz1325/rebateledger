"""Claim evidence pack (SPEC §4.8): a ZIP with a PDF and CSV appendices.

Amounts come from the same live reconciliation the Results screen shows, so the pack
always reconciles with what the user sees. The eligible-line listing is rebuilt with the
engine's own selection step over exactly the import batches the run used, and the pack
states whether its total equals the run's stored eligible spend.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.clock import today_in
from app.core.csv_safe import csv_string
from app.db.models.business import (
    Agreement,
    AgreementVersion,
    CreditLineRow,
    PurchaseLineRow,
    Supplier,
)
from app.db.models.identity import Tenant
from app.db.models.runs import (
    CalculationRun,
    ClaimEvent,
    ClaimItem,
    CreditAllocation,
    PeriodResultRow,
    PeriodTrace,
)
from app.engine.calculate import select_lines
from app.engine.models import Period
from app.exports.writers import html_to_pdf, render_html
from app.services import reconciliation as recon
from app.services.agreement_terms import snapshot_for
from app.services.agreements import to_line
from app.services.claims import get as get_claim
from app.services.claims import recovered_total

ZERO = Decimal(0)
CENT = Decimal("0.01")


@dataclass
class LineCheck:
    eligible_count: int
    excluded_count: int
    eligible_spend: Decimal
    matches: bool
    rows: list[list[object]]


@dataclass
class Section:
    item: ClaimItem
    result: PeriodResultRow
    run_number: int
    agreement_name: str
    reference: str
    summary: str
    expected: Decimal | None
    received: Decimal
    variance: Decimal | None
    due_date: date | None
    trace: list[dict[str, Any]]
    allocations: list[dict[str, Any]]
    lines: LineCheck


def _lines(
    db: Session, tenant: Tenant, result: PeriodResultRow, run: CalculationRun, agreement: Agreement
) -> LineCheck:
    version = db.execute(
        select(AgreementVersion).where(
            AgreementVersion.id == result.agreement_version_id,
            AgreementVersion.tenant_id == tenant.id,
        )
    ).scalar_one()
    snap = snapshot_for(db, version, agreement)
    batch_ids = [uuid.UUID(b) for b in run.snapshot.get("batch_ids", [])]
    rows = (
        list(
            db.execute(
                select(PurchaseLineRow).where(
                    PurchaseLineRow.tenant_id == tenant.id,
                    PurchaseLineRow.supplier_id == result.supplier_id,
                    PurchaseLineRow.batch_id.in_(batch_ids),
                    or_(
                        PurchaseLineRow.invoice_date.between(
                            result.period_start, result.period_end
                        ),
                        PurchaseLineRow.ship_date.between(result.period_start, result.period_end),
                        PurchaseLineRow.receipt_date.between(
                            result.period_start, result.period_end
                        ),
                        PurchaseLineRow.invoice_date.is_(None)
                        & PurchaseLineRow.ship_date.is_(None)
                        & PurchaseLineRow.receipt_date.is_(None),
                    ),
                )
            ).scalars()
        )
        if batch_ids
        else []
    )
    by_id = {str(r.id): r for r in rows}
    selection = select_lines(
        snap, Period(result.period_start, result.period_end), [to_line(r) for r in rows]
    )
    eligible_ids = {ln.line_id for ln in selection.eligible}
    listing: list[list[object]] = []
    for ln in selection.considered:
        r = by_id[ln.line_id]
        listing.append(
            [
                agreement.name,
                result.period_label,
                "yes" if ln.line_id in eligible_ids else "no",
                r.invoice_number,
                r.line_number or "",
                r.sku,
                r.invoice_date.isoformat() if r.invoice_date else "",
                r.ship_date.isoformat() if r.ship_date else "",
                r.receipt_date.isoformat() if r.receipt_date else "",
                format(r.quantity, "f"),
                format(r.amount, "f"),
                r.source_row or "",
            ]
        )
    spend = sum((ln.amount for ln in selection.eligible), ZERO)
    return LineCheck(
        len(selection.eligible),
        len(selection.considered) - len(selection.eligible),
        spend,
        spend == result.spend,
        listing,
    )


def build_evidence_pack(
    db: Session, tenant: Tenant, claim_id: uuid.UUID, now: datetime
) -> tuple[bytes, int, int]:
    from app.exports.service import zip_bytes

    claim = get_claim(db, tenant.id, claim_id)
    supplier = db.execute(
        select(Supplier).where(Supplier.id == claim.supplier_id, Supplier.tenant_id == tenant.id)
    ).scalar_one()
    items = list(
        db.execute(
            select(ClaimItem).where(ClaimItem.claim_id == claim.id).order_by(ClaimItem.period_start)
        ).scalars()
    )
    today = today_in(tenant.timezone)
    sections: list[Section] = []
    all_lines: list[list[object]] = []
    credit_rows: list[list[object]] = []
    for it in items:
        live = next(
            (
                li
                for li in recon.live_items(db, tenant, agreement_id=it.agreement_id, today=today)
                if li.result.period_start == it.period_start
                and li.result.period_end == it.period_end
            ),
            None,
        )
        result = (
            live.result
            if live
            else db.execute(
                select(PeriodResultRow).where(PeriodResultRow.id == it.result_id)
            ).scalar_one()
        )
        run = db.execute(
            select(CalculationRun).where(CalculationRun.id == result.run_id)
        ).scalar_one()
        agreement = db.execute(
            select(Agreement).where(
                Agreement.id == it.agreement_id, Agreement.tenant_id == tenant.id
            )
        ).scalar_one()
        version = db.execute(
            select(AgreementVersion).where(AgreementVersion.id == result.agreement_version_id)
        ).scalar_one()
        trace = (
            db.execute(select(PeriodTrace.trace).where(PeriodTrace.result_id == result.id)).scalar()
            or []
        )
        allocations = []
        for a, c in db.execute(
            select(CreditAllocation, CreditLineRow)
            .join(CreditLineRow, CreditLineRow.id == CreditAllocation.credit_id)
            .where(
                CreditAllocation.tenant_id == tenant.id,
                CreditAllocation.agreement_id == it.agreement_id,
                CreditAllocation.reversed_at.is_(None),
                CreditAllocation.period_start <= it.period_end,
                CreditAllocation.period_end >= it.period_start,
            )
            .order_by(CreditLineRow.credit_date)
        ).all():
            allocations.append(
                {
                    "reference": c.credit_reference,
                    "credit_date": c.credit_date,
                    "method": a.method,
                    "amount": a.amount,
                }
            )
            credit_rows.append(
                [
                    agreement.name,
                    result.period_label,
                    c.credit_reference,
                    c.credit_date.isoformat(),
                    a.method,
                    format(a.amount, "f"),
                    format(c.amount, "f"),
                ]
            )
        lines = _lines(db, tenant, result, run, agreement)
        all_lines.extend(lines.rows)
        if live:
            expected, received, variance, due = (
                live.item.expected,
                live.item.received,
                live.item.variance,
                live.item.due_date,
            )
        else:
            expected, received, variance, due = (
                it.expected,
                it.received_at_creation,
                it.variance_at_creation,
                None,
            )
        sections.append(
            Section(
                it,
                result,
                run.number,
                agreement.name,
                agreement.external_reference or "",
                version.summary,
                expected,
                received,
                variance,
                due,
                trace,
                allocations,
                lines,
            )
        )
    totals = {
        "expected": sum((s.expected for s in sections if s.expected is not None), ZERO),
        "received": sum((s.received for s in sections), ZERO),
        "variance": sum((s.variance for s in sections if s.variance is not None), ZERO),
    }
    events = list(
        db.execute(
            select(ClaimEvent)
            .where(ClaimEvent.claim_id == claim.id)
            .order_by(ClaimEvent.occurred_at)
        ).scalars()
    )
    html = render_html(
        "evidence.html",
        claim=claim,
        supplier=supplier.name,
        organization=tenant.name,
        generated_at=now,
        as_of=today.isoformat(),
        sections=sections,
        totals=totals,
        recovered=recovered_total(db, claim.id),
        events=events,
    )
    summary_rows = [
        [
            s.agreement_name,
            s.result.period_label,
            s.item.period_start.isoformat(),
            s.item.period_end.isoformat(),
            _f(s.expected),
            _f(s.received),
            _f(s.variance),
        ]
        for s in sections
    ]
    summary_rows.append(
        [
            "Total",
            "",
            "",
            "",
            _f(totals["expected"]),
            _f(totals["received"]),
            _f(totals["variance"]),
        ]
    )
    files = {
        f"claim-{claim.number}-evidence.pdf": html_to_pdf(html),
        "summary.csv": (
            "﻿"
            + csv_string(
                ["Agreement", "Period", "Start", "End", "Expected", "Received", "Variance"],
                summary_rows,
            )
        ).encode(),
        "eligible-lines.csv": (
            "﻿"
            + csv_string(
                [
                    "Agreement",
                    "Period",
                    "Eligible",
                    "Invoice",
                    "Line",
                    "SKU",
                    "Invoice date",
                    "Ship date",
                    "Receipt date",
                    "Quantity",
                    "Amount",
                    "Source row",
                ],
                all_lines,
            )
        ).encode(),
        "credits.csv": (
            "﻿"
            + csv_string(
                [
                    "Agreement",
                    "Period",
                    "Credit memo",
                    "Credit date",
                    "Allocation",
                    "Allocated amount",
                    "Credit amount",
                ],
                credit_rows,
            )
        ).encode(),
    }
    return zip_bytes(files), claim.number, len(all_lines)


def _f(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")
