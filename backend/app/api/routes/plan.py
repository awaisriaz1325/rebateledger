"""Plan and usage, read-only for the tenant (SPEC §4.13 "Plan & usage")."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Ctx, Requires
from app.api.schemas.common import Out
from app.core.permissions import Permission
from app.services import subscriptions

router = APIRouter(prefix="/api/v1/org", tags=["organization"])


class PlanUsageOut(Out):
    plan_code: str | None
    plan_name: str | None
    status: str | None
    limits: dict[str, int | None]
    usage: dict[str, int]


@router.get("/plan", response_model=PlanUsageOut)
def plan_usage(ctx: Annotated[Ctx, Depends(Requires(Permission.VIEW_BILLING))]) -> PlanUsageOut:
    lim = subscriptions.limits(ctx.db, ctx.tenant_uuid)
    use = subscriptions.usage(ctx.db, ctx.tenant_uuid)
    if lim is None:
        return PlanUsageOut(plan_code=None, plan_name=None, status=None, limits={}, usage=use)
    return PlanUsageOut(
        plan_code=lim.plan_code,
        plan_name=lim.plan_name,
        status=lim.status,
        usage=use,
        limits={f: getattr(lim, f) for f in subscriptions.LIMIT_FIELDS},
    )
