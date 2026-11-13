"""Ship-and-debit / SPA claim matcher (v1.1 Phase 17, ADR 0017 §4). Pure and deterministic.

For each sale line, find the special pricing agreement (SPA) that covers it and the amount
the supplier owes back:

    claimable = (book cost on the SPA − SPA net cost) × quantity      (rounded half-up to cents)

Rules (never guessed — anything ambiguous is NEEDS_REVIEW with a reason code):

1. A SPA covers a line when the supplier matches, the SKU is one of its items, the invoice
   date is inside the SPA's validity, and the SPA's customer / job (when set) equal the line's
   (compared case- and space-insensitively).
2. No SPA covers the line → no result (not a SPA sale). If a SPA would cover it except that
   the line has no customer or job → NEEDS_REVIEW ``CUSTOMER_MISSING`` / ``JOB_MISSING``.
3. More than one SPA covers it → NEEDS_REVIEW ``MULTIPLE_SPAS`` (amount 0).
4. SPA cost not below book cost → NEEDS_REVIEW ``SPA_COST_NOT_BELOW_BOOK`` (amount 0).
5. A return (negative quantity) → NEEDS_REVIEW ``RETURN`` with the negative amount it would
   reverse; it does not change the cap.
6. Quantity caps are consumed in (invoice date, line id) order, after quantities already in
   claims. Over the cap: the rest of the line is not claimable (``CAP_REACHED``); a line that
   crosses the cap is claimable for the remainder (info ``CAP_PARTIAL``).
7. The line's cost differs from the SPA book cost → NEEDS_REVIEW ``COST_MISMATCH``; the
   amount is still computed from the book cost and is not changed.

Claim deadline = invoice date + the SPA's claim deadline days.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum

from app.engine.version import ENGINE_VERSION

CENT = Decimal("0.01")
ZERO = Decimal("0")


class SpaStatus(StrEnum):
    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    NOT_CLAIMABLE = "not_claimable"


@dataclass(frozen=True, slots=True)
class SpaItemTerms:
    book_cost: Decimal
    spa_cost: Decimal
    quantity_cap: Decimal | None = None


@dataclass(frozen=True, slots=True)
class SpaTerms:
    spa_id: str
    supplier_id: str
    valid_from: date
    valid_to: date
    claim_deadline_days: int
    items: Mapping[str, SpaItemTerms]
    customer: str | None = None
    job: str | None = None


@dataclass(frozen=True, slots=True)
class Sale:
    line_id: str
    supplier_id: str
    invoice_date: date
    sku: str
    quantity: Decimal
    customer: str | None = None
    job: str | None = None
    unit_cost: Decimal | None = None


@dataclass(frozen=True, slots=True)
class SpaReason:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SpaResult:
    line_id: str
    supplier_id: str
    spa_id: str | None
    status: SpaStatus
    claimable_quantity: Decimal
    claimable_amount: Decimal
    unit_difference: Decimal | None
    deadline: date | None
    reasons: tuple[SpaReason, ...] = ()
    engine_version: str = field(default=ENGINE_VERSION)


def _norm(text: str | None) -> str | None:
    if text is None:
        return None
    t = " ".join(text.split()).casefold()
    return t or None


def _covers(spa: SpaTerms, s: Sale, *, ignore_party: bool = False) -> bool:
    if spa.supplier_id != s.supplier_id or s.sku not in spa.items:
        return False
    if not spa.valid_from <= s.invoice_date <= spa.valid_to:
        return False
    if ignore_party:
        return True
    if spa.customer is not None and _norm(spa.customer) != _norm(s.customer):
        return False
    return not (spa.job is not None and _norm(spa.job) != _norm(s.job))


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def match(
    spas: Sequence[SpaTerms],
    sales: Sequence[Sale],
    already_claimed: Mapping[tuple[str, str], Decimal] | None = None,
) -> list[SpaResult]:
    """Results for every sale line a SPA covers (or almost covers). Order-independent input.

    ``already_claimed``: quantity per (spa id, sku) already in claims, counted against caps.
    """
    used: dict[tuple[str, str], Decimal] = dict(already_claimed or {})
    by_sku: dict[str, list[SpaTerms]] = {}
    for p in spas:  # index only; every candidate is still checked with _covers
        for sku in p.items:
            by_sku.setdefault(sku, []).append(p)
    out: list[SpaResult] = []
    with localcontext() as ctx:
        ctx.prec = 34
        for s in sorted(sales, key=lambda x: (x.invoice_date, x.line_id)):
            pool = by_sku.get(s.sku, [])
            cands = [p for p in pool if _covers(p, s)]
            if not cands:
                near = [p for p in pool if _covers(p, s, ignore_party=True)]
                missing = []
                if any(p.customer is not None for p in near) and _norm(s.customer) is None:
                    missing.append(
                        SpaReason(
                            "CUSTOMER_MISSING", "A SPA needs a customer, but this sale has none."
                        )
                    )
                if any(p.job is not None for p in near) and _norm(s.job) is None:
                    missing.append(
                        SpaReason("JOB_MISSING", "A SPA needs a job, but this sale has none.")
                    )
                if missing:
                    out.append(
                        SpaResult(
                            s.line_id,
                            s.supplier_id,
                            None,
                            SpaStatus.NEEDS_REVIEW,
                            ZERO,
                            ZERO,
                            None,
                            None,
                            tuple(missing),
                        )
                    )
                continue
            if len(cands) > 1:
                ids = ", ".join(sorted(p.spa_id for p in cands))
                out.append(
                    SpaResult(
                        s.line_id,
                        s.supplier_id,
                        None,
                        SpaStatus.NEEDS_REVIEW,
                        ZERO,
                        ZERO,
                        None,
                        None,
                        (
                            SpaReason(
                                "MULTIPLE_SPAS",
                                f"More than one SPA covers this sale ({ids}); choose one.",
                            ),
                        ),
                    )
                )
                continue
            spa = cands[0]
            item = spa.items[s.sku]
            diff = item.book_cost - item.spa_cost
            deadline = s.invoice_date + timedelta(days=spa.claim_deadline_days)
            if diff <= 0:
                out.append(
                    SpaResult(
                        s.line_id,
                        s.supplier_id,
                        spa.spa_id,
                        SpaStatus.NEEDS_REVIEW,
                        ZERO,
                        ZERO,
                        diff,
                        deadline,
                        (
                            SpaReason(
                                "SPA_COST_NOT_BELOW_BOOK",
                                f"SPA cost {item.spa_cost} is not below book cost {item.book_cost}.",
                            ),
                        ),
                    )
                )
                continue
            if s.quantity < 0:
                out.append(
                    SpaResult(
                        s.line_id,
                        s.supplier_id,
                        spa.spa_id,
                        SpaStatus.NEEDS_REVIEW,
                        s.quantity,
                        _money(diff * s.quantity),
                        diff,
                        deadline,
                        (
                            SpaReason(
                                "RETURN",
                                "Return of a SPA sale: check whether the supplier will debit it back.",
                            ),
                        ),
                    )
                )
                continue
            reasons: list[SpaReason] = []
            qty = s.quantity
            key = (spa.spa_id, s.sku)
            if item.quantity_cap is not None:
                remaining = item.quantity_cap - used.get(key, ZERO)
                if remaining <= 0:
                    out.append(
                        SpaResult(
                            s.line_id,
                            s.supplier_id,
                            spa.spa_id,
                            SpaStatus.NOT_CLAIMABLE,
                            ZERO,
                            ZERO,
                            diff,
                            deadline,
                            (
                                SpaReason(
                                    "CAP_REACHED",
                                    f"The SPA quantity cap of {item.quantity_cap} is used up.",
                                ),
                            ),
                        )
                    )
                    continue
                if qty > remaining:
                    reasons.append(
                        SpaReason(
                            "CAP_PARTIAL",
                            f"Only {remaining} of {qty} units fit under the cap of {item.quantity_cap}.",
                        )
                    )
                    qty = remaining
                used[key] = used.get(key, ZERO) + qty
            status = SpaStatus.OK
            if s.unit_cost is not None and s.unit_cost != item.book_cost:
                status = SpaStatus.NEEDS_REVIEW
                reasons.append(
                    SpaReason(
                        "COST_MISMATCH",
                        f"Cost on the sale ({s.unit_cost}) differs from the SPA book cost ({item.book_cost}); amount uses the book cost.",
                    )
                )
            out.append(
                SpaResult(
                    s.line_id,
                    s.supplier_id,
                    spa.spa_id,
                    status,
                    qty,
                    _money(diff * qty),
                    diff,
                    deadline,
                    tuple(reasons),
                )
            )
    return out
