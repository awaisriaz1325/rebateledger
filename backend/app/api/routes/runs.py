"""Calculation runs, results, traces, diffs, version resolutions (SPEC §4.7)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator
from sqlalchemy import select

from app.api.deps import Ctx, Requires, idempotency_key
from app.api.schemas.common import DecimalStr, In, Ok, Out, Page
from app.api.schemas.views import ComponentValueOut, ReasonOut, RunDiffOut, TraceStepOut
from app.core.errors import not_found
from app.core.permissions import Permission
from app.db.models.runs import CalculationRun, PeriodResultRow, PeriodTrace
from app.engine.models import Period, VersionResolution
from app.services import idempotency
from app.services import runs as svc

router = APIRouter(prefix="/api/v1", tags=["runs"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Run = Annotated[Ctx, Depends(Requires(Permission.RUN_RECONCILIATION, write=True))]


class ScopeIn(In):
    type: Literal["all", "supplier", "agreements"] = "all"
    supplier_id: uuid.UUID | None = None
    agreement_ids: Annotated[list[uuid.UUID], Field(default_factory=list, max_length=500)]

    @model_validator(mode="after")
    def _check(self) -> ScopeIn:
        if self.type == "supplier" and self.supplier_id is None:
            raise ValueError("supplier scope needs supplier_id")
        if self.type == "agreements" and not self.agreement_ids:
            raise ValueError("agreements scope needs agreement_ids")
        return self


class RunIn(In):
    scope: ScopeIn
    period_start: date
    period_end: date


class RunOut(Out):
    id: uuid.UUID
    number: int
    status: str
    scope: dict[str, Any]
    period_start: date
    period_end: date
    engine_version: str
    totals: dict[str, Any]
    snapshot: dict[str, Any]
    started_by: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    job_id: uuid.UUID | None
    error: str


class PeriodResultOut(Out):
    id: uuid.UUID
    run_id: uuid.UUID
    agreement_id: uuid.UUID
    agreement_version_id: uuid.UUID
    version_no: int
    supplier_id: uuid.UUID
    period_start: date
    period_end: date
    full_period_start: date
    full_period_end: date
    period_label: str
    expected: DecimalStr | None
    expected_unrounded: DecimalStr | None
    spend: DecimalStr
    quantity: DecimalStr
    measure: DecimalStr
    tier_reached: int | None
    statuses: list[str]
    reasons: list[ReasonOut]
    components: list[ComponentValueOut]
    eligible_count: int
    excluded_counts: dict[str, Any]
    due_date: date
    input_hash: str
    engine_version: str
    stale_at: datetime | None
    stale_reason: str | None


class ResultDetail(PeriodResultOut):
    trace: list[TraceStepOut]
    run_number: int


class ResolutionIn(In):
    agreement_id: uuid.UUID
    period_start: date
    period_end: date
    choice: VersionResolution

    @model_validator(mode="after")
    def _range(self) -> ResolutionIn:
        if self.period_end < self.period_start:
            raise ValueError("period_end is before period_start")
        return self


def _run_out(db: Any, run: CalculationRun) -> RunOut:
    svc.mark_failed_if_job_dead(db, run)
    return RunOut.model_validate(run)


@router.post("/runs", status_code=202, response_model=RunOut)
def start_run(
    body: RunIn, ctx: Run, key: Annotated[str | None, Depends(idempotency_key)]
) -> JSONResponse:
    replay = idempotency.begin(ctx.db, ctx, "POST /runs", key, body.model_dump(mode="json"))
    if replay:
        return JSONResponse(
            replay.body,
            status_code=replay.status,
            headers={"Location": f"/api/v1/jobs/{replay.body['job_id']}"},
        )
    scope = body.scope.model_dump(mode="json", exclude_none=True)
    run = svc.start(
        ctx.db, ctx, scope=scope, period_start=body.period_start, period_end=body.period_end
    )
    out = RunOut.model_validate(run).model_dump(mode="json")
    idempotency.finish(ctx.db, ctx, "POST /runs", key, 202, out)
    return JSONResponse(out, status_code=202, headers={"Location": f"/api/v1/jobs/{run.job_id}"})


@router.get("/runs", response_model=Page[RunOut])
def list_runs(
    ctx: View,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[RunOut]:
    q = select(CalculationRun).where(CalculationRun.tenant_id == ctx.tenant_uuid)
    if cursor:
        q = q.where(CalculationRun.number < cursor)
    rows = list(ctx.db.execute(q.order_by(CalculationRun.number.desc()).limit(limit + 1)).scalars())
    nxt = str(rows[limit - 1].number) if len(rows) > limit else None
    return Page[RunOut](items=[_run_out(ctx.db, r) for r in rows[:limit]], next_cursor=nxt)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: uuid.UUID, ctx: View) -> RunOut:
    return _run_out(ctx.db, svc.get(ctx.db, ctx.tenant_uuid, run_id))


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
def cancel_run(run_id: uuid.UUID, ctx: Run) -> RunOut:
    return RunOut.model_validate(svc.cancel(ctx.db, ctx, run_id))


@router.get("/runs/{run_id}/results", response_model=Page[PeriodResultOut])
def run_results(
    run_id: uuid.UUID,
    ctx: View,
    cursor: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
) -> Page[PeriodResultOut]:
    svc.get(ctx.db, ctx.tenant_uuid, run_id)
    q = select(PeriodResultRow).where(
        PeriodResultRow.tenant_id == ctx.tenant_uuid, PeriodResultRow.run_id == run_id
    )
    if cursor:
        q = q.where(PeriodResultRow.id > cursor)
    rows = list(ctx.db.execute(q.order_by(PeriodResultRow.id).limit(limit + 1)).scalars())
    nxt = str(rows[limit - 1].id) if len(rows) > limit else None
    return Page[PeriodResultOut](
        items=[PeriodResultOut.model_validate(r) for r in rows[:limit]], next_cursor=nxt
    )


@router.get("/runs/{run_id}/diff/{other_run_id}", response_model=RunDiffOut)
def diff_runs(run_id: uuid.UUID, other_run_id: uuid.UUID, ctx: View) -> RunDiffOut:
    a, b = svc.get(ctx.db, ctx.tenant_uuid, run_id), svc.get(ctx.db, ctx.tenant_uuid, other_run_id)
    return RunDiffOut.model_validate(svc.run_diff(ctx.db, ctx.tenant_uuid, a, b))


@router.get("/results/{result_id}", response_model=ResultDetail)
def get_result(result_id: uuid.UUID, ctx: View) -> ResultDetail:
    row = ctx.db.execute(
        select(PeriodResultRow).where(
            PeriodResultRow.id == result_id, PeriodResultRow.tenant_id == ctx.tenant_uuid
        )
    ).scalar_one_or_none()
    if row is None:
        raise not_found("Result")
    trace = (
        ctx.db.execute(select(PeriodTrace.trace).where(PeriodTrace.result_id == row.id)).scalar()
        or []
    )
    run = svc.get(ctx.db, ctx.tenant_uuid, row.run_id)
    return ResultDetail(
        **PeriodResultOut.model_validate(row).model_dump(), trace=trace, run_number=run.number
    )


@router.get("/results/{result_id}/history", response_model=list[PeriodResultOut])
def result_history(result_id: uuid.UUID, ctx: View) -> list[PeriodResultOut]:
    row = ctx.db.execute(
        select(PeriodResultRow).where(
            PeriodResultRow.id == result_id, PeriodResultRow.tenant_id == ctx.tenant_uuid
        )
    ).scalar_one_or_none()
    if row is None:
        raise not_found("Result")
    rows = ctx.db.execute(
        select(PeriodResultRow)
        .join(CalculationRun, CalculationRun.id == PeriodResultRow.run_id)
        .where(
            PeriodResultRow.tenant_id == ctx.tenant_uuid,
            PeriodResultRow.agreement_id == row.agreement_id,
            PeriodResultRow.period_start == row.period_start,
            PeriodResultRow.period_end == row.period_end,
        )
        .order_by(CalculationRun.number.desc())
    ).scalars()
    return [PeriodResultOut.model_validate(r) for r in rows]


@router.put("/version-resolutions", response_model=Ok)
def set_resolution(
    body: ResolutionIn,
    ctx: Annotated[Ctx, Depends(Requires(Permission.EDIT_AGREEMENTS, write=True))],
) -> Ok:
    svc.set_resolution(
        ctx.db, ctx, body.agreement_id, Period(body.period_start, body.period_end), body.choice
    )
    return Ok()
