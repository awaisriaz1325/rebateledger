"""Bulk agreement import (v1.2 Phase 21): drafts only, all-or-nothing, same rules as the editor.

Fixture (tests.api.test_workflow.world_setup): supplier Acme (code ACME) with active agreement
ACME-1 (2% flat quarterly); Q1 2025 purchases 100,000.

Hand-worked golden value for ACME-T (tiered all-units on spend, Q1 2025 = 100,000):
tiers 0 → 1%, 50,000 → 2%, 100,000 → 3%; ``gte`` so 100,000 reaches tier 3 →
100,000 × 3% = 3,000.00.
"""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from app.services.agreement_bulk import COLUMNS
from tests.api.conftest import login
from tests.api.factories import TERMS
from tests.api.test_workflow import world_setup  # noqa: F401 - shared pytest fixture

VERSION = {
    "effective_from": "2025-01-01",
    "effective_to": "",
    "period_type": "quarterly",
    "fiscal_aligned": "true",
    "date_basis": "invoice_date",
    "measure": "spend",
    "spend_basis": "net_of_returns",
    "threshold_comparison": "gte",
    "negative_result": "floor_at_zero",
    "rounding_mode": "half_up",
    "payment_terms_days": "30",
    "stacking": "stackable",
    "prorate_thresholds_on_partial_period": "false",
    "zero_baseline_policy": "needs_review",
}


def row(**cells: str) -> dict[str, str]:
    base = {
        "agreement_ref": "ACME-T",
        "agreement_name": "Acme tiers",
        "supplier": "ACME",
        **VERSION,
    }
    return {**base, **cells}


TIERED = [
    row(component_key="tiers", component_type="tiered_all_units", tier_threshold="0", tier_rate="1%"),
    row(component_key="tiers", component_type="tiered_all_units", tier_threshold="$50,000", tier_rate="0.02"),
    row(component_key="tiers", component_type="tiered_all_units", tier_threshold="100000.00", tier_rate="3%"),
]  # fmt: skip


def to_csv(rows: list[dict[str, str]], header: list[str] | None = None) -> bytes:
    names = header or [c.name for c in COLUMNS]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=names, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()


def preview(c: Any, data: bytes) -> dict[str, Any]:
    r = c.post("/api/v1/agreements/bulk/preview", files={"file": ("a.csv", data, "text/csv")})
    assert r.status_code == 200, r.text
    return dict(r.json())


def commit(c: Any, data: bytes, key: str | None = None) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    return c.post(
        "/api/v1/agreements/bulk", files={"file": ("a.csv", data, "text/csv")}, headers=headers
    )


def agreement_count(c: Any) -> int:
    return len(c.get("/api/v1/agreements").json()["items"])


def test_template_and_columns_match() -> None:
    from app.services.agreement_bulk import template

    assert template().strip().split(",") == [c.name for c in COLUMNS]


