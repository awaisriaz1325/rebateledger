"""Phase 7: reports, exports, evidence packs, full data export (PHASES §7)."""

from __future__ import annotations

import csv
import http.server
import io
import threading
import uuid
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.core.csv_safe import DANGEROUS_PREFIXES
from app.exports.writers import (
    Column,
    NoNetworkFetcher,
    Table,
    html_to_pdf,
    to_csv,
    to_pdf,
    to_xlsx,
)
from tests.api.conftest import World, login, step_up
from tests.api.test_workflow import CREDIT_COLS, _client, imp, run, world_setup  # noqa: F401

MALICIOUS = [
    '=HYPERLINK("http://evil.example/x","click")',
    "+cmd|' /C calc'!A0",
    "@SUM(1+1)*cmd|' /C calc'!A0",
    "-2+3+cmd|' /C calc'!A0",
    "\t=1+1",
    "\r=1+1",
]


def _download(c: TestClient, export: dict[str, Any]) -> bytes:
    e = c.get(f"/api/v1/exports/{export['id']}").json()
    assert e["status"] == "succeeded", e
    link = c.post(f"/api/v1/exports/{export['id']}/link").json()
    assert link["url"].startswith("/api/v1/exports/download?token=")
    r = c.get(link["url"])
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"].startswith("attachment;")
    return r.content


def _export(c: TestClient, report: str, fmt: str, **params: str) -> dict[str, Any]:
    r = c.post(
        "/api/v1/exports",
        json={"report": report, "format": fmt, "params": params},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 202, r.text
    return dict(r.json())


def _assert_csv_safe(data: bytes) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    for row in rows:
        for cell in row:
            assert not cell.startswith(DANGEROUS_PREFIXES), cell
    return rows


def _assert_xlsx_safe(data: bytes) -> list[tuple[Any, ...]]:
    wb = openpyxl.load_workbook(io.BytesIO(data))
    values = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert cell.data_type != "f", (ws.title, cell.coordinate, cell.value)
                if isinstance(cell.value, str):
                    assert not cell.value.startswith(DANGEROUS_PREFIXES), cell.value
            values.append(tuple(c.value for c in row))
    return values


# --------------------------------------------------------------------------- writers (unit)


def _table() -> Table:
    return Table(
        title="T",
        columns=[
            Column("name", "Name"),
            Column("amount", "Amount", "money"),
            Column("n", "Count", "int"),
        ],
        rows=[{"name": m, "amount": Decimal("-12.3400"), "n": 3} for m in MALICIOUS],
        totals={"amount": Decimal("-74.0400")},
    )


def test_writers_neutralise_every_malicious_cell() -> None:
    rows = _assert_csv_safe(to_csv(_table()))
    assert [r[0] for r in rows[1:-1]] == ["'" + m for m in MALICIOUS]
    assert (
        rows[1][1] == "'-12.3400"
    )  # CSV is all text: negative numbers are quoted too (SPEC accepts)
    assert rows[-1] == ["Total", "'-74.0400", ""]

    values = _assert_xlsx_safe(to_xlsx(_table()))
    report = values[: len(MALICIOUS) + 2]
    # XML parsing normalises a carriage return to a line feed; the protective quote stays.
    assert [v[0] for v in report[1:-1]] == ["'" + m.replace("\r", "\n") for m in MALICIOUS]
    assert report[1][1] == Decimal("-12.34") or report[1][1] == pytest.approx(
        -12.34
    )  # typed number
    assert isinstance(report[1][1], int | float | Decimal) and isinstance(report[1][2], int)


class _Counter(http.server.BaseHTTPRequestHandler):
    hits: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        _Counter.hits.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/css")
        self.end_headers()
        self.wfile.write(b"body{color:red}")

    def log_message(self, *args: Any) -> None:
        pass


def test_pdf_renderer_cannot_fetch_any_url() -> None:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Counter)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    _Counter.hits.clear()
    try:
        html = f"""<html><head>
          <link rel="stylesheet" href="{base}/sheet.css">
          <style>@import url("{base}/import.css"); @font-face {{ font-family: x; src: url("{base}/font.woff"); }}
                 body {{ background: url("{base}/bg.png"); }}</style></head>
          <body><img src="{base}/img.png"><img src="file:///etc/hostname"><object data="{base}/obj"></object>
          <iframe src="{base}/frame"></iframe><a href="{base}/link">link</a></body></html>"""
        fetcher = NoNetworkFetcher()
        pdf = html_to_pdf(html, fetcher)
        assert pdf.startswith(b"%PDF")
        assert _Counter.hits == []
        assert any(u.startswith(base) for u in fetcher.blocked)
        assert "file:///etc/hostname" in fetcher.blocked
        # User-supplied text is escaped, so it can never become markup that fetches.
        table = Table(
            title="x", columns=[Column("n", "Name")], rows=[{"n": f'<img src="{base}/user.png">'}]
        )
        assert to_pdf(
            table,
            organization=f'<link rel=stylesheet href="{base}/o.css">',
            generated_at=datetime.now(UTC),
        ).startswith(b"%PDF")
        assert _Counter.hits == []
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------------- API


