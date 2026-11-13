"""SPA matcher (v1.1 Phase 17): hand-worked cases and properties."""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.engine.spa import Sale, SpaItemTerms, SpaStatus, SpaTerms, match

D = Decimal
SPA_A = SpaTerms(
    spa_id="SPA-1",
    supplier_id="S1",
    valid_from=date(2026, 1, 1),
    valid_to=date(2026, 6, 30),
    claim_deadline_days=60,
    items={
        "WIRE": SpaItemTerms(book_cost=D("10.00"), spa_cost=D("7.50")),
        "BOX": SpaItemTerms(book_cost=D("40.00"), spa_cost=D("31.25"), quantity_cap=D("100")),
    },
    customer="Hospital Build LLC",
)


def sale(i: int, sku: str = "WIRE", qty: str = "10", **kw: object) -> Sale:
    base: dict[str, object] = {
        "line_id": f"L{i:03d}",
        "supplier_id": "S1",
        "invoice_date": date(2026, 2, 1) + timedelta(days=i),
        "sku": sku,
        "quantity": D(qty),
        "customer": "hospital  build llc",
    }
    base.update(kw)
    return Sale(**base)  # type: ignore[arg-type]


def test_basic_claim_book_minus_spa_cost_times_quantity() -> None:
    # (10.00 − 7.50) × 10 = 25.00 ; deadline = 2 Feb 2026 + 60 days = 3 Apr 2026
    [r] = match([SPA_A], [sale(1)])
    assert (r.status, r.spa_id, r.claimable_quantity, r.claimable_amount) == (
        SpaStatus.OK,
        "SPA-1",
        D("10"),
        D("25.00"),
    )
    assert r.unit_difference == D("2.50") and r.deadline == date(2026, 4, 3)


def test_rounding_half_up_per_line() -> None:
    # (40.00 − 31.25) × 0.333 = 2.91375 → 2.91
    [r] = match([SPA_A], [sale(1, "BOX", "0.333")])
    assert r.claimable_amount == D("2.91")


def test_not_a_spa_sale_gives_no_result() -> None:
    assert match([SPA_A], [sale(1, "OTHER")]) == []
    assert match([SPA_A], [sale(1, supplier_id="S2")]) == []
    assert match([SPA_A], [sale(1, invoice_date=date(2026, 7, 1))]) == []
    assert match([SPA_A], [sale(1, customer="Someone Else")]) == []


def test_missing_customer_is_review_not_a_guess() -> None:
    [r] = match([SPA_A], [sale(1, customer=None)])
    assert r.status is SpaStatus.NEEDS_REVIEW and [x.code for x in r.reasons] == [
        "CUSTOMER_MISSING"
    ]
    assert r.claimable_amount == 0


def test_missing_job_is_review() -> None:
    spa = SpaTerms(
        "SPA-J",
        "S1",
        date(2026, 1, 1),
        date(2026, 12, 31),
        30,
        {"WIRE": SpaItemTerms(D("10"), D("9"))},
        job="Tower A",
    )
    [r] = match([spa], [sale(1, job=None)])
    assert [x.code for x in r.reasons] == ["JOB_MISSING"]
    [ok] = match([spa], [sale(1, job=" tower a ")])
    assert ok.status is SpaStatus.OK and ok.claimable_amount == D("10.00")


def test_two_covering_spas_need_review() -> None:
    open_spa = SpaTerms(
        "SPA-2",
        "S1",
        date(2026, 1, 1),
        date(2026, 12, 31),
        90,
        {"WIRE": SpaItemTerms(D("10.00"), D("8.00"))},
    )
    [r] = match([SPA_A, open_spa], [sale(1)])
    assert r.status is SpaStatus.NEEDS_REVIEW and r.spa_id is None
    assert [x.code for x in r.reasons] == ["MULTIPLE_SPAS"] and "SPA-1, SPA-2" in r.reasons[
        0
    ].message


