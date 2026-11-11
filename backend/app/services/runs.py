"""Calculation runs (SPEC §4.7): scope → snapshot → engine → immutable results."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.core.clock import today_in, utcnow
from app.core.errors import AppError, conflict, not_found
from app.db.models.business import (
    Agreement,
    BatchStatus,
    CreditLineRow,
    ImportBatch,
    VersionStatus,
)
from app.db.models.identity import Tenant
from app.db.models.runs import (
    CalculationRun,
    CreditAllocation,
    PeriodResultRow,
    PeriodTrace,
    ReconciliationItem,
    RunInput,
    RunStatus,
    VersionResolutionRow,
)
from app.engine.calculate import PeriodResult, due_date
from app.engine.models import Period, VersionResolution
from app.engine.planner import PeriodJob, PeriodKey, plan_agreement, run_jobs
from app.engine.reconcile import (
    Allocation,
    Credit,
    MatchTarget,
    Tolerance,
    auto_match,
    reconcile_item,
)
from app.engine.version import ENGINE_VERSION
from app.services import agreements as agreement_svc
from app.services.agreement_terms import snapshot_for
from app.services.audit import Actor, record
from app.workers.jobs import JobContext, enqueue, handler

MAX_RANGE_DAYS = 3 * 366
LOOKBACK_DAYS = (
    800  # prior-year and preceding-period baselines for periods starting before the range
)


def _scoped_agreements(db: Session, tenant_id: uuid.UUID, scope: dict[str, Any]) -> list[Agreement]:
    q = select(Agreement).where(Agreement.tenant_id == tenant_id, Agreement.status == "active")
    kind = scope.get("type", "all")
    if kind == "supplier":
        q = q.where(Agreement.supplier_id == uuid.UUID(scope["supplier_id"]))
    elif kind == "agreements":
        q = q.where(Agreement.id.in_([uuid.UUID(a) for a in scope["agreement_ids"]]))
    return list(db.execute(q.order_by(Agreement.id)).scalars())


def start(
    db: Session, ctx: Any, *, scope: dict[str, Any], period_start: date, period_end: date
) -> CalculationRun:
    if period_end < period_start:
        raise AppError(
            422, "RANGE_INVALID", "Invalid range", "The end date is before the start date."
        )
    if (period_end - period_start).days > MAX_RANGE_DAYS:
        raise AppError(
            422, "RANGE_TOO_LONG", "Range too long", "Runs may cover at most three years."
        )
    kind = scope.get("type", "all")
    if kind == "supplier":
        from app.services.suppliers import get as get_supplier

        get_supplier(db, ctx.tenant_uuid, uuid.UUID(scope["supplier_id"]))
    elif kind == "agreements":
        for aid in scope.get("agreement_ids", []):
            agreement_svc.get_agreement(db, ctx.tenant_uuid, uuid.UUID(aid))
    if not _scoped_agreements(db, ctx.tenant_uuid, scope):
        raise conflict("NOTHING_TO_RUN", "No active agreements are in this scope.")
    number = (
        db.execute(
            select(func.max(CalculationRun.number)).where(
                CalculationRun.tenant_id == ctx.tenant_uuid
            )
        ).scalar()
        or 0
    ) + 1
    run = CalculationRun(
        tenant_id=ctx.tenant_uuid,
        number=number,
        scope=scope,
        period_start=period_start,
        period_end=period_end,
        started_by=ctx.user.id,
        engine_version=ENGINE_VERSION,
    )
    db.add(run)
    db.flush()
    # One active run per tenant: others queue behind the same queue_key (SPEC §4.7, §9 case 44).
    job = enqueue(
        db,
        tenant_id=ctx.tenant_uuid,
        job_type="calculation_run",
        payload={"run_id": str(run.id)},
        created_by=ctx.user.id,
        queue_key=f"run:{ctx.tenant_uuid}",
        max_attempts=2,
    )
    run.job_id = job.id
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="run.started",
        object_type="calculation_run",
        object_id=run.id,
        summary={"scope": scope, "from": period_start.isoformat(), "to": period_end.isoformat()},
    )
    return run


def get(db: Session, tenant_id: uuid.UUID, run_id: uuid.UUID) -> CalculationRun:
    run = db.execute(
        select(CalculationRun).where(
            CalculationRun.id == run_id, CalculationRun.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if run is None:
        raise not_found("Run")
    return run


def resolutions(db: Session, tenant_id: uuid.UUID) -> dict[PeriodKey, VersionResolution]:
    rows = db.execute(
        select(VersionResolutionRow).where(VersionResolutionRow.tenant_id == tenant_id)
    ).scalars()
    return {
        (str(r.agreement_id), r.period_start, r.period_end): VersionResolution(r.choice)
        for r in rows
    }


def tolerance_for(tenant: Tenant) -> Tolerance:
    return Tolerance(tenant.abs_tolerance, tenant.pct_tolerance)


def active_allocations(
    db: Session, tenant_id: uuid.UUID, agreement_ids: Sequence[uuid.UUID] | None = None
) -> list[CreditAllocation]:
    q = select(CreditAllocation).where(
        CreditAllocation.tenant_id == tenant_id, CreditAllocation.reversed_at.is_(None)
    )
    if agreement_ids is not None:
        q = q.where(CreditAllocation.agreement_id.in_(list(agreement_ids)))
    return list(db.execute(q).scalars())


def to_alloc(a: CreditAllocation) -> Allocation:
    return Allocation(
        str(a.credit_id), str(a.agreement_id), a.period_start, a.period_end, a.amount, a.method
    )


def to_credit(c: CreditLineRow) -> Credit:
    return Credit(
        str(c.id),
        str(c.supplier_id),
        c.credit_date,
        c.amount,
        c.credit_reference,
        c.agreement_reference,
        c.period_start,
        c.period_end,
        c.period_label,
    )


# --------------------------------------------------------------------------- job


@handler("calculation_run")
def _run_job(db: Session, job: JobContext) -> dict[str, Any]:
    assert job.tenant_id is not None
    run = get(db, job.tenant_id, uuid.UUID(job.payload["run_id"]))
    if run.status == RunStatus.CANCELLED.value:
        return {"status": "cancelled"}
    tenant = db.get(Tenant, run.tenant_id)
    assert tenant is not None
    run.status, run.started_at = RunStatus.RUNNING.value, utcnow()
    resolution_map = resolutions(db, run.tenant_id)
    agreements = _scoped_agreements(db, run.tenant_id, run.scope)
    by_supplier: dict[uuid.UUID, list[Agreement]] = {}
    for a in agreements:
        by_supplier.setdefault(a.supplier_id, []).append(a)
    tol = tolerance_for(tenant)
    today = today_in(tenant.timezone)
    version_ids: list[uuid.UUID] = []
    results_written = 0
    total_expected = Decimal(0)
    needs_review_count = 0
    look_from = run.period_start - timedelta(days=LOOKBACK_DAYS)
    batch_ids = set(
        db.execute(
            select(ImportBatch.id).where(
                ImportBatch.tenant_id == run.tenant_id,
                ImportBatch.status == BatchStatus.COMMITTED.value,
                ImportBatch.import_type.in_(["purchases", "baselines", "credits"]),
            )
        ).scalars()
    )
    baseline_ids: set[uuid.UUID] = set()
    for i, (supplier_id, supplier_agreements) in enumerate(
        sorted(by_supplier.items(), key=lambda kv: str(kv[0]))
    ):
        job.progress(i, len(by_supplier))
        jobs: list[PeriodJob] = []
        names: dict[str, Agreement] = {}
        for a in supplier_agreements:
            versions = [
                v
                for v in agreement_svc.versions(db, run.tenant_id, a.id)
                if v.status in (VersionStatus.ACTIVE.value, VersionStatus.SUPERSEDED.value)
            ]
            if not versions:
                continue
            snaps = [snapshot_for(db, v, a) for v in versions]
            version_ids.extend(v.id for v in versions)
            names[str(a.id)] = a
            jobs.extend(plan_agreement(snaps, run.period_start, run.period_end, resolution_map))
        if not jobs:
            continue
        lines = agreement_svc.purchase_lines(
            db, run.tenant_id, supplier_id, look_from, run.period_end
        )
        base_rows = [
            b for a in supplier_agreements for b in agreement_svc.baselines(db, run.tenant_id, a.id)
        ]
        baseline_ids.update(uuid.UUID(b.baseline_id) for b in base_rows)
        coverage = agreement_svc.data_coverage_start(db, run.tenant_id, supplier_id)
        results = run_jobs(jobs, lines, base_rows, {str(supplier_id): coverage} if coverage else {})
        _auto_match(db, run, supplier_id, results, names)
        allocs = [
            to_alloc(a)
            for a in active_allocations(db, run.tenant_id, [uuid.UUID(k) for k in names])
        ]
        credit_dates = _credit_dates(db, run.tenant_id, {uuid.UUID(a.credit_id) for a in allocs})
        for r in results:
            row = _store_result(db, run, r)
            item = reconcile_item(
                agreement_id=r.agreement_id,
                period=r.period,
                expected=r.expected,
                engine_needs_review=r.needs_review,
                allocations=allocs,
                credit_dates=credit_dates,
                payment_terms_days=r.payment_terms_days,
                today=today,
                tolerance=tol,
            )
            db.add(
                ReconciliationItem(
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    result_id=row.id,
                    received=item.received,
                    variance=item.variance,
                    tolerance=item.tolerance,
                    status=item.status.value,
                    flags=[f.value for f in item.flags],
                    as_of=today,
                )
            )
            results_written += 1
            if r.needs_review:
                needs_review_count += 1
            elif r.expected is not None:
                total_expected += r.expected
        db.flush()
    inputs = [
        {
            "id": uuid.uuid7(),
            "tenant_id": run.tenant_id,
            "run_id": run.id,
            "kind": "version",
            "ref_id": v,
        }
        for v in sorted(set(version_ids))
    ]
    inputs += [
        {
            "id": uuid.uuid7(),
            "tenant_id": run.tenant_id,
            "run_id": run.id,
            "kind": "batch",
            "ref_id": b,
        }
        for b in sorted(batch_ids)
    ]
    inputs += [
        {
            "id": uuid.uuid7(),
            "tenant_id": run.tenant_id,
            "run_id": run.id,
            "kind": "baseline",
            "ref_id": b,
        }
        for b in sorted(baseline_ids)
    ]
    if inputs:
        db.execute(insert(RunInput), inputs)
    run.snapshot = {
        "engine_version": ENGINE_VERSION,
        "tolerance": {"abs": format(tol.abs_amount, "f"), "pct": format(tol.pct, "f")},
        "version_ids": [str(v) for v in sorted(set(version_ids))],
        "batch_ids": [str(b) for b in sorted(batch_ids)],
        "baseline_ids": [str(b) for b in sorted(baseline_ids)],
        "resolutions": {f"{k[0]}|{k[1]}|{k[2]}": v.value for k, v in resolution_map.items()},
        "as_of": today.isoformat(),
        "timezone": tenant.timezone,
    }
    run.totals = {
        "expected": format(total_expected, "f"),
        "needs_review": needs_review_count,
        "results": results_written,
    }
    run.status, run.finished_at = RunStatus.SUCCEEDED.value, utcnow()
    record(
        db,
        tenant_id=run.tenant_id,
        actor=Actor.system("run"),
        action="run.succeeded",
        object_type="calculation_run",
        object_id=run.id,
        summary=run.totals,
    )
    from app.services.notifications import notify_run_finished

    notify_run_finished(db, run)
    job.progress(len(by_supplier), len(by_supplier))
    return {"run_id": str(run.id), **run.totals}


def _credit_dates(db: Session, tenant_id: uuid.UUID, ids: set[uuid.UUID]) -> dict[str, date]:
    if not ids:
        return {}
    rows = db.execute(
        select(CreditLineRow.id, CreditLineRow.credit_date).where(
            CreditLineRow.tenant_id == tenant_id, CreditLineRow.id.in_(list(ids))
        )
    ).all()
    return {str(r[0]): r[1] for r in rows}


def _auto_match(
    db: Session,
    run: CalculationRun,
    supplier_id: uuid.UUID,
    results: list[PeriodResult],
    agreements: dict[str, Agreement],
) -> int:
    """Deterministic auto-match (SPEC §4.7.1 rule 1) for credits not yet allocated."""
    allocated = select(CreditAllocation.credit_id).where(
        CreditAllocation.tenant_id == run.tenant_id, CreditAllocation.reversed_at.is_(None)
    )
    credits = list(
        db.execute(
            select(CreditLineRow).where(
                CreditLineRow.tenant_id == run.tenant_id,
                CreditLineRow.supplier_id == supplier_id,
                CreditLineRow.voided.is_(False),
                CreditLineRow.agreement_reference.is_not(None),
                CreditLineRow.id.not_in(allocated),
            )
        ).scalars()
    )
    if not credits:
        return 0
    targets = [
        MatchTarget(
            r.agreement_id, r.supplier_id, agreements[r.agreement_id].external_reference, r.period
        )
        for r in results
    ]
    matched, _ = auto_match([to_credit(c) for c in credits], targets)
    for m in matched:
        db.add(
            CreditAllocation(
                tenant_id=run.tenant_id,
                credit_id=uuid.UUID(m.credit_id),
                agreement_id=uuid.UUID(m.agreement_id),
                period_start=m.period_start,
                period_end=m.period_end,
                amount=m.amount,
                method="auto",
            )
        )
        record(
            db,
            tenant_id=run.tenant_id,
            actor=Actor.system("auto-match"),
            action="allocation.auto_matched",
            object_type="credit",
            object_id=m.credit_id,
            summary={
                "agreement_id": m.agreement_id,
                "period_start": m.period_start.isoformat(),
                "amount": format(m.amount, "f"),
            },
        )
    db.flush()
    return len(matched)


def _store_result(db: Session, run: CalculationRun, r: PeriodResult) -> PeriodResultRow:
    row = PeriodResultRow(
        tenant_id=run.tenant_id,
        run_id=run.id,
        agreement_id=uuid.UUID(r.agreement_id),
        agreement_version_id=uuid.UUID(r.version_id),
        supplier_id=uuid.UUID(r.supplier_id),
        version_no=r.version_no,
        period_start=r.period.start,
        period_end=r.period.end,
        full_period_start=r.full_period.start,
        full_period_end=r.full_period.end,
        period_label=r.full_period.label,
        expected=r.expected,
        expected_unrounded=r.expected_unrounded,
        spend=r.spend,
        quantity=r.quantity,
        measure=r.measure,
        tier_reached=r.tier_reached,
        components=[
            {
                "component_id": c.component_id,
                "type": c.type.value,
                "value": None if c.value is None else format(c.value, "f"),
                "formula": c.formula,
                "tier_reached": c.tier_reached,
                "baseline": None if c.baseline is None else format(c.baseline, "f"),
            }
            for c in r.components
        ],
        statuses=[s.value for s in r.statuses],
        reasons=[{"code": x.code, "message": x.message} for x in r.reasons],
        eligible_count=r.eligible_count,
        excluded_counts=dict(r.excluded_counts),
        payment_terms_days=r.payment_terms_days,
        due_date=due_date(r),
        input_hash=r.input_hash,
        engine_version=r.engine_version,
    )
    db.add(row)
    db.flush()
    db.add(
        PeriodTrace(tenant_id=run.tenant_id, result_id=row.id, trace=[t.as_dict() for t in r.trace])
    )
    return row


def cancel(db: Session, ctx: Any, run_id: uuid.UUID) -> CalculationRun:
    run = get(db, ctx.tenant_uuid, run_id)
    if run.status not in (RunStatus.QUEUED.value, RunStatus.RUNNING.value):
        raise conflict("RUN_FINISHED", f"Run {run.number} is already {run.status}.")
    from app.db.models.identity import Job

    if run.job_id:
        job = db.get(Job, run.job_id)
        if job is not None:
            job.cancel_requested = True
    if run.status == RunStatus.QUEUED.value:
        run.status = RunStatus.CANCELLED.value
        run.finished_at = utcnow()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="run.cancel_requested",
        object_type="calculation_run",
        object_id=run.id,
    )
    return run


def mark_failed_if_job_dead(db: Session, run: CalculationRun) -> None:
    """Keep run status in step with its job (failed / cancelled workers)."""
    from app.db.models.identity import Job, JobStatus

    if run.status not in (RunStatus.QUEUED.value, RunStatus.RUNNING.value) or run.job_id is None:
        return
    job = db.get(Job, run.job_id)
    if job is None:
        return
    if job.status == JobStatus.DEAD.value:
        run.status, run.error, run.finished_at = (
            RunStatus.FAILED.value,
            "The calculation failed. Retry the run; if it fails again, contact support.",
            utcnow(),
        )
    elif job.status == JobStatus.CANCELLED.value:
        run.status, run.finished_at = RunStatus.CANCELLED.value, utcnow()


# --------------------------------------------------------------------------- latest results + diff


def latest_results_query(tenant_id: uuid.UUID) -> Any:
    """Results of the latest succeeded run per (agreement, full period).

    Ranking by *full* period (not measured window) means a split or re-planned period
    replaces the older result set instead of leaving stale windows behind.
    """
    ranked = (
        select(
            PeriodResultRow.id.label("rid"),
            func.dense_rank()
            .over(
                partition_by=(
                    PeriodResultRow.agreement_id,
                    PeriodResultRow.full_period_start,
                    PeriodResultRow.full_period_end,
                ),
                order_by=(CalculationRun.finished_at.desc(), CalculationRun.number.desc()),
            )
            .label("rn"),
        )
        .join(CalculationRun, CalculationRun.id == PeriodResultRow.run_id)
        .where(
            PeriodResultRow.tenant_id == tenant_id,
            CalculationRun.status == RunStatus.SUCCEEDED.value,
        )
        .subquery()
    )
    return (
        select(PeriodResultRow)
        .join(ranked, ranked.c.rid == PeriodResultRow.id)
        .where(ranked.c.rn == 1)
    )


def run_diff(
    db: Session, tenant_id: uuid.UUID, a: CalculationRun, b: CalculationRun
) -> dict[str, Any]:
    """What changed between two runs (SPEC §4.7): results, inputs, versions, tolerance."""

    def results(run: CalculationRun) -> dict[tuple[str, date, date], PeriodResultRow]:
        rows = db.execute(
            select(PeriodResultRow).where(
                PeriodResultRow.tenant_id == tenant_id, PeriodResultRow.run_id == run.id
            )
        ).scalars()
        return {(str(r.agreement_id), r.period_start, r.period_end): r for r in rows}

    ra, rb = results(a), results(b)
    changes = []
    for key in sorted(set(ra) | set(rb), key=lambda k: (k[0], k[1])):
        x, y = ra.get(key), rb.get(key)
        if x and y and x.input_hash == y.input_hash and x.expected == y.expected:
            continue
        changes.append(
            {
                "agreement_id": key[0],
                "period_start": key[1].isoformat(),
                "period_end": key[2].isoformat(),
                "before": None
                if x is None
                else (None if x.expected is None else format(x.expected, "f")),
                "after": None
                if y is None
                else (None if y.expected is None else format(y.expected, "f")),
                "before_version": x.version_no if x else None,
                "after_version": y.version_no if y else None,
                "before_statuses": x.statuses if x else [],
                "after_statuses": y.statuses if y else [],
                "inputs_changed": bool(x and y and x.input_hash != y.input_hash),
            }
        )
    sa, sb = a.snapshot, b.snapshot
    batches_a, batches_b = set(sa.get("batch_ids", [])), set(sb.get("batch_ids", []))
    return {
        "from_run": a.number,
        "to_run": b.number,
        "results_changed": changes,
        "batches_added": sorted(batches_b - batches_a),
        "batches_removed": sorted(batches_a - batches_b),
        "versions_added": sorted(set(sb.get("version_ids", [])) - set(sa.get("version_ids", []))),
        "versions_removed": sorted(set(sa.get("version_ids", [])) - set(sb.get("version_ids", []))),
        "tolerance_changed": sa.get("tolerance") != sb.get("tolerance"),
        "engine_version_changed": sa.get("engine_version") != sb.get("engine_version"),
    }


def set_resolution(
    db: Session, ctx: Any, agreement_id: uuid.UUID, period: Period, choice: VersionResolution
) -> VersionResolutionRow:
    agreement_svc.get_agreement(db, ctx.tenant_uuid, agreement_id)
    existing = db.execute(
        select(VersionResolutionRow).where(
            VersionResolutionRow.tenant_id == ctx.tenant_uuid,
            VersionResolutionRow.agreement_id == agreement_id,
            VersionResolutionRow.period_start == period.start,
            VersionResolutionRow.period_end == period.end,
        )
    ).scalar_one_or_none()
    if existing:
        existing.choice, existing.decided_by, existing.decided_at = (
            choice.value,
            ctx.user.id,
            utcnow(),
        )
        row = existing
    else:
        row = VersionResolutionRow(
            tenant_id=ctx.tenant_uuid,
            agreement_id=agreement_id,
            period_start=period.start,
            period_end=period.end,
            choice=choice.value,
            decided_by=ctx.user.id,
        )
        db.add(row)
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.version_resolution_set",
        object_type="agreement",
        object_id=agreement_id,
        summary={"period": f"{period.start}..{period.end}", "choice": choice.value},
    )
    from app.services.staleness import mark_stale_for_agreement

    mark_stale_for_agreement(db, ctx.tenant_uuid, agreement_id, "version decision changed")
    return row