def test_report_exports_neutralise_names_in_every_format(
    app_client: TestClient, world: World
) -> None:
    t = world.tenant()
    login(app_client, world.member(t, "analyst"))
    for i, name in enumerate(MALICIOUS[:4]):
        sid = app_client.post("/api/v1/suppliers", json={"name": name, "codes": [f"C{i}"]}).json()[
            "id"
        ]
        from tests.api.factories import TERMS

        r = app_client.post(
            "/api/v1/agreements",
            json={
                "supplier_id": sid,
                "name": MALICIOUS[(i + 1) % 4],
                "external_reference": f"@R{i}",
                "terms": TERMS,
            },
        )
        assert r.status_code == 201, r.text
    preview = app_client.get(
        "/api/v1/reports/preview", params={"report": "agreement_register"}
    ).json()
    assert preview["row_count"] == 4 and not preview["truncated"]
    assert {r["supplier"] for r in preview["rows"]} == set(MALICIOUS[:4])  # screen shows raw text

    rows = _assert_csv_safe(_download(app_client, _export(app_client, "agreement_register", "csv")))
    assert {r[0] for r in rows[1:]} == {"'" + m for m in MALICIOUS[:4]}
    values = _assert_xlsx_safe(
        _download(app_client, _export(app_client, "agreement_register", "xlsx"))
    )
    assert {v[0] for v in values[1:5]} == {"'" + m for m in MALICIOUS[:4]}
    pdf_req = app_client.post(
        "/api/v1/exports",
        json={"report": "agreement_register", "format": "pdf"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert pdf_req.json()["code"] == "FORMAT_UNAVAILABLE"
    assert _download(app_client, _export(app_client, "reconciliation_summary", "pdf")).startswith(
        b"%PDF"
    )


def test_evidence_pack_reconciles_with_screen(world_setup: Any) -> None:  # noqa: F811 - shared fixture
    c = world_setup[0]
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-1,04/20/2025,1500.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)
    screen = {r["period_start"]: r for r in c.get("/api/v1/reconciliation").json()}
    q1 = screen["2025-01-01"]
    claim = c.post(
        "/api/v1/claims", json={"result_ids": [q1["result_id"]], "title": '=HYPERLINK("x")'}
    ).json()
    c.post(f"/api/v1/claims/{claim['id']}/notes", json={"text": "Called Jo at Acme"})
    r = c.post(
        f"/api/v1/claims/{claim['id']}/evidence-pack",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 202, r.text
    z = zipfile.ZipFile(io.BytesIO(_download(c, r.json())))
    names = set(z.namelist())
    assert {
        f"claim-{claim['number']}-evidence.pdf",
        "summary.csv",
        "eligible-lines.csv",
        "credits.csv",
    } <= names
    assert z.read(f"claim-{claim['number']}-evidence.pdf").startswith(b"%PDF")

    summary = _assert_csv_safe(z.read("summary.csv"))
    head, item, total = summary[0], summary[1], summary[-1]
    assert head == ["Agreement", "Period", "Start", "End", "Expected", "Received", "Variance"]
    # Exactly the numbers on the Results screen (string-for-string, no float anywhere).
    assert (item[4], item[5], item[6]) == (
        q1["expected"],
        q1["received"],
        q1["variance"].replace("-", "'-"),
    )
    assert Decimal(total[4]) == Decimal(q1["expected"]) and Decimal(total[5]) == Decimal(
        q1["received"]
    )

    detail = c.get(f"/api/v1/results/{q1['result_id']}").json()
    lines = _assert_csv_safe(z.read("eligible-lines.csv"))[1:]
    eligible = [ln for ln in lines if ln[2] == "yes"]
    assert sorted(ln[3] for ln in eligible) == ["I1", "I2"]
    assert sum(Decimal(ln[10]) for ln in eligible) == Decimal(detail["spend"]) == Decimal("100000")
    credits = _assert_csv_safe(z.read("credits.csv"))[1:]
    assert [(cr[2], Decimal(cr[5])) for cr in credits] == [("CM-1", Decimal("1500"))]


def test_links_are_bound_to_user_and_short_lived(world_setup: Any) -> None:  # noqa: F811 - shared fixture
    c, world, t = world_setup[:3]
    export = _export(c, "claims_register", "csv")
    link = c.post(f"/api/v1/exports/{export['id']}/link").json()
    expires = datetime.fromisoformat(link["expires_at"])
    assert 0 < (expires - datetime.now(UTC)).total_seconds() <= 15 * 60

    other = _client(c)
    login(other, world.member(t, "analyst"))
    assert other.get(link["url"]).json()["code"] == "LINK_INVALID"  # someone else's link
    assert other.get(f"/api/v1/exports/{export['id']}").status_code == 404  # someone else's export
    assert other.post(f"/api/v1/exports/{export['id']}/link").status_code == 404
    assert c.get(link["url"][:-4] + "beef").json()["code"] == "LINK_INVALID"  # tampered
    assert all(e["id"] != export["id"] for e in other.get("/api/v1/exports").json())

    owner = _client(c)
    login(owner, world.member(t, "owner"))
    assert any(e["id"] == export["id"] for e in owner.get("/api/v1/exports").json())

    world.sql(
        "UPDATE rl.exports SET expires_at = now() - interval '1 minute' WHERE id = :e",
        e=export["id"],
    )
    assert c.post(f"/api/v1/exports/{export['id']}/link").json()["code"] == "EXPORT_NOT_READY"


def test_full_data_export_owner_only_with_step_up(world_setup: Any) -> None:  # noqa: F811 - shared fixture
    c, world, t = world_setup[:3]
    assert c.post("/api/v1/org/data-export").status_code == 403  # analyst
    owner_member = world.member(t, "owner")
    owner = _client(c)
    login(owner, owner_member)
    world.sql(
        "UPDATE rl.sessions SET stepped_up_at = NULL WHERE user_id = :u", u=owner_member.user_id
    )
    assert owner.post("/api/v1/org/data-export").json()["code"] == "STEP_UP_REQUIRED"
    step_up(owner, owner_member)
    r = owner.post("/api/v1/org/data-export", headers={"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 202, r.text
    export = r.json()
    assert export["kind"] == "full_export"
    z = zipfile.ZipFile(io.BytesIO(_download(owner, export)))
    names = set(z.namelist())
    assert {
        "README.txt",
        "suppliers.csv",
        "purchase_lines.csv",
        "members.csv",
        "audit_events.csv",
    } <= names
    assert not {"jobs.csv", "idempotency_keys.csv", "exports.csv"} & names
    assert any(n.startswith("files/imports/") for n in names)
    for name in names:
        if name.endswith(".csv"):
            header = z.read(name).decode("utf-8").splitlines()[0]
            for secret in ("token_hash", "password_hash", "secret_encrypted", "storage_key"):
                assert secret not in header, (name, header)
    suppliers = list(csv.DictReader(io.StringIO(z.read("suppliers.csv").decode())))
    assert [s["name"] for s in suppliers] == ["Acme"]
    members = list(csv.DictReader(io.StringIO(z.read("members.csv").decode())))
    assert {m["role"] for m in members} >= {"analyst", "owner"}
    # The analyst cannot see or download the owner's full export.
    assert c.get(f"/api/v1/exports/{export['id']}").status_code == 404
