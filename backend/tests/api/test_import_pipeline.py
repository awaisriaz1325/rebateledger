"""Import pipeline end to end through the API (SPEC §4.5, §9 cases 17–29)."""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import World, login

FIX = Path(__file__).resolve().parents[1] / "imports" / "fixtures"
COLUMNS = {
    "supplier_code": "Vendor",
    "invoice_number": "Invoice",
    "line_number": "Line",
    "sku": "Item",
    "quantity": "Qty",
    "amount": "Ext",
    "invoice_date": "Inv Date",
    "currency": "Currency",
}
US = {"columns": COLUMNS, "date_format": "MM/DD/YYYY"}


@pytest.fixture
def org(app_client: TestClient, world: World) -> tuple[TestClient, World, uuid.UUID, str]:
    t = world.tenant()
    login(app_client, world.member(t, "analyst"))
    r = app_client.post("/api/v1/suppliers", json={"name": "Acme Electric", "codes": ["acme"]})
    assert r.status_code == 201, r.text
    return app_client, world, t, r.json()["id"]


def upload(
    c: TestClient,
    name: str,
    data: bytes | None = None,
    itype: str = "purchases",
    confirm: bool = False,
) -> Any:
    content = data if data is not None else (FIX / name).read_bytes()
    return c.post(
        "/api/v1/imports",
        files={"file": (name, content, "application/octet-stream")},
        data={"import_type": itype, "confirm_duplicate": str(confirm).lower()},
    )


def configure(c: TestClient, bid: str, cfg: dict[str, Any]) -> dict[str, Any]:
    r = c.put(f"/api/v1/imports/{bid}/config", json=cfg)
    assert r.status_code == 200, r.text
    return dict(r.json())


def validate(c: TestClient, bid: str) -> dict[str, Any]:
    r = c.post(f"/api/v1/imports/{bid}/validate")
    assert r.status_code == 202, r.text
    assert r.headers["Location"] == f"/api/v1/jobs/{r.json()['job_id']}"
    return dict(c.get(f"/api/v1/imports/{bid}").json())