def test_spa_cost_not_below_book_needs_review() -> None:
    bad = SpaTerms(
        "SPA-3",
        "S1",
        date(2026, 1, 1),
        date(2026, 12, 31),
        30,
        {"WIRE": SpaItemTerms(D("10.00"), D("10.00"))},
    )
    [r] = match([bad], [sale(1, customer=None)])
    assert [x.code for x in r.reasons] == ["SPA_COST_NOT_BELOW_BOOK"] and r.claimable_amount == 0


def test_return_is_review_with_negative_amount_and_keeps_cap() -> None:
    # Return of 5 BOX: (40.00 − 31.25) × −5 = −43.75 ; cap untouched, so 100 can still be claimed.
    rows = match([SPA_A], [sale(1, "BOX", "-5"), sale(2, "BOX", "100")])
    ret, full = rows
    assert (ret.status, ret.claimable_amount, [x.code for x in ret.reasons]) == (
        SpaStatus.NEEDS_REVIEW,
        D("-43.75"),
        ["RETURN"],
    )
    assert (full.status, full.claimable_quantity) == (SpaStatus.OK, D("100"))


def test_cap_consumed_in_date_order_with_partial_line() -> None:
    # Cap 100 BOX. L001 60 → 60 ; L002 60 → 40 (partial) ; L003 10 → 0 (cap reached).
    rows = match([SPA_A], [sale(3, "BOX", "10"), sale(1, "BOX", "60"), sale(2, "BOX", "60")])
    assert [(r.line_id, r.status, r.claimable_quantity, r.claimable_amount) for r in rows] == [
        ("L001", SpaStatus.OK, D("60"), D("525.00")),
        ("L002", SpaStatus.OK, D("40"), D("350.00")),
        ("L003", SpaStatus.NOT_CLAIMABLE, D("0"), D("0")),
    ]
    assert [x.code for x in rows[1].reasons] == ["CAP_PARTIAL"]
    assert [x.code for x in rows[2].reasons] == ["CAP_REACHED"]


def test_cap_counts_quantity_already_in_claims() -> None:
    [r] = match([SPA_A], [sale(1, "BOX", "30")], {("SPA-1", "BOX"): D("80")})
    assert r.claimable_quantity == D("20")


def test_cost_mismatch_is_review_but_amount_uses_book_cost() -> None:
    [r] = match([SPA_A], [sale(1, unit_cost=D("9.80"))])
    assert r.status is SpaStatus.NEEDS_REVIEW and [x.code for x in r.reasons] == ["COST_MISMATCH"]
    assert r.claimable_amount == D("25.00")
    [same] = match([SPA_A], [sale(1, unit_cost=D("10.0000"))])
    assert same.status is SpaStatus.OK


SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@st.composite
def box_sales(draw: st.DrawFn) -> list[Sale]:
    n = draw(st.integers(min_value=0, max_value=30))
    return [
        sale(
            i,
            "BOX",
            str(
                draw(st.decimals(min_value=D("-20"), max_value=D("80"), places=2, allow_nan=False))
            ),
        )
        for i in range(n)
    ]


@SETTINGS
@given(box_sales(), st.randoms(use_true_random=False))
def test_order_independent(sales: list[Sale], rnd: random.Random) -> None:
    shuffled = list(sales)
    rnd.shuffle(shuffled)
    assert match([SPA_A], sales) == match([SPA_A], shuffled)


@SETTINGS
@given(box_sales(), st.decimals(min_value=D("0"), max_value=D("150"), places=2, allow_nan=False))
def test_cap_never_exceeded(sales: list[Sale], already: Decimal) -> None:
    rows = match([SPA_A], sales, {("SPA-1", "BOX"): already})
    claimed = sum((r.claimable_quantity for r in rows if r.claimable_quantity > 0), D("0"))
    assert claimed <= max(D("100") - already, D("0"))
    for r in rows:
        if r.status is SpaStatus.OK:
            assert r.claimable_amount == (D("8.75") * r.claimable_quantity).quantize(
                D("0.01"), rounding=ROUND_HALF_UP
            )
