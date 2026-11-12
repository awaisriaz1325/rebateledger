"""Report definitions (SPEC §4.10). Each builder reads tenant data through the same
services the screens use and returns a :class:`Table` with exact Decimal totals, so a
report always agrees with what the user sees on screen."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import today_in
from app.core.errors import AppError, not_found
from app.db.models.business import Agreement, AgreementVersion, ImportBatch, Supplier
from app.db.models.identity import Membership, Tenant, User
from app.db.models.runs import TERMINAL_CLAIM, Claim
from app.exports.writers import Column, Table
from app.services import reconciliation as recon

ZERO = Decimal(0)


@dataclass(frozen=True)
class ReportParams:
    supplier_id: uuid.UUID | None = None
    period_from: date | None = None
    period_to: date | None = None
    status: str | None = None

    @staticmethod
    def parse(raw: dict[str, Any]) -> ReportParams:
        def _date(key: str) -> date | None:
            value = raw.get(key)
            return date.fromisoformat(value) if value else None

        sid = raw.get("supplier_id")
        try:
            return ReportParams(
                supplier_id=uuid.UUID(sid) if sid else None,
                period_from=_date("period_from"),
                period_to=_date("period_to"),
                status=raw.get("status") or None,
            )
        except ValueError as exc:
            raise AppError(
                422, "REPORT_PARAMS_INVALID", "Invalid report filters", str(exc)
            ) from exc

    def as_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.supplier_id:
            out["supplier_id"] = str(self.supplier_id)
        if self.period_from:
            out["period_from"] = self.period_from.isoformat()
        if self.period_to:
            out["period_to"] = self.period_to.isoformat()
        if self.status:
            out["status"] = self.status
        return out


Builder = Callable[[Session, Tenant, ReportParams], Table]


@dataclass(frozen=True)
class ReportDef:
    key: str
    title: str
    description: str
    builder: Builder
    pdf: bool
    filters: tuple[str, ...]
    requires_supplier: bool = False


def _supplier(db: Session, tenant: Tenant, sid: uuid.UUID) -> Supplier:
    s = db.execute(
        select(Supplier).where(Supplier.id == sid, Supplier.tenant_id == tenant.id)
    ).scalar_one_or_none()
    if s is None:
        raise not_found("Supplier")
    return s


def _filter_text(db: Session, tenant: Tenant, p: ReportParams) -> list[tuple[str, str]]:
    out = []
    if p.supplier_id:
        out.append(("Supplier", _supplier(db, tenant, p.supplier_id).name))
    if p.period_from:
        out.append(("Periods from", p.period_from.isoformat()))
    if p.period_to:
        out.append(("Periods to", p.period_to.isoformat()))
    if p.status:
        out.append(("Status", p.status))
    return out


def _sum(rows: list[dict[str, Any]], key: str) -> Decimal:
    return sum((r[key] for r in rows if isinstance(r.get(key), Decimal)), ZERO)


# --------------------------------------------------------------------------- reconciliation

RECON_COLUMNS = (
    Column("supplier", "Supplier"),
    Column("agreement", "Agreement"),
    Column("period", "Period"),
    Column("period_start", "Start", "date"),
    Column("period_end", "End", "date"),
    Column("version", "Version", "int"),
    Column("expected", "Expected", "money"),
    Column("received", "Received", "money"),
    Column("variance", "Variance", "money"),
    Column("status", "Status"),
    Column("due_date", "Due", "date"),
    Column("days_past_due", "Days past due", "int"),
    Column("stale", "Inputs changed since run"),
)


def _recon_rows(db: Session, tenant: Tenant, p: ReportParams) -> list[dict[str, Any]]:
    today = today_in(tenant.timezone)
    statuses = {s.strip() for s in p.status.split(",")} if p.status else None
    rows = []
    for li in recon.live_items(db, tenant, supplier_id=p.supplier_id, today=today):
        r, it = li.result, li.item
        if p.period_from and r.period_end < p.period_from:
            continue
        if p.period_to and r.period_start > p.period_to:
            continue
        if statuses and it.status.value not in statuses:
            continue
        rows.append(
            {
                "supplier": li.supplier_name,
                "agreement": li.agreement_name,
                "period": r.period_label,
                "period_start": r.period_start,
                "period_end": r.period_end,
                "version": r.version_no,
                "expected": it.expected,
                "received": it.received,
                "variance": it.variance,
                "status": it.status.value,
                "due_date": it.due_date,
                "days_past_due": max((today - it.due_date).days, 0),
                "stale": r.stale_at is not None,
            }
        )
    return rows


def reconciliation_summary(db: Session, tenant: Tenant, p: ReportParams) -> Table:
    rows = _recon_rows(db, tenant, p)
    return Table(
        title="Reconciliation summary",
        subtitle="Expected vs received rebate per agreement period",
        columns=RECON_COLUMNS,
        rows=rows,
        filters=_filter_text(db, tenant, p),
        totals={k: _sum(rows, k) for k in ("expected", "received", "variance")},
    )


def supplier_statement(db: Session, tenant: Tenant, p: ReportParams) -> Table:
    if p.supplier_id is None:
        raise AppError(
            422, "SUPPLIER_REQUIRED", "Choose a supplier", "A statement covers one supplier."
        )
    supplier = _supplier(db, tenant, p.supplier_id)
    rows = _recon_rows(db, tenant, p)
    return Table(
        title=f"Supplier statement — {supplier.name}",
        subtitle="All agreements and periods for one supplier",
        columns=[c for c in RECON_COLUMNS if c.key != "supplier"],
        rows=rows,
        filters=_filter_text(db, tenant, p),
        totals={k: _sum(rows, k) for k in ("expected", "received", "variance")},
    )


# --------------------------------------------------------------------------- claims


def _names(db: Session, tenant: Tenant) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]:
    suppliers = dict(
        db.execute(select(Supplier.id, Supplier.name).where(Supplier.tenant_id == tenant.id)).all()
    )
    people = dict(
        db.execute(
            select(User.id, User.name)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.tenant_id == tenant.id)
        ).all()
    )
    return suppliers, people


def _claims(db: Session, tenant: Tenant, p: ReportParams) -> list[Claim]:
    q = select(Claim).where(Claim.tenant_id == tenant.id)
    if p.supplier_id:
        q = q.where(Claim.supplier_id == p.supplier_id)
    if p.status == "open":
        q = q.where(Claim.status.not_in([s.value for s in TERMINAL_CLAIM]))
    elif p.status == "closed":
        q = q.where(Claim.status.in_([s.value for s in TERMINAL_CLAIM]))
    elif p.status:
        q = q.where(Claim.status.in_([s.strip() for s in p.status.split(",")]))
    if p.period_from:
        q = q.where(Claim.created_at >= p.period_from)
    if p.period_to:
        q = q.where(Claim.created_at < _day_after(p.period_to))
    return list(db.execute(q.order_by(Claim.number)).scalars())


def _day_after(d: date) -> date:
    return date.fromordinal(d.toordinal() + 1)


def claims_register(db: Session, tenant: Tenant, p: ReportParams) -> Table:
    from app.services.claims import recovered_total

    suppliers, people = _names(db, tenant)
    rows = [
        {
            "number": c.number,
            "title": c.title,
            "supplier": suppliers.get(c.supplier_id, ""),
            "status": c.status,
            "identified": c.identified_amount,
            "claimed": c.claimed_amount,
            "recovered": recovered_total(db, c.id),
            "assignee": people.get(c.assignee_id, "") if c.assignee_id else "",
            "opened": c.created_at.date(),
            "submitted": c.submitted_at.date() if c.submitted_at else None,
            "due": c.due_date,
            "closed": c.resolved_at.date() if c.resolved_at else None,
        }
        for c in _claims(db, tenant, p)
    ]
    return Table(
        title="Claims register",
        subtitle="Every claim with identified, claimed and recovered amounts",
        columns=[
            Column("number", "Claim", "int"),
            Column("title", "Title"),
            Column("supplier", "Supplier"),
            Column("status", "Status"),
            Column("identified", "Identified", "money"),
            Column("claimed", "Claimed", "money"),
            Column("recovered", "Recovered", "money"),
            Column("assignee", "Assignee"),
            Column("opened", "Opened", "date"),
            Column("submitted", "Submitted", "date"),
            Column("due", "Due", "date"),
            Column("closed", "Closed", "date"),
        ],
        rows=rows,
        filters=_filter_text(db, tenant, p),
        totals={k: _sum(rows, k) for k in ("identified", "claimed", "recovered")},
    )


def recovery_report(db: Session, tenant: Tenant, p: ReportParams) -> Table:
    """Identified vs recovered per supplier. Recovered = credits linked to claims only."""
    from app.services.claims import recovered_total

    suppliers, _ = _names(db, tenant)
    by: dict[uuid.UUID, dict[str, Any]] = {}
    for c in _claims(db, tenant, p):
        row = by.setdefault(
            c.supplier_id,
            {
                "supplier": suppliers.get(c.supplier_id, ""),
                "claims": 0,
                "identified": ZERO,
                "claimed": ZERO,
                "recovered": ZERO,
                "written_off": ZERO,
                "open": ZERO,
            },
        )
        recovered = recovered_total(db, c.id)
        row["claims"] += 1
        row["identified"] += c.identified_amount
        row["claimed"] += c.claimed_amount
        row["recovered"] += recovered
        if c.status == "written_off":
            row["written_off"] += max(c.claimed_amount - recovered, ZERO)
        elif c.status not in {s.value for s in TERMINAL_CLAIM}:
            row["open"] += max(c.claimed_amount - recovered, ZERO)
    rows = sorted(by.values(), key=lambda r: r["supplier"])
    for r in rows:
        r["rate"] = (
            (r["recovered"] / r["claimed"] * 100).quantize(Decimal("0.1")) if r["claimed"] else None
        )
    return Table(
        title="Recovery report",
        subtitle="Identified vs recovered by supplier (recovered = linked supplier credits)",
        columns=[
            Column("supplier", "Supplier"),
            Column("claims", "Claims", "int"),
            Column("identified", "Identified", "money"),
            Column("claimed", "Claimed", "money"),
            Column("recovered", "Recovered", "money"),
            Column("written_off", "Written off", "money"),
            Column("open", "Still open", "money"),
            Column("rate", "Recovered % of claimed", "number"),
        ],
        rows=rows,
        filters=_filter_text(db, tenant, p),
        totals={
            k: _sum(rows, k) for k in ("identified", "claimed", "recovered", "written_off", "open")
        },
    )


# --------------------------------------------------------------------------- registers


def agreement_register(db: Session, tenant: Tenant, p: ReportParams) -> Table:
    q = (
        select(Agreement, Supplier.name)
        .join(Supplier, Supplier.id == Agreement.supplier_id)
        .where(Agreement.tenant_id == tenant.id)
    )
    if p.supplier_id:
        q = q.where(Agreement.supplier_id == p.supplier_id)
    rows = []
    for a, supplier_name in db.execute(q.order_by(Supplier.name, Agreement.name)).all():
        versions = list(
            db.execute(
                select(AgreementVersion)
                .where(
                    AgreementVersion.agreement_id == a.id, AgreementVersion.tenant_id == tenant.id
                )
                .order_by(AgreementVersion.version_no)
            ).scalars()
        )
        active = next((v for v in reversed(versions) if v.status == "active"), None)
        latest = versions[-1] if versions else None
        shown = active or latest
        rows.append(
            {
                "supplier": supplier_name,
                "agreement": a.name,
                "reference": a.external_reference or "",
                "status": "archived"
                if a.status == "archived"
                else (latest.status if latest else ""),
                "active_version": active.version_no if active else None,
                "effective_from": shown.effective_from if shown else None,
                "effective_to": shown.effective_to if shown else None,
                "period": shown.period_type if shown else "",
                "summary": shown.summary if shown else "",
            }
        )
    return Table(
        title="Agreement register",
        subtitle="Every rebate agreement and its current terms",
        columns=[
            Column("supplier", "Supplier"),
            Column("agreement", "Agreement"),
            Column("reference", "Reference"),
            Column("status", "Status"),
            Column("active_version", "Active version", "int"),
            Column("effective_from", "Effective from", "date"),
            Column("effective_to", "Effective to", "date"),
            Column("period", "Period"),
            Column("summary", "Terms summary"),
        ],
        rows=rows,
        filters=_filter_text(db, tenant, p),
    )


def import_history(db: Session, tenant: Tenant, p: ReportParams) -> Table:
    q = select(ImportBatch).where(ImportBatch.tenant_id == tenant.id)
    if p.period_from:
        q = q.where(ImportBatch.created_at >= p.period_from)
    if p.period_to:
        q = q.where(ImportBatch.created_at < _day_after(p.period_to))
    rows = []
    for b in db.execute(q.order_by(ImportBatch.created_at.desc())).scalars():
        s = b.stats or {}
        rows.append(
            {
                "uploaded": b.created_at,
                "file": b.filename,
                "type": b.import_type,
                "status": b.status,
                "rows_read": s.get("rows_read"),
                "committed": s.get("rows_committed"),
                "skipped": s.get("rows_skipped"),
                "duplicates": s.get("duplicates"),
                "date_from": s.get("date_from") or "",
                "date_to": s.get("date_to") or "",
                "voided": b.void_reason if b.voided_at else "",
            }
        )
    return Table(
        title="Import history",
        subtitle="Every uploaded file and what it changed",
        columns=[
            Column("uploaded", "Uploaded", "datetime"),
            Column("file", "File"),
            Column("type", "Type"),
            Column("status", "Status"),
            Column("rows_read", "Rows read", "int"),
            Column("committed", "Committed", "int"),
            Column("skipped", "Skipped", "int"),
            Column("duplicates", "Duplicates", "int"),
            Column("date_from", "Data from"),
            Column("date_to", "Data to"),
            Column("voided", "Void reason"),
        ],
        rows=rows,
        filters=_filter_text(db, tenant, p),
    )


REPORTS: dict[str, ReportDef] = {
    d.key: d
    for d in (
        ReportDef(
            "reconciliation_summary",
            "Reconciliation summary",
            "Expected vs received per agreement period, with totals.",
            reconciliation_summary,
            True,
            ("supplier_id", "period_from", "period_to", "status"),
        ),
        ReportDef(
            "supplier_statement",
            "Supplier statement",
            "Everything for one supplier: periods, credits received and what is still owed.",
            supplier_statement,
            True,
            ("supplier_id", "period_from", "period_to"),
            requires_supplier=True,
        ),
        ReportDef(
            "claims_register",
            "Claims register",
            "Every claim with identified, claimed and recovered amounts.",
            claims_register,
            True,
            ("supplier_id", "status", "period_from", "period_to"),
        ),
        ReportDef(
            "recovery_report",
            "Recovery report",
            "Identified vs recovered by supplier.",
            recovery_report,
            True,
            ("supplier_id", "period_from", "period_to"),
        ),
        ReportDef(
            "agreement_register",
            "Agreement register",
            "All agreements with their current terms.",
            agreement_register,
            False,
            ("supplier_id",),
        ),
        ReportDef(
            "import_history",
            "Import history",
            "Every file imported, with row counts and voids.",
            import_history,
            False,
            ("period_from", "period_to"),
        ),
    )
}


def build(db: Session, tenant: Tenant, key: str, raw: dict[str, Any]) -> Table:
    definition = REPORTS.get(key)
    if definition is None:
        raise not_found("Report")
    params = ReportParams.parse(raw)
    if definition.requires_supplier and params.supplier_id is None:
        raise AppError(
            422, "SUPPLIER_REQUIRED", "Choose a supplier", "This report covers one supplier."
        )
    return definition.builder(db, tenant, params)
