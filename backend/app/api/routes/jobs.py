"""Job status resource for 202 responses (SPEC §6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import Ctx, Requires
from app.api.schemas.common import Ok, Out
from app.core.errors import not_found
from app.core.permissions import Permission
from app.db.models.identity import Job, JobStatus

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


class JobOut(Out):
    id: uuid.UUID
    type: str
    status: str
    progress: int
    total: int | None
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def get_job(ctx: Ctx, job_id: uuid.UUID) -> Job:
    job = ctx.db.execute(
        select(Job).where(Job.id == job_id, Job.tenant_id == ctx.tenant_uuid)
    ).scalar_one_or_none()
    if job is None or job.type == "send_email":
        raise not_found("Job")
    return job


@router.get("/{job_id}", response_model=JobOut)
def job_status(
    job_id: uuid.UUID, ctx: Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
) -> JobOut:
    return JobOut.model_validate(get_job(ctx, job_id))


@router.post("/{job_id}/cancel", response_model=Ok)
def cancel_job(
    job_id: uuid.UUID, ctx: Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
) -> Ok:
    job = get_job(ctx, job_id)
    if job.created_by != ctx.user.id and not ctx.can(Permission.MANAGE_SETTINGS):
        from app.core.errors import forbidden

        raise forbidden("Only the person who started this job or an Admin can cancel it.")
    if job.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
        job.cancel_requested = True
    return Ok()
