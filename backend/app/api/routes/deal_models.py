"""Deal modelling (v1.1 Phase 13): read-only what-if of proposed terms on past purchases."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import Field

from app.api.deps import Ctx, Requires
from app.api.schemas.common import DecimalStr, In, Out
from app.api.schemas.views import ReasonOut
from app.core.permissions import Permission
from app.services import deal_models as svc
from app.services.agreement_terms import VersionTermsIn

router = APIRouter(prefix="/api/v1", tags=["deal-models"])
# Same permission as drafting terms (the live terms check). Read-only: nothing is written.
Model = Annotated[Ctx, Depends(Requires(Permission.EDIT_AGREEMENTS))]


class OptionIn(In):
    label: Annotated[str, Field(min_length=1, max_length=60)]
    terms: VersionTermsIn


class DealModelIn(In):
    supplier_id: uuid.UUID
    window_start: date
    window_end: date
    options: Annotated[list[OptionIn], Field(min_length=1, max_length=svc.MAX_OPTIONS)]


class ModelPeriodOut(Out):
    label: str
    start: date
    end: date
    expected: DecimalStr | None
    spend: DecimalStr
    measure: DecimalStr
    tier_reached: int | None
    statuses: list[str]
    reasons: list[ReasonOut]


class SensitivityOut(Out):
    factor: DecimalStr
    total_expected: DecimalStr
    complete: bool


class OptionOut(Out):
    label: str
    summary: str
    total_expected: DecimalStr
    total_spend: DecimalStr
    effective_rate: DecimalStr | None
    complete: bool
    periods: list[ModelPeriodOut]
    sensitivity: list[SensitivityOut]


class DealModelOut(Out):
    window_start: date
    window_end: date
    engine_version: str
    options: list[OptionOut]


@router.post("/deal-models/evaluate", response_model=DealModelOut)
def evaluate(body: DealModelIn, ctx: Model) -> DealModelOut:
    """Estimate what each option would have paid on the supplier's real past purchases.

    Nothing is saved. Results are estimates: the window's real purchases, the proposed rules.
    """
    results = svc.evaluate(
        ctx.db,
        ctx,
        supplier_id=body.supplier_id,
        start=body.window_start,
        end=body.window_end,
        options=[(o.label, o.terms) for o in body.options],
    )
    engine_version = results[0].periods[0].engine_version
    return DealModelOut(
        window_start=body.window_start,
        window_end=body.window_end,
        engine_version=engine_version,
        options=[
            OptionOut(
                label=r.label,
                summary=r.summary,
                total_expected=r.total_expected,
                total_spend=r.total_spend,
                effective_rate=r.effective_rate,
                complete=r.complete,
                periods=[
                    ModelPeriodOut(
                        label=p.period.label,
                        start=p.period.start,
                        end=p.period.end,
                        expected=p.expected,
                        spend=p.spend,
                        measure=p.measure,
                        tier_reached=p.tier_reached,
                        statuses=[s.value for s in p.statuses],
                        reasons=[ReasonOut(code=x.code, message=x.message) for x in p.reasons],
                    )
                    for p in r.periods
                ],
                sensitivity=[
                    SensitivityOut(factor=f, total_expected=t, complete=c)
                    for f, t, c in r.sensitivity
                ],
            )
            for r in results
        ],
    )
