"""Supplier statement compare (v1.2 Phase 22). Hand-worked values.

Fixture (tests.api.test_workflow.world_setup): ACME-1, 2% flat quarterly from 2025-01-01;
purchases Q1 = 100,000 (→ 2,000.00), Q2 = 50,000 (→ 1,000.00). Tenant tolerance 1.00 / 0.5%,
so the tolerance on 2,000.00 is max(1.00, 10.00) = 10.00.

Statement lines (difference = ours − theirs):
- S1 Q1 ACME-1, theirs 2,000.00 on 100,000           → agrees, 0.00
- S2 Q2 ACME-1, theirs   800.00 on  40,000           → purchases_differ, 200.00
- S3 Q1 ACME-1, theirs 1,500.00 on 100,000           → rate_or_tier_differs, 500.00
- S4 Q1 no reference, theirs 1,990.00                → unconfirmed (ACME's only agreement)
                                                       → after confirming: agrees, 10.00 (= tolerance)
- S5 Q1 reference NOPE                               → unmatched (warning, not an error)
- S6 Feb 2025 ACME-1                                 → not_calculated (no such period)
"""

from __future__ import annotations

import io
import uuid
import zipfile
from decimal import Decimal
from typing import Any

from tests.api.conftest import login
from tests.api.test_exports import _download
from tests.api.test_workflow import (
    imp,
    run,
    world_setup,  # noqa: F401 - shared pytest fixture
)

COLS = {
    "supplier_code": "Vendor",
    "agreement_reference": "Program",
    "period_start": "From",
    "period_end": "To",
    "supplier_measure": "Purchases",
    "supplier_rebate": "Rebate",
    "statement_reference": "Statement",
}
CSV = (
    "Vendor,Program,From,To,Purchases,Rebate,Statement\n"
    "ACME,ACME-1,01/01/2025,03/31/2025,100000.00,2000.00,S1\n"
    "ACME,ACME-1,04/01/2025,06/30/2025,40000.00,800.00,S2\n"
    "ACME,ACME-1,01/01/2025,03/31/2025,100000.00,1500.00,S3\n"
    "ACME,,01/01/2025,03/31/2025,,1990.00,S4\n"
    "ACME,NOPE,01/01/2025,03/31/2025,,2000.00,S5\n"
    "ACME,ACME-1,02/01/2025,02/28/2025,,700.00,S6\n"
)


def _rows(c: Any, **params: str) -> dict[str, dict[str, Any]]:
    r = c.get("/api/v1/statements", params=params)
    assert r.status_code == 200, r.text
    return {x["statement_reference"]: x for x in r.json()}


def _setup(c: Any) -> dict[str, dict[str, Any]]:
    run(c)
    imp(c, "statements", CSV, COLS)
    return _rows(c)


