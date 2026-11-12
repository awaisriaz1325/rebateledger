"""Agreements, versions, approvals and dry-run preview (SPEC §4.4)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import AppError, conflict, forbidden, not_found
from app.core.permissions import Permission
from app.db.models.business import (
    Agreement,
    AgreementVersion,
    Approval,
    BaselineRow,
    PurchaseLineRow,
    Supplier,
    VersionStatus,
)
from app.db.models.runs import Claim
from app.engine.calculate import PeriodResult, calculate
from app.engine.models import Baseline, CalcOptions, Period, PurchaseLine, VersionSnapshot
from app.engine.periods import clip, periods_overlapping, prior_period
from app.services import subscriptions, suppliers
from app.services.agreement_terms import (
    VersionTermsIn,
    snapshot_for,
    to_snapshot,
    warnings_for,
    write_rows,
)
from app.services.audit import record


def get_agreement(db: Session, tenant_id: uuid.UUID, agreement_id: uuid.UUID) -> Agreement:
    a = db.execute(
        select(Agreement).where(Agreement.id == agreement_id, Agreement.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if a is None:
        raise not_found("Agreement")
    return a


def get_version(
    db: Session, tenant_id: uuid.UUID, version_id: uuid.UUID, *, lock: bool = False
) -> tuple[AgreementVersion, Agreement]:
    q = select(AgreementVersion).where(
        AgreementVersion.id == version_id, AgreementVersion.tenant_id == tenant_id
    )
    if lock:
        q = q.with_for_update()
    v = db.execute(q).scalar_one_or_none()
    if v is None:
        raise not_found("Agreement version")
    return v, get_agreement(db, tenant_id, v.agreement_id)


def versions(db: Session, tenant_id: uuid.UUID, agreement_id: uuid.UUID) -> list[AgreementVersion]:
    return list(
        db.execute(
            select(AgreementVersion)
            .where(
                AgreementVersion.tenant_id == tenant_id,
                AgreementVersion.agreement_id == agreement_id,
            )
            .order_by(AgreementVersion.version_no)
        ).scalars()
    )


def _fiscal_start(ctx: Any) -> int:
    assert ctx.tenant is not None
    return int(ctx.tenant.fiscal_year_start_month)


def _validate(
    ctx: Any, terms: VersionTermsIn, agreement: Agreement, version_id: uuid.UUID, version_no: int
) -> VersionSnapshot:
    return to_snapshot(
        terms,
        agreement_id=str(agreement.id),
        version_id=str(version_id),
        version_no=version_no,
        supplier_id=str(agreement.supplier_id),
        fiscal_start=_fiscal_start(ctx),
        name=agreement.name,
        external_reference=agreement.external_reference,
    )


def create(
    db: Session,
    ctx: Any,
    *,
    supplier_id: uuid.UUID,
    name: str,
    external_reference: str | None,
    notes: str,
    terms: VersionTermsIn,
) -> tuple[Agreement, AgreementVersion, list[str]]:
    suppliers.get(db, ctx.tenant_uuid, supplier_id)
    ref = external_reference.strip() if external_reference else None
    if ref:
        dup = db.execute(
            select(Agreement.id).where(
                Agreement.tenant_id == ctx.tenant_uuid,
                func.lower(Agreement.external_reference) == ref.lower(),
            )
        ).first()
        if dup:
            raise conflict(
                "REFERENCE_IN_USE", "Another agreement already uses this external reference."
            )
    a = Agreement(
        tenant_id=ctx.tenant_uuid,
        supplier_id=supplier_id,
        name=name,
        external_reference=ref or None,
        notes=notes,
        owner_user_id=ctx.user.id,
        created_by=ctx.user.id,
    )
    db.add(a)
    db.flush()
    v = _new_draft(db, ctx, a, terms, 1)
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.created",
        object_type="agreement",
        object_id=a.id,
        summary={"name": name},
    )
    return a, v, warnings_for(terms)


def _new_draft(
    db: Session, ctx: Any, a: Agreement, terms: VersionTermsIn, version_no: int
) -> AgreementVersion:
    v = AgreementVersion(
        tenant_id=ctx.tenant_uuid,
        agreement_id=a.id,
        version_no=version_no,
        status=VersionStatus.DRAFT.value,
        effective_from=terms.effective_from,
        period_type=terms.period_type.value,
        fiscal_year_start_month=1,
        date_basis=terms.date_basis.value,
        measure=terms.measure.value,
        spend_basis=terms.spend_basis.value,
        threshold_comparison=terms.threshold_comparison.value,
        negative_result=terms.negative_result.value,
        rounding_mode=terms.rounding_mode.value,
        payment_terms_days=terms.payment_terms_days,
        stacking=terms.stacking.value,
        prorate_thresholds_on_partial_period=terms.prorate_thresholds_on_partial_period,
        zero_baseline_policy=terms.zero_baseline_policy.value,
        created_by=ctx.user.id,
    )
    db.add(v)
    db.flush()
    snapshot = _validate(ctx, terms, a, v.id, version_no)
    write_rows(db, v, terms, snapshot)
    return v


def new_version(
    db: Session, ctx: Any, agreement_id: uuid.UUID, terms: VersionTermsIn
) -> tuple[AgreementVersion, list[str]]:
    a = get_agreement(db, ctx.tenant_uuid, agreement_id)
    if a.status == "archived":
        raise conflict("AGREEMENT_ARCHIVED", "Unarchive the agreement before adding a version.")
    drafts = [
        v
        for v in versions(db, ctx.tenant_uuid, a.id)
        if v.status in (VersionStatus.DRAFT.value, VersionStatus.PENDING_APPROVAL.value)
    ]
    if drafts:
        raise conflict(
            "DRAFT_EXISTS",
            f"Version {drafts[0].version_no} is still a draft or awaiting approval. Finish or delete it first.",
        )
    next_no = (
        db.execute(
            select(func.max(AgreementVersion.version_no)).where(
                AgreementVersion.agreement_id == a.id
            )
        ).scalar()
        or 0
    ) + 1
    v = _new_draft(db, ctx, a, terms, next_no)
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.version_created",
        object_type="agreement_version",
        object_id=v.id,
        summary={"version_no": next_no},
    )
    return v, warnings_for(terms)


def update_draft(
    db: Session, ctx: Any, version_id: uuid.UUID, terms: VersionTermsIn, expected_version: int
) -> tuple[AgreementVersion, list[str]]:
    v, a = get_version(db, ctx.tenant_uuid, version_id, lock=True)
    if v.status != VersionStatus.DRAFT.value:
        raise conflict(
            "VERSION_NOT_EDITABLE",
            f"Version {v.version_no} is {v.status}. Active versions are immutable: create a new version with an effective date.",
        )
    if v.row_version != expected_version:
        raise AppError(
            412,
            "PRECONDITION_FAILED",
            "Changed by someone else",
            "This draft was changed by someone else. Reload to see the latest version.",
        )
    snapshot = _validate(ctx, terms, a, v.id, v.version_no)
    write_rows(db, v, terms, snapshot)
    v.updated_by = ctx.user.id
    v.updated_at = utcnow()
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.draft_updated",
        object_type="agreement_version",
        object_id=v.id,
    )
    return v, warnings_for(terms)


def delete_draft(db: Session, ctx: Any, version_id: uuid.UUID) -> None:
    v, a = get_version(db, ctx.tenant_uuid, version_id, lock=True)
    if v.status != VersionStatus.DRAFT.value:
        raise conflict("VERSION_NOT_EDITABLE", "Only drafts can be deleted.")
    if len(versions(db, ctx.tenant_uuid, a.id)) == 1:
        raise conflict(
            "LAST_VERSION",
            "An agreement needs at least one version; archive the agreement instead.",
        )
    db.delete(v)
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.draft_deleted",
        object_type="agreement_version",
        object_id=v.id,
    )


# --------------------------------------------------------------------------- activation


def _overlap_plan(db: Session, ctx: Any, v: AgreementVersion) -> list[AgreementVersion]:
    """Versions that the new one supersedes. Raises if the ranges cannot be resolved."""
    to_supersede = []
    new_end = v.effective_to or date.max
    for other in versions(db, ctx.tenant_uuid, v.agreement_id):
        if other.id == v.id or other.status not in (
            VersionStatus.ACTIVE.value,
            VersionStatus.SUPERSEDED.value,
        ):
            continue
        other_end = other.effective_to or date.max
        if other.effective_from > new_end or v.effective_from > other_end:
            continue
        if other.status == VersionStatus.ACTIVE.value and other.effective_from < v.effective_from:
            to_supersede.append(other)
            continue
        raise conflict(
            "VERSION_OVERLAP",
            f"Version {v.version_no} ({v.effective_from} – {v.effective_to or 'open'}) overlaps version {other.version_no} "
            f"({other.effective_from} – {other.effective_to or 'open'}). A new version must start after the version it replaces.",
        )
    return to_supersede


def request_activation(
    db: Session, ctx: Any, version_id: uuid.UUID, note: str = ""
) -> AgreementVersion:
    v, a = get_version(db, ctx.tenant_uuid, version_id, lock=True)
    if v.status != VersionStatus.DRAFT.value:
        raise conflict("VERSION_NOT_DRAFT", f"Version {v.version_no} is {v.status}.")
    if a.status == "archived":
        raise conflict("AGREEMENT_ARCHIVED", "Unarchive the agreement first.")
    _overlap_plan(db, ctx, v)
    snapshot_for(db, v, a)  # re-validate stored terms
    assert ctx.tenant is not None
    if ctx.tenant.four_eyes_activation:
        v.status = VersionStatus.PENDING_APPROVAL.value
        v.submitted_by, v.submitted_at = ctx.user.id, utcnow()
        approval = Approval(
            tenant_id=ctx.tenant_uuid,
            object_type="agreement_version",
            object_id=v.id,
            requested_by=ctx.user.id,
            request_note=note,
        )
        db.add(approval)
        db.flush()
        record(
            db,
            tenant_id=ctx.tenant_uuid,
            actor=ctx.actor,
            action="agreement.activation_requested",
            object_type="agreement_version",
            object_id=v.id,
            summary={"approval_id": str(approval.id)},
        )
        return v
    _activate(db, ctx, v, a)
    return v


def _activate(db: Session, ctx: Any, v: AgreementVersion, a: Agreement) -> None:
    supersede = _overlap_plan(db, ctx, v)
    already_active = any(
        o.status == VersionStatus.ACTIVE.value for o in versions(db, ctx.tenant_uuid, a.id)
    )
    if not already_active:
        subscriptions.check(db, ctx.tenant_uuid, agreements=1)
    for old in supersede:
        old.status = VersionStatus.SUPERSEDED.value
        old.superseded_at = utcnow()
        old.effective_to = v.effective_from - timedelta(days=1)
        record(
            db,
            tenant_id=ctx.tenant_uuid,
            actor=ctx.actor,
            action="agreement.version_superseded",
            object_type="agreement_version",
            object_id=old.id,
            summary={"effective_to": old.effective_to.isoformat(), "by_version": v.version_no},
        )
    db.flush()
    v.status = VersionStatus.ACTIVE.value
    v.activated_by, v.activated_at = ctx.user.id, utcnow()
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.version_activated",
        object_type="agreement_version",
        object_id=v.id,
        summary={"version_no": v.version_no},
    )
    from app.services.staleness import mark_stale_for_agreement

    mark_stale_for_agreement(db, ctx.tenant_uuid, a.id, f"version {v.version_no} activated")


def list_approvals(db: Session, tenant_id: uuid.UUID, status: str = "pending") -> list[Approval]:
    return list(
        db.execute(
            select(Approval)
            .where(Approval.tenant_id == tenant_id, Approval.status == status)
            .order_by(Approval.requested_at)
        ).scalars()
    )


def describe_approvals(
    db: Session, tenant_id: uuid.UUID, approvals: list[Approval]
) -> dict[uuid.UUID, tuple[str, str]]:
    """Human label and in-app link for each approval, resolved in two queries."""
    version_ids = [a.object_id for a in approvals if a.object_type == "agreement_version"]
    claim_ids = [a.object_id for a in approvals if a.object_type == "claim_write_off"]
    out: dict[uuid.UUID, tuple[str, str]] = {}
    if version_ids:
        rows = db.execute(
            select(
                AgreementVersion.id,
                AgreementVersion.version_no,
                Agreement.id,
                Agreement.name,
                Supplier.name,
            )
            .join(Agreement, Agreement.id == AgreementVersion.agreement_id)
            .join(Supplier, Supplier.id == Agreement.supplier_id)
            .where(AgreementVersion.tenant_id == tenant_id, AgreementVersion.id.in_(version_ids))
        ).all()
        for vid, vno, aid, aname, sname in rows:
            out[vid] = (f"Activate {aname} v{vno} ({sname})", f"/app/agreements/{aid}")
    if claim_ids:
        claim_rows = db.execute(
            select(Claim.id, Claim.number, Claim.title).where(
                Claim.tenant_id == tenant_id, Claim.id.in_(claim_ids)
            )
        ).all()
        for cid, number, title in claim_rows:
            out[cid] = (f"Write off claim #{number}: {title}", f"/app/claims/{cid}")
    return out


def _approval(db: Session, ctx: Any, approval_id: uuid.UUID) -> Approval:
    ap = db.execute(
        select(Approval)
        .where(Approval.id == approval_id, Approval.tenant_id == ctx.tenant_uuid)
        .with_for_update()
    ).scalar_one_or_none()
    if ap is None:
        raise not_found("Approval")
    if ap.status != "pending":
        raise conflict("APPROVAL_DECIDED", f"This request was already {ap.status}.")
    return ap


def decide(
    db: Session, ctx: Any, approval_id: uuid.UUID, approve: bool, note: str = ""
) -> Approval:
    """Four-eyes: the decider must be a different user who holds APPROVE *now*.

    Identity, not role, is compared, so changing anyone's role mid-flow cannot
    enable self-approval; the database CHECK constraint enforces it too.
    """
    ap = _approval(db, ctx, approval_id)
    if not ctx.can(Permission.APPROVE):
        raise forbidden("Only an Admin or Owner can approve.")
    if ap.requested_by == ctx.user.id:
        raise AppError(
            403,
            "SELF_APPROVAL",
            "You cannot approve your own request",
            "A different Admin or Owner must approve this.",
        )
    ap.status = "approved" if approve else "rejected"
    ap.decided_by, ap.decided_at, ap.decision_note = ctx.user.id, utcnow(), note
    db.flush()
    if ap.object_type == "agreement_version":
        v, a = get_version(db, ctx.tenant_uuid, ap.object_id, lock=True)
        if v.status != VersionStatus.PENDING_APPROVAL.value:
            raise conflict("VERSION_NOT_PENDING", "This version is no longer awaiting approval.")
        if approve:
            _activate(db, ctx, v, a)
        else:
            v.status = VersionStatus.DRAFT.value
    else:
        from app.services.claims import apply_write_off_decision

        apply_write_off_decision(db, ctx, ap, approve)
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action=f"approval.{ap.status}",
        object_type=ap.object_type,
        object_id=ap.object_id,
        summary={"approval_id": str(ap.id)},
    )
    return ap


def cancel_request(db: Session, ctx: Any, approval_id: uuid.UUID) -> None:
    ap = _approval(db, ctx, approval_id)
    if ap.requested_by != ctx.user.id and not ctx.can(Permission.APPROVE):
        raise forbidden("Only the requester or an approver can cancel this request.")
    ap.status = "cancelled"
    if ap.object_type == "agreement_version":
        v, _ = get_version(db, ctx.tenant_uuid, ap.object_id, lock=True)
        if v.status == VersionStatus.PENDING_APPROVAL.value:
            v.status = VersionStatus.DRAFT.value
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="approval.cancelled",
        object_type=ap.object_type,
        object_id=ap.object_id,
    )


def set_archived(db: Session, ctx: Any, agreement_id: uuid.UUID, archived: bool) -> Agreement:
    a = get_agreement(db, ctx.tenant_uuid, agreement_id)
    a.status = "archived" if archived else "active"
    if not archived:
        has_active = any(
            v.status == VersionStatus.ACTIVE.value for v in versions(db, ctx.tenant_uuid, a.id)
        )
        if has_active:
            subscriptions.check(db, ctx.tenant_uuid, agreements=1)
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.archived" if archived else "agreement.unarchived",
        object_type="agreement",
        object_id=a.id,
    )
    return a


# --------------------------------------------------------------------------- engine inputs from the DB


_LINE_COLUMNS = (
    PurchaseLineRow.id,
    PurchaseLineRow.supplier_id,
    PurchaseLineRow.quantity,
    PurchaseLineRow.amount,
    PurchaseLineRow.sku,
    PurchaseLineRow.invoice_date,
    PurchaseLineRow.ship_date,
    PurchaseLineRow.receipt_date,
    PurchaseLineRow.branch,
    PurchaseLineRow.category,
    PurchaseLineRow.flags,
)


def purchase_lines(
    db: Session, tenant_id: uuid.UUID, supplier_id: uuid.UUID, start: date, end: date
) -> list[PurchaseLine]:
    """Non-voided lines of a supplier with any basis date (or none) touching the range.

    Selects plain columns rather than ORM entities: at 100k lines entity hydration was
    most of the cost of a tier-tracker or run request (Phase 10 load test)."""
    rows = db.execute(
        select(*_LINE_COLUMNS).where(
            PurchaseLineRow.tenant_id == tenant_id,
            PurchaseLineRow.supplier_id == supplier_id,
            PurchaseLineRow.voided.is_(False),
            (
                (PurchaseLineRow.invoice_date.between(start, end))
                | (PurchaseLineRow.ship_date.between(start, end))
                | (PurchaseLineRow.receipt_date.between(start, end))
                | (
                    PurchaseLineRow.invoice_date.is_(None)
                    & PurchaseLineRow.ship_date.is_(None)
                    & PurchaseLineRow.receipt_date.is_(None)
                )
            ),
        )
    )
    return [to_line(r) for r in rows]


class _LineLike(Protocol):
    """A purchase-line ORM row or a column-tuple Row with the same names."""

    @property
    def id(self) -> object: ...
    @property
    def supplier_id(self) -> uuid.UUID: ...
    @property
    def quantity(self) -> Decimal: ...
    @property
    def amount(self) -> Decimal: ...
    @property
    def sku(self) -> str: ...
    @property
    def invoice_date(self) -> date | None: ...
    @property
    def ship_date(self) -> date | None: ...
    @property
    def receipt_date(self) -> date | None: ...
    @property
    def branch(self) -> str | None: ...
    @property
    def category(self) -> str | None: ...
    @property
    def flags(self) -> dict[str, Any]: ...


def to_line(r: _LineLike) -> PurchaseLine:
    return PurchaseLine(
        line_id=str(r.id),
        supplier_id=str(r.supplier_id),
        quantity=r.quantity,
        amount=r.amount,
        sku=r.sku,
        invoice_date=r.invoice_date,
        ship_date=r.ship_date,
        receipt_date=r.receipt_date,
        branch=r.branch,
        category=r.category,
        flags=PurchaseLine.make_flags({k: bool(v) for k, v in r.flags.items()}),
    )


def lines_needed_from(snap: VersionSnapshot, full: Period) -> date:
    """Earliest basis date the engine can read for ``full``: the period start, or the start
    of a prior-period baseline when a growth component computes one from purchase lines."""
    start = full.start
    for comp in snap.components:
        if comp.is_growth and comp.prior_period_offset is not None:
            prior = prior_period(
                full,
                comp.prior_period_offset,
                snap.period_type,
                snap.fiscal_year_start_month,
                snap.custom_periods,
            )
            if prior is not None:
                start = min(start, prior.start)
    return start


def baselines(db: Session, tenant_id: uuid.UUID, agreement_id: uuid.UUID) -> list[Baseline]:
    rows = db.execute(
        select(BaselineRow).where(
            BaselineRow.tenant_id == tenant_id,
            BaselineRow.agreement_id == agreement_id,
            BaselineRow.voided.is_(False),
        )
    ).scalars()
    return [
        Baseline(str(r.agreement_id), r.period_start, r.period_end, r.value, str(r.id))
        for r in rows
    ]


def data_coverage_start(db: Session, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> date | None:
    """Earliest basis date imported for the supplier — the point from which history is assumed complete."""
    return db.execute(
        select(
            func.min(
                func.least(
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


def preview(db: Session, ctx: Any, version_id: uuid.UUID, period_start: date) -> PeriodResult:
    """Dry run of a (draft) version against imported data for the period containing
    ``period_start``; nothing is saved (SPEC §4.4.5)."""
    v, a = get_version(db, ctx.tenant_uuid, version_id)
    snap = snapshot_for(db, v, a)
    candidates = periods_overlapping(
        snap.period_type,
        snap.fiscal_year_start_month,
        period_start,
        period_start,
        snap.custom_periods,
    )
    if not candidates:
        raise AppError(
            422, "PERIOD_INVALID", "No period", "No period of this agreement contains that date."
        )
    full = candidates[0]
    eff = snap.effective_period
    window = clip(full, eff.start, eff.end)
    if window is None:
        raise AppError(
            422,
            "PERIOD_INVALID",
            "Outside effective range",
            "This version is not effective in that period.",
        )
    look_back = date(max(full.start.year - 1, 1), 1, 1)
    lines = purchase_lines(db, ctx.tenant_uuid, a.supplier_id, look_back, full.end)
    return calculate(
        snap,
        window,
        lines,
        baselines(db, ctx.tenant_uuid, a.id),
        CalcOptions(
            data_coverage_start=data_coverage_start(db, ctx.tenant_uuid, a.supplier_id),
            full_period=Period(full.start, full.end, full.label),
        ),
    )