def test_columns_endpoint_lists_allowed_values(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    cols = {x["name"]: x for x in c.get("/api/v1/agreements/bulk/columns").json()}
    assert "custom" not in cols["period_type"]["allowed"]
    assert cols["component_type"]["required"] is True
    t = c.get("/api/v1/agreements/bulk/template")
    assert t.status_code == 200 and t.text.startswith("agreement_ref,agreement_name,supplier,")


def test_import_creates_a_draft_equal_to_the_editor(world_setup: Any) -> None:  # noqa: F811
    c, _w, _t, sid, _aid = world_setup
    plan = preview(c, to_csv(TIERED))
    assert plan["errors"] == []
    [item] = plan["items"]
    assert (item["action"], item["components"], item["tiers"], item["supplier_name"]) == (
        "create",
        1,
        3,
        "Acme",
    )
    before = agreement_count(c)
    r = commit(c, to_csv(TIERED))
    assert r.status_code == 201, r.text
    assert agreement_count(c) == before + 1
    aid = r.json()["items"][0]["agreement_id"]
    imported = c.get(f"/api/v1/agreements/{aid}").json()
    [v] = imported["versions"]
    assert v["status"] == "draft"  # never active straight from a file
    assert imported["external_reference"] == "ACME-T"

    # Same terms through the editor API.
    terms = {
        **TERMS,
        "effective_from": "2025-01-01",
        "components": [
            {
                "key": "tiers",
                "type": "tiered_all_units",
                "tiers": [
                    {"threshold": "0", "rate": "0.01"},
                    {"threshold": "50000", "rate": "0.02"},
                    {"threshold": "100000.00", "rate": "0.03"},
                ],
            }
        ],
    }
    e = c.post(
        "/api/v1/agreements", json={"supplier_id": sid, "name": "Editor tiers", "terms": terms}
    ).json()
    ev = e["versions"][0]
    assert v["terms"] == ev["terms"]
    # Same engine output: hand-worked 3,000.00 for Q1 2025.
    body = {"period_containing": "2025-02-01"}
    p1 = c.post(f"/api/v1/agreement-versions/{v['id']}/preview", json=body).json()
    p2 = c.post(f"/api/v1/agreement-versions/{ev['id']}/preview", json=body).json()
    assert p1["expected"] == p2["expected"] == "3000.00"
    assert p1["tier_reached"] == p2["tier_reached"] == 3


def test_reimport_is_idempotent_and_conflicting_draft_is_refused(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    assert commit(c, to_csv(TIERED)).status_code == 201
    count = agreement_count(c)
    plan = preview(c, to_csv(TIERED))
    assert plan["items"][0]["action"] == "unchanged" and plan["errors"] == []
    assert commit(c, to_csv(TIERED)).status_code == 201
    assert agreement_count(c) == count

    changed = [
        {**r, "tier_rate": "4%"} if r["tier_threshold"] == "100000.00" else r for r in TIERED
    ]
    plan = preview(c, to_csv(changed))
    assert [(e["row"], e["column"]) for e in plan["errors"]] == [(2, "agreement_ref")]
    assert "already has draft version 1" in plan["errors"][0]["message"]
    r = commit(c, to_csv(changed))
    assert r.status_code == 422 and r.json()["code"] == "BULK_INVALID"


def test_existing_active_agreement_gets_a_new_draft_version(world_setup: Any) -> None:  # noqa: F811
    c, _w, _t, _sid, aid = world_setup
    rows = [
        row(
            agreement_ref="acme-1",  # references match case-insensitively
            agreement_name="Acme base renamed",
            effective_from="2025-07-01",
            component_key="base",
            component_type="flat_percent",
            rate="2.5%",
        )
    ]
    plan = preview(c, to_csv(rows))
    assert plan["errors"] == []
    [item] = plan["items"]
    assert item["action"] == "new_version" and item["agreement_id"] == aid
    assert any("is kept" in w for w in item["warnings"])
    assert commit(c, to_csv(rows)).status_code == 201
    versions = c.get(f"/api/v1/agreements/{aid}").json()["versions"]
    assert [(v["version_no"], v["status"]) for v in versions] == [(1, "active"), (2, "draft")]
    assert versions[1]["terms"]["components"][0]["rate"] == "0.025"


def test_errors_are_reported_per_row_and_nothing_is_created(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    rows = [
        # 2: ambiguous rate
        row(agreement_ref="A", component_key="base", component_type="flat_percent", rate="2"),
        # 3: unknown supplier
        row(agreement_ref="B", supplier="NOPE", component_key="base", component_type="flat_percent", rate="1%"),
        # 4–5: version column differs between rows of one agreement
        row(agreement_ref="C", component_key="t", component_type="tiered_all_units", tier_threshold="0", tier_rate="1%"),
        row(agreement_ref="C", payment_terms_days="60", component_key="t", component_type="tiered_all_units", tier_threshold="10", tier_rate="2%"),
        # 6–7: a component mixing tier and non-tier rows
        row(agreement_ref="D", component_key="t", component_type="tiered_all_units", tier_threshold="0", tier_rate="1%"),
        row(agreement_ref="D", component_key="t", component_type="tiered_all_units"),
        # 8: custom periods are set in the editor
        row(agreement_ref="E", period_type="custom", component_key="base", component_type="flat_percent", rate="1%"),
        # 9: bad date
        row(agreement_ref="F", effective_from="31/01/2025", component_key="base", component_type="flat_percent", rate="1%"),
        # 10: engine rule (flat_percent needs a rate)
        row(agreement_ref="G", component_key="base", component_type="flat_percent"),
    ]  # fmt: skip
    plan = preview(c, to_csv(rows))
    found = {(e["row"], e["column"]) for e in plan["errors"]}
    assert {
        (2, "rate"),
        (3, "supplier"),
        (5, "payment_terms_days"),
        (6, "tier_threshold"),
        (8, "period_type"),
        (9, "effective_from"),
    } <= found
    assert any(e["row"] == 10 for e in plan["errors"])
    assert "write 0.02 or 2%" in next(e["message"] for e in plan["errors"] if e["row"] == 2)
    before = agreement_count(c)
    r = commit(c, to_csv(rows))
    assert r.status_code == 422 and r.json()["code"] == "BULK_INVALID"
    assert agreement_count(c) == before


def test_header_problems_are_reported(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    names = [c.name for c in COLUMNS if c.name != "measure"] + ["mesure"]
    plan = preview(
        c, to_csv([row(component_key="b", component_type="flat_percent", rate="1%")], names)
    )
    assert {(e["row"], e["column"]) for e in plan["errors"]} == {(1, "mesure"), (1, "measure")}
    plan = preview(c, to_csv([]))
    assert plan["errors"][0]["message"] == "The file has no data rows."


def test_other_tenants_suppliers_are_invisible(world_setup: Any) -> None:  # noqa: F811
    c, w, _t, _sid, _aid = world_setup
    other = w.tenant()
    login(c, w.member(other, "analyst"))
    assert c.post("/api/v1/suppliers", json={"name": "Hidden", "codes": ["HID"]}).status_code == 201
    login(c, w.member(_t, "analyst"))
    rows = [row(supplier="HID", component_key="b", component_type="flat_percent", rate="1%")]
    plan = preview(c, to_csv(rows))
    assert [(e["row"], e["column"]) for e in plan["errors"]] == [(2, "supplier")]


def test_idempotency_key_replays_the_first_response(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    key = str(uuid.uuid4())
    first = commit(c, to_csv(TIERED), key)
    count = agreement_count(c)
    again = commit(c, to_csv(TIERED), key)
    assert again.status_code == 201 and again.json() == first.json()
    assert agreement_count(c) == count


def test_formula_like_text_is_stored_as_typed(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    rows = [
        row(
            agreement_name='=HYPERLINK("x")',
            component_key="b",
            component_type="flat_percent",
            rate="1%",
        )
    ]
    r = commit(c, to_csv(rows))
    assert r.status_code == 201, r.text
    aid = r.json()["items"][0]["agreement_id"]
    assert c.get(f"/api/v1/agreements/{aid}").json()["name"] == '=HYPERLINK("x")'


def test_file_guards(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup

    def code(data: bytes) -> str:
        r = c.post("/api/v1/agreements/bulk/preview", files={"file": ("a.csv", data, "text/csv")})
        assert r.status_code == 422, r.text
        return str(r.json()["code"])

    assert code(b"x" * (1024 * 1024 + 1)) == "FILE_TOO_LARGE"
    assert code("agreement_ref\nCaf\xe9\n".encode("latin-1")) == "FILE_ENCODING"
    many = "agreement_ref\n" + "A\n" * 2001
    assert code(many.encode()) == "TOO_MANY_ROWS"