def test_each_line_gets_the_hand_worked_status(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    rows = _setup(c)
    got = {k: (v["status"], v["ours"], v["theirs"], v["difference"]) for k, v in rows.items()}
    assert got == {
        "S1": ("agrees", "2000.00", "2000.00", "0.00"),
        "S2": ("purchases_differ", "1000.00", "800.00", "200.00"),
        "S3": ("rate_or_tier_differs", "2000.00", "1500.00", "500.00"),
        "S4": ("unconfirmed", None, "1990.00", None),
        "S5": ("unmatched", None, "2000.00", None),
        "S6": ("not_calculated", None, "700.00", None),
    }
    assert rows["S2"]["our_measure"] == "50000.00" and rows["S2"]["their_measure"] == "40000.00"
    assert rows["S4"]["match_status"] == "suggested"
    assert len(rows["S1"]["result_ids"]) == 1
    only = c.get("/api/v1/statements", params={"status": "purchases_differ"}).json()
    assert [x["statement_reference"] for x in only] == ["S2"]


def test_reimporting_the_same_statement_adds_nothing(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    _setup(c)
    imp(c, "statements", CSV + "\n", COLS)  # a byte-different copy: rows dedupe, not the file
    assert len(c.get("/api/v1/statements").json()) == 6


def test_confirm_choose_and_clear_the_agreement(world_setup: Any) -> None:  # noqa: F811
    c, _w, _t, sid, aid = world_setup
    rows = _setup(c)
    r = c.put(f"/api/v1/statements/{rows['S4']['id']}/agreement", json={"agreement_id": aid})
    assert r.status_code == 200, r.text
    s4 = r.json()
    assert (s4["match_status"], s4["status"], s4["difference"]) == ("confirmed", "agrees", "10.00")

    r = c.put(f"/api/v1/statements/{rows['S5']['id']}/agreement", json={"agreement_id": aid})
    assert r.json()["status"] == "agrees"  # S5 theirs 2,000.00 once assigned
    r = c.put(f"/api/v1/statements/{rows['S5']['id']}/agreement", json={"agreement_id": None})
    assert (r.json()["match_status"], r.json()["status"]) == ("unmatched", "unmatched")

    # Another supplier's agreement cannot be chosen.
    other_sid = c.post("/api/v1/suppliers", json={"name": "Beta", "codes": ["BETA"]}).json()["id"]
    from tests.api.factories import TERMS

    other = c.post(
        "/api/v1/agreements", json={"supplier_id": other_sid, "name": "Beta base", "terms": TERMS}
    ).json()
    r = c.put(
        f"/api/v1/statements/{rows['S4']['id']}/agreement", json={"agreement_id": other["id"]}
    )
    assert r.status_code == 422 and r.json()["code"] == "AGREEMENT_SUPPLIER_MISMATCH"
    assert sid != other_sid


def test_export_is_formula_safe(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    run(c)
    imp(
        c,
        "statements",
        "Vendor,Program,From,To,Purchases,Rebate,Statement\n"
        'ACME,ACME-1,01/01/2025,03/31/2025,,1500.00,"=HYPERLINK(""x"")"\n',
        COLS,
    )
    r = c.get("/api/v1/statements/export")
    assert r.status_code == 200
    lines = r.text.splitlines()
    assert lines[0].startswith("Supplier,Agreement,Statement reference,")
    assert "'=HYPERLINK" in lines[1]
    assert ",1500.00,2000.00,500.00," in lines[1]


def test_viewer_cannot_assign_and_other_tenants_lines_are_invisible(world_setup: Any) -> None:  # noqa: F811
    c, w, t, _sid, aid = world_setup
    rows = _setup(c)
    login(c, w.member(t, "viewer"))
    r = c.put(f"/api/v1/statements/{rows['S4']['id']}/agreement", json={"agreement_id": aid})
    assert r.status_code == 403
    other = w.tenant()
    login(c, w.member(other, "owner"))
    assert c.get("/api/v1/statements").json() == []
    r = c.put(f"/api/v1/statements/{rows['S4']['id']}/agreement", json={"agreement_id": None})
    assert r.status_code == 404


def test_evidence_pack_includes_the_statement(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    rows = _setup(c)
    q1 = next(
        r for r in c.get("/api/v1/reconciliation").json() if r["period_start"] == "2025-01-01"
    )
    claim = c.post("/api/v1/claims", json={"result_ids": [q1["result_id"]]}).json()
    r = c.post(
        f"/api/v1/claims/{claim['id']}/evidence-pack",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 202, r.text
    z = zipfile.ZipFile(io.BytesIO(_download(c, r.json())))
    text = z.read("supplier-statement.csv").decode("utf-8-sig")
    # Only matched/confirmed Q1 lines: S1 and S3 (S4 is unconfirmed, S5 unmatched).
    body = text.splitlines()[1:]
    assert len(body) == 2 and all(",2000.00," in ln for ln in body)
    assert sum(Decimal(ln.split(",")[9]) for ln in body) == Decimal("500.00")
    assert rows["S1"]["result_ids"] == [q1["result_id"]]