def commit(c: TestClient, bid: str, mode: str = "all_or_nothing") -> dict[str, Any]:
    r = c.post(
        f"/api/v1/imports/{bid}/commit",
        json={"mode": mode},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 202, r.text
    job = c.get(f"/api/v1/jobs/{r.json()['job_id']}").json()
    batch = dict(c.get(f"/api/v1/imports/{bid}").json())
    batch["_job"] = job
    return batch


def run(
    c: TestClient, name: str, cfg: dict[str, Any], mode: str = "all_or_nothing"
) -> tuple[str, dict[str, Any]]:
    r = upload(c, name)
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    configure(c, bid, cfg)
    validate(c, bid)
    return bid, commit(c, bid, mode)


def errors(c: TestClient, bid: str) -> list[dict[str, Any]]:
    return list(c.get(f"/api/v1/imports/{bid}/errors").json()["items"])


def amounts(world: World, bid: str) -> list[str]:
    return [
        str(r[0])
        for r in world.sql(
            "SELECT amount FROM rl.purchase_lines WHERE batch_id = :b ORDER BY source_row", b=bid
        )
    ]


def test_case17_ambiguous_dates_require_explicit_format(org: Any) -> None:
    c, world, _, _ = org
    bid = upload(c, "17_ambiguous_dates.csv").json()["id"]
    preview = c.get(f"/api/v1/imports/{bid}/preview").json()
    assert preview["date_format_candidates"]["invoice_date"] == ["MM/DD/YYYY", "DD/MM/YYYY"]
    assert preview["suggested_columns"]["supplier_code"] == "Vendor"
    configure(c, bid, {"columns": COLUMNS})
    problems = c.post(f"/api/v1/imports/{bid}/validate-preview").json()["config_problems"]
    assert any("date format" in p for p in problems)
    configure(c, bid, {"date_format": "DD/MM/YYYY"})
    validate(c, bid)
    commit(c, bid)
    dates = [
        str(r[0])
        for r in world.sql(
            "SELECT invoice_date FROM rl.purchase_lines WHERE batch_id = :b ORDER BY source_row",
            b=bid,
        )
    ]
    assert dates == ["2026-04-03", "2026-06-05"]


@pytest.mark.parametrize(
    ("name", "encoding", "text"),
    [
        ("18_utf8_bom.csv", "utf-8-sig", "Café"),
        ("18_windows_1252.csv", "cp1252", "Café – dash"),
        ("18_utf16_bom.csv", "utf-16", "A"),
    ],
)
def test_case18_encoding_detected_and_overridable(
    org: Any, name: str, encoding: str, text: str
) -> None:
    c, _, _, _ = org
    r = upload(c, name)
    assert r.json()["config"]["encoding"] == encoding
    bid = r.json()["id"]
    preview = c.get(f"/api/v1/imports/{bid}/preview").json()
    assert preview["header"][0] == "Vendor"
    assert preview["sample_rows"][0][3] == text
    if encoding == "cp1252":
        configure(c, bid, {"encoding": "utf-8"})
        bad = c.get(f"/api/v1/imports/{bid}/preview")
        assert bad.status_code == 422 and bad.json()["code"] == "ENCODING_MISMATCH"


def test_case19_semicolon_and_comma_decimals(org: Any) -> None:
    c, world, _, _ = org
    r = upload(c, "19_semicolon_comma_decimals.csv")
    assert r.json()["config"]["delimiter"] == ";"
    bid = r.json()["id"]
    configure(
        c,
        bid,
        {**US, "date_format": "DD.MM.YYYY", "decimal_separator": ",", "thousands_separator": "."},
    )
    validate(c, bid)
    batch = commit(c, bid)
    assert batch["status"] == "committed", batch
    assert amounts(world, bid) == ["1234.5600", "-10.5000"]


def test_case20_negative_styles(org: Any) -> None:
    c, world, _, _ = org
    bid = upload(c, "20_parentheses_negative.csv").json()["id"]
    configure(c, bid, US)
    rows = c.post(f"/api/v1/imports/{bid}/validate-preview").json()["rows"]
    assert (
        rows[0]["issues"][0]["code"] == "NOT_A_NUMBER"
    )  # minus style chosen: parentheses rejected
    configure(c, bid, {"negative_style": "parentheses"})
    validate(c, bid)
    commit(c, bid)
    assert amounts(world, bid) == ["-1234.5600", "99.0000"]
    bid2, _ = run(c, "20_trailing_minus.csv", {**US, "negative_style": "trailing_minus"})
    assert amounts(world, bid2) == ["-1234.5600"]
    assert (
        world.sql("SELECT is_return FROM rl.purchase_lines WHERE batch_id = :b", b=bid2)[0][0]
        is True
    )


def test_case21_sku_leading_zero_and_scientific(org: Any) -> None:
    c, world, _, _ = org
    bid, batch = run(c, "21_sku_leading_zero_and_scientific.csv", US)
    assert batch["stats"]["rows_committed"] == 2
    assert [
        r[0]
        for r in world.sql(
            "SELECT sku FROM rl.purchase_lines WHERE batch_id = :b ORDER BY source_row", b=bid
        )
    ] == ["00123", "1.23E+11"]
    assert any(e["code"] == "SKU_SCIENTIFIC" and e["row"] == 3 for e in errors(c, bid))


def test_case22_duplicate_rows_within_file(org: Any) -> None:
    c, _, _, _ = org
    bid, batch = run(c, "22_duplicate_rows.csv", US)
    assert (batch["stats"]["rows_committed"], batch["stats"]["duplicates"]) == (2, 1)
    assert [e["row"] for e in errors(c, bid) if e["code"] == "DUPLICATE_ROW"] == [3]


def test_case23_same_file_twice_needs_confirmation(org: Any) -> None:
    c, _, _, _ = org
    first, _ = run(c, "22_duplicate_rows.csv", US)
    again = upload(c, "22_duplicate_rows.csv")
    assert again.status_code == 409
    body = again.json()
    assert body["code"] == "FILE_ALREADY_IMPORTED" and body["previous_batch_id"] == first
    confirmed = upload(c, "22_duplicate_rows.csv", confirm=True)
    assert confirmed.status_code == 201 and confirmed.json()["duplicate_of_batch_id"] == first
    bid = confirmed.json()["id"]
    configure(c, bid, US)
    validate(c, bid)
    batch = commit(c, bid)
    assert (batch["stats"]["rows_committed"], batch["stats"]["duplicates"]) == (0, 3)


def test_case24_unknown_suppliers_grouped_and_resolved(org: Any) -> None:
    c, _, _, acme = org
    bid = upload(c, "24_unknown_suppliers.csv").json()["id"]
    configure(c, bid, US)
    batch = validate(c, bid)
    assert batch["stats"]["unknown_supplier_codes"] == [
        {"code": "NEWCO", "rows": 2},
        {"code": "OTHER", "rows": 1},
    ]
    r = c.post(
        f"/api/v1/imports/{bid}/resolve-suppliers",
        json={
            "codes": {
                "newco": {"action": "create", "name": "New Co"},
                "OTHER": {"action": "map", "supplier_id": acme},
            }
        },
    )
    assert r.status_code == 200, r.text
    batch = validate(c, bid)
    assert batch["stats"]["rows_error"] == 0
    assert commit(c, bid)["stats"]["rows_committed"] == 4
    names = {s["name"] for s in c.get("/api/v1/suppliers").json()["items"]}
    assert names == {"Acme Electric", "New Co"}


def test_case25_non_usd_is_a_row_error(org: Any) -> None:
    c, _, _, _ = org
    bid, batch = run(c, "25_non_usd.csv", US, mode="skip_invalid")
    assert (batch["stats"]["rows_committed"], batch["stats"]["rows_skipped"]) == (1, 1)
    assert [e["code"] for e in errors(c, bid) if e["severity"] == "error"] == ["CURRENCY_NOT_USD"]


def test_case26_ragged_row_reported_not_shifted(org: Any) -> None:
    c, world, _, _ = org
    bid, batch = run(c, "26_ragged_row.csv", US, mode="skip_invalid")
    assert next(e for e in errors(c, bid) if e["code"] == "RAGGED_ROW")["row"] == 2
    assert batch["stats"]["rows_committed"] == 1
    assert (
        world.sql("SELECT invoice_number FROM rl.purchase_lines WHERE batch_id = :b", b=bid)[0][0]
        == "I2"
    )


def test_case28_zip_bomb_and_external_entity_rejected(org: Any) -> None:
    c, _, _, _ = org
    r = upload(c, "28_zip_bomb.xlsx")
    assert (r.status_code, r.json()["code"]) == (422, "XLSX_TOO_LARGE")
    r = upload(c, "28_external_entity.xlsx")
    if r.status_code == 201:  # the workbook part itself is fine; the sheet is refused on read
        r = c.get(f"/api/v1/imports/{r.json()['id']}/preview")
    assert r.status_code == 422 and r.json()["code"] == "XLSX_UNREADABLE"
    assert "root:" not in r.text


def test_file_type_and_signature_checks(org: Any) -> None:
    c, _, _, _ = org
    assert upload(c, "x.xlsm", b"PK\x03\x04").json()["code"] == "FILE_TYPE_NOT_ALLOWED"
    assert upload(c, "x.exe", b"MZ").json()["code"] == "FILE_TYPE_NOT_ALLOWED"
    assert upload(c, "fake.xlsx", b"just text").json()["code"] == "FILE_SIGNATURE_MISMATCH"
    assert upload(c, "fake.csv", b"PK\x03\x04binary").json()["code"] == "FILE_SIGNATURE_MISMATCH"
    assert upload(c, "empty.csv", b"").json()["code"] == "FILE_EMPTY"


def test_case29_crash_mid_commit_leaves_no_partial_batch(
    org: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import imports as svc
    from app.workers import jobs

    c, world, t, _ = org
    rows = "".join(f"ACME,I{i},1,A,1,10.00,01/15/2026,USD\n" for i in range(50))
    bid = upload(
        c, "big.csv", ("Vendor,Invoice,Line,Item,Qty,Ext,Inv Date,Currency\n" + rows).encode()
    ).json()["id"]
    configure(c, bid, US)
    validate(c, bid)
    monkeypatch.setattr(svc, "CHUNK", 10)
    real_insert = svc._insert
    calls = {"n": 0}

    def crashing(*args: Any) -> set[int]:
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("worker killed")
        return real_insert(*args)

    monkeypatch.setattr(svc, "_insert", crashing)
    r = c.post(f"/api/v1/imports/{bid}/commit", json={"mode": "all_or_nothing"})
    job_id = r.json()["job_id"]
    assert world.sql("SELECT count(*) FROM rl.purchase_lines WHERE batch_id = :b", b=bid)[0][0] == 0
    assert c.get(f"/api/v1/jobs/{job_id}").json()["status"] == "queued"  # will be retried
    monkeypatch.setattr(svc, "_insert", real_insert)
    jobs.run_job(uuid.UUID(job_id), t)  # the retry
    assert (
        world.sql("SELECT count(*) FROM rl.purchase_lines WHERE batch_id = :b", b=bid)[0][0] == 50
    )
    assert c.get(f"/api/v1/imports/{bid}").json()["status"] == "committed"


def test_all_or_nothing_vs_skip_invalid_and_error_report(org: Any) -> None:
    c, world, _, _ = org
    bid = upload(c, "25_non_usd.csv").json()["id"]
    configure(c, bid, US)
    validate(c, bid)
    batch = commit(c, bid)
    assert batch["status"] == "validated" and "skip invalid" in batch["stats"]["failure"]
    assert world.sql("SELECT count(*) FROM rl.purchase_lines WHERE batch_id = :b", b=bid)[0][0] == 0
    report = c.get(f"/api/v1/imports/{bid}/errors.csv")
    assert report.headers["content-disposition"].startswith("attachment")
    assert "CURRENCY_NOT_USD" in report.text
    assert commit(c, bid, "skip_invalid")["stats"]["rows_committed"] == 1


def test_void_excludes_rows_and_allows_reimport(org: Any) -> None:
    c, world, _, _ = org
    bid, _ = run(c, "22_duplicate_rows.csv", US)
    r = c.post(f"/api/v1/imports/{bid}/void", json={"reason": "wrong period"})
    assert r.status_code == 200 and r.json()["status"] == "voided"
    assert (
        world.sql("SELECT bool_and(voided) FROM rl.purchase_lines WHERE batch_id = :b", b=bid)[0][0]
        is True
    )
    again = upload(
        c, "22_duplicate_rows.csv"
    )  # voided batches don't trigger the duplicate-file warning
    assert again.status_code == 201
    bid2 = again.json()["id"]
    configure(c, bid2, US)
    validate(c, bid2)
    assert commit(c, bid2)["stats"]["rows_committed"] == 2
    assert (
        c.post(f"/api/v1/imports/{bid}/void", json={"reason": "again"}).json()["code"]
        == "IMPORT_NOT_COMMITTED"
    )


def test_xlsx_import_with_typed_cells(org: Any) -> None:
    from datetime import datetime

    from openpyxl import Workbook

    c, world, _, _ = org
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Vendor", "Invoice", "Line", "Item", "Qty", "Ext", "Inv Date", "Currency"])
    excel_date = datetime(2026, 2, 3)  # noqa: DTZ001 - Excel cells carry no timezone
    ws.append(["ACME", "I1", 1, "00123", 3, 1234.56, excel_date, "USD"])
    buf = io.BytesIO()
    wb.save(buf)
    r = upload(c, "book.xlsx", buf.getvalue())
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    configure(c, bid, {**US, "date_format": "YYYY-MM-DD"})
    validate(c, bid)
    assert commit(c, bid)["status"] == "committed"
    row = world.sql(
        "SELECT sku, quantity, amount, invoice_date FROM rl.purchase_lines WHERE batch_id = :b",
        b=bid,
    )[0]
    assert (row[0], str(row[1]), str(row[2]), str(row[3])) == (
        "00123",
        "3.0000",
        "1234.5600",
        "2026-02-03",
    )


def test_credits_baselines_products_suppliers(org: Any) -> None:
    c, world, _, acme = org
    credits = b"Vendor,Memo,Date,Amount,Program,Period\nACME,CM1,04/10/2026,500.00,PRG-1,2026-Q1\nACME,CM2,04/10/2026,500.00,,\nACME,CM1,04/11/2026,1.00,,\n"
    bid = upload(c, "credits.csv", credits, "credits").json()["id"]
    configure(
        c,
        bid,
        {
            "columns": {
                "supplier_code": "Vendor",
                "credit_reference": "Memo",
                "credit_date": "Date",
                "amount": "Amount",
                "agreement_reference": "Program",
                "period_label": "Period",
            },
            "date_format": "MM/DD/YYYY",
        },
    )
    validate(c, bid)
    batch = commit(c, bid)
    assert (batch["stats"]["rows_committed"], batch["stats"]["duplicates"]) == (2, 1)
    flags = {
        r[0]: r[1]
        for r in world.sql(
            "SELECT credit_reference, possible_duplicate FROM rl.credit_lines WHERE batch_id = :b",
            b=bid,
        )
    }
    assert flags == {"CM1": True, "CM2": True}

    products = b"SKU,Class,Desc\nA,WIRE,Wire\nB,LIGHTING,Lamp\n"
    bid = upload(c, "products.csv", products, "products").json()["id"]
    configure(c, bid, {"columns": {"sku": "SKU", "category": "Class", "description": "Desc"}})
    validate(c, bid)
    assert commit(c, bid)["stats"]["rows_committed"] == 2

    sups = b'Name,Code,Tags\nBeta Corp,BETA,"hvac, parts"\nAcme dup,ACME,\n'
    bid = upload(c, "suppliers.csv", sups, "suppliers").json()["id"]
    configure(c, bid, {"columns": {"name": "Name", "supplier_code": "Code", "tags": "Tags"}})
    validate(c, bid)
    batch = commit(c, bid)
    assert (batch["stats"]["rows_committed"], batch["stats"]["duplicates"]) == (1, 1)
    _ = acme


def test_idempotent_commit_and_upload(org: Any) -> None:
    c, world, _, _ = org
    key = str(uuid.uuid4())
    content = (FIX / "22_duplicate_rows.csv").read_bytes()
    r1 = c.post(
        "/api/v1/imports",
        files={"file": ("d.csv", content, "text/csv")},
        data={"import_type": "purchases"},
        headers={"Idempotency-Key": key},
    )
    r2 = c.post(
        "/api/v1/imports",
        files={"file": ("d.csv", content, "text/csv")},
        data={"import_type": "purchases"},
        headers={"Idempotency-Key": key},
    )
    assert r1.status_code == r2.status_code == 201 and r1.json()["id"] == r2.json()["id"]
    bid = r1.json()["id"]
    configure(c, bid, US)
    validate(c, bid)
    k2 = str(uuid.uuid4())
    a = c.post(
        f"/api/v1/imports/{bid}/commit",
        json={"mode": "all_or_nothing"},
        headers={"Idempotency-Key": k2},
    )
    b = c.post(
        f"/api/v1/imports/{bid}/commit",
        json={"mode": "all_or_nothing"},
        headers={"Idempotency-Key": k2},
    )
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    reused = c.post(
        f"/api/v1/imports/{bid}/commit",
        json={"mode": "skip_invalid"},
        headers={"Idempotency-Key": k2},
    )
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert world.sql("SELECT count(*) FROM rl.purchase_lines WHERE batch_id = :b", b=bid)[0][0] == 2


def test_streaming_import_of_50k_rows(org: Any) -> None:
    c, world, _, _ = org
    header = "Vendor,Invoice,Line,Item,Qty,Ext,Inv Date,Currency\n"
    body = "".join(
        f"ACME,I{i},1,SKU{i % 97},2,{i % 1000}.25,01/{(i % 28) + 1:02d}/2026,USD\n"
        for i in range(50_000)
    )
    bid = upload(c, "big.csv", (header + body).encode()).json()["id"]
    configure(c, bid, US)
    validate(c, bid)
    batch = commit(c, bid)
    assert batch["stats"]["rows_committed"] == 50_000
    assert batch["_job"]["progress"] == 50_000
    total = world.sql("SELECT sum(amount) FROM rl.purchase_lines WHERE batch_id = :b", b=bid)[0][0]
    expected = sum(int(i % 1000) for i in range(50_000)) + 50_000 * 0.25
    assert str(total) == f"{expected:.4f}"
