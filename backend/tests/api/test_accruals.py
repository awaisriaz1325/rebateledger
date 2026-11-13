"""Month-end accrual journal (v1.1 Phase 15). Hand-worked values, reversing method (ADR 0017).

Fixture (tests.api.test_workflow.world_setup): ACME, 2% flat quarterly from 2025-01-01.
Purchases: 60,000 on 15 Jan + 40,000 on 20 Mar (Q1 = 100,000 → 2,000.00 earned) and 50,000 on
10 Apr (Q2). A run covers Q1–Q2 2025. A 1,500.00 credit for Q1 is dated 20 Apr 2025.

Closing 31 May 2025:
- Q1 (closed): earned 2,000.00 − received 1,500.00 = 500.00
- Q2 (open; 1 Apr – 31 May): earned to date 50,000 × 2% = 1,000.00 (estimate), received 0
- Total outstanding 1,500.00; reversal dated 1 Jun 2025.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.services import accruals
from tests.api.conftest import login, step_up
from tests.api.test_workflow import (
    CREDIT_COLS,
    imp,
    run,
    world_setup,  # noqa: F401 - shared pytest fixture
)


@pytest.fixture
def booked(world_setup: Any) -> Any:  # noqa: F811 - the fixture imported above
    c, w, t, _sid, _aid = world_setup
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-1,04/20/2025,1500.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)
    owner = w.member(t, "owner")
    login(c, owner)
    org = c.get("/api/v1/org")
    r = c.patch(
        "/api/v1/org/settings/accounting",
        json={
            "gl_receivable_account": "1250 Rebates receivable",
            "gl_offset_account": "5010 COGS - vendor rebates",
        },
        headers={"If-Match": org.headers["ETag"]},
    )
    assert r.status_code == 200, r.text
    return c, w, t, owner


def _export(c: Any, closing: str = "2025-05-31", fmt: str = "generic") -> Any:
    return c.post(
        "/api/v1/accruals/journal/export",
        json={"closing_date": closing, "format": fmt, "reviewed": True},
    )


def test_preview_books_outstanding_receivable_per_period(booked: Any) -> None:
    c, *_ = booked
    j = c.get("/api/v1/accruals/journal", params={"closing_date": "2025-05-31"}).json()
    assert j["reversal_date"] == "2025-06-01"
    assert j["accounts_configured"] is True
    assert [
        (ln["period_start"], ln["basis"], ln["earned"], ln["received"], ln["outstanding"])
        for ln in j["lines"]
    ] == [
        ("2025-01-01", "closed", "2000.00", "1500.00", "500.00"),
        ("2025-04-01", "open_estimate", "1000.00", "0.00", "1000.00"),
    ]
    assert j["total"] == "1500.00"
    assert j["excluded"] == [] and j["not_calculated"] == []
    assert j["last_export"] is None


def test_credit_dated_after_closing_is_not_yet_received(booked: Any) -> None:
    c, *_ = booked
    j = c.get("/api/v1/accruals/journal", params={"closing_date": "2025-03-31"}).json()
    assert [(ln["period_start"], ln["outstanding"]) for ln in j["lines"]] == [
        ("2025-01-01", "2000.00")
    ]


def test_export_is_a_balanced_reversing_journal(booked: Any) -> None:
    c, _w, _t, owner = booked
    step_up(c, owner)
    r = _export(c)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 8  # 2 lines × (Dr + Cr) × (accrual + reversal)
    first = rows[0]
    assert (first["Journal"], first["Date"], first["Account"], first["Debit"], first["Credit"]) == (
        "ACC-202505",
        "2025-05-31",
        "1250 Rebates receivable",
        "500.00",
        "",
    )
    assert rows[1]["Account"] == "5010 COGS - vendor rebates" and rows[1]["Credit"] == "500.00"
    assert "(estimate to date)" in rows[2]["Description"]
    rev = [x for x in rows if x["Journal"] == "ACC-202505-R"]
    assert {x["Date"] for x in rev} == {"2025-06-01"}
    assert rev[0]["Account"] == "5010 COGS - vendor rebates" and rev[0]["Debit"] == "500.00"
    for jno in ("ACC-202505", "ACC-202505-R"):
        part = [x for x in rows if x["Journal"] == jno]
        debit = sum(Decimal(x["Debit"] or "0") for x in part)
        credit = sum(Decimal(x["Credit"] or "0") for x in part)
        assert debit == credit == Decimal("1500.00")

    hist = c.get("/api/v1/accruals/exports").json()
    assert len(hist) == 1 and hist[0]["total"] == "1500.00" and hist[0]["line_count"] == 2
    assert hist[0]["id"] == r.headers["X-Export-Id"]


def test_reexport_shows_what_changed(booked: Any) -> None:
    c, _w, _t, owner = booked
    step_up(c, owner)
    assert _export(c).status_code == 200
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-2,05/15/2025,200.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)  # credits are matched to periods by a run
    j = c.get("/api/v1/accruals/journal", params={"closing_date": "2025-05-31"}).json()
    assert j["last_export"]["total"] == "1500.00"
    assert j["changes_since_last_export"] == [
        {
            "agreement": "Acme base",
            "supplier": "Acme",
            "period_start": "2025-01-01",
            "before": "500.00",
            "after": "300.00",
        }
    ]


def test_qbo_format_uses_us_dates(booked: Any) -> None:
    c, _w, _t, owner = booked
    step_up(c, owner)
    r = _export(c, fmt="qbo")
    assert r.status_code == 200, r.text
    header, first = r.text.splitlines()[:2]
    assert header == "JournalNo,JournalDate,AccountName,Debits,Credits,Description,Name"
    assert first.startswith("ACC-202505,05/31/2025,1250 Rebates receivable,500.00,,")


def test_guards(booked: Any) -> None:
    c, w, t, owner = booked
    step_up(c, owner)
    r = c.get("/api/v1/accruals/journal", params={"closing_date": "2025-05-30"})
    assert r.status_code == 422 and r.json()["code"] == "CLOSING_DATE_NOT_MONTH_END"
    r = c.post(
        "/api/v1/accruals/journal/export",
        json={"closing_date": "2025-05-31", "format": "generic", "reviewed": False},
    )
    assert r.status_code == 422  # sign-off is required
    assert _export(c, closing="2024-12-31").json()["code"] == "NOTHING_TO_ACCRUE"
    login(c, w.member(t, "analyst"))
    assert (
        c.get("/api/v1/accruals/journal", params={"closing_date": "2025-05-31"}).status_code == 200
    )
    assert _export(c).status_code == 403  # analysts preview; owners and admins sign off


def test_export_refused_until_gl_accounts_are_set(world_setup: Any) -> None:  # noqa: F811
    c, w, t, _sid, _aid = world_setup
    run(c)
    owner = w.member(t, "owner")
    login(c, owner)
    step_up(c, owner)
    r = _export(c)
    assert r.status_code == 422 and r.json()["code"] == "GL_ACCOUNTS_MISSING"


def test_overpaid_period_swaps_debit_and_credit() -> None:
    line = accruals.AccrualLine(
        uuid.uuid4(),
        "Deal",
        "Supplier",
        date(2025, 1, 1),
        date(2025, 3, 31),
        "2025-Q1",
        "closed",
        Decimal("2000.00"),
        Decimal("2500.00"),
    )
    journal = accruals.Journal(date(2025, 5, 31), date(2025, 6, 1), [line])
    rows = list(csv.DictReader(io.StringIO(accruals.render(journal, "generic", "AR", "COGS"))))
    assert [(x["Journal"], x["Account"], x["Debit"], x["Credit"]) for x in rows] == [
        ("ACC-202505", "COGS", "500.00", ""),
        ("ACC-202505", "AR", "", "500.00"),
        ("ACC-202505-R", "AR", "500.00", ""),
        ("ACC-202505-R", "COGS", "", "500.00"),
    ]


def test_closed_period_without_a_run_is_listed_not_guessed(booked: Any) -> None:
    c, *_ = booked
    # The run covered Q1–Q2 only. At 30 Sep, Q3 is closed but was never calculated.
    j = c.get("/api/v1/accruals/journal", params={"closing_date": "2025-09-30"}).json()
    assert [(ln["period_start"], ln["basis"], ln["outstanding"]) for ln in j["lines"]] == [
        ("2025-01-01", "closed", "500.00"),
        ("2025-04-01", "closed", "1000.00"),
    ]
    assert [(x["period_start"], x["reason"]) for x in j["not_calculated"]] == [
        ("2025-07-01", "No calculation run yet")
    ]
