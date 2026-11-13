"""ERP presets through the API (v1.1 Phase 12)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.api.conftest import World, login
from tests.api.test_import_pipeline import commit, configure, upload, validate

P21_FILE = (
    b"Supplier ID,Vendor Invoice No,Line No,Item ID,Qty Received,Unit Cost,Extended Cost,"
    b"Invoice Date,Date Received,Location ID,Product Group ID,Item Desc\n"
    b"acme,INV-1001,1,WIRE-12,10,4.50,45.00,01/15/2026,01/14/2026,MAIN,WIRE,12 AWG wire\n"
    b'acme,INV-1001,2,BOX-4,4,"1,250.00","5,000.00",01/15/2026,01/14/2026,MAIN,BOX,Box\n'
)


def _org(c: TestClient, world: World) -> uuid.UUID:
    t = world.tenant()
    login(c, world.member(t, "analyst"))
    r = c.post("/api/v1/suppliers", json={"name": "Acme Electric", "codes": ["acme"]})
    assert r.status_code == 201, r.text
    return t


def test_p21_file_is_recognised_applied_confirmed_and_committed(
    app_client: TestClient, world: World
) -> None:
    c = app_client
    _org(c, world)
    bid = upload(c, "p21.csv", P21_FILE).json()["id"]

    pv = c.get(f"/api/v1/imports/{bid}/preview").json()
    assert pv["preset_suggestion"] == {
        "id": "p21-purchases",
        "erp": "Epicor Prophet 21",
        "report": "PO receipt / purchase history export",
        "verified": False,
    }
    assert pv["applied_preset_id"] is None

    r = c.post(f"/api/v1/imports/{bid}/preset", json={"preset_id": "p21-purchases"})
    assert r.status_code == 200, r.text
    cfg = r.json()["config"]
    assert cfg["columns"]["sku"] == "Item ID"
    assert cfg["columns"]["amount"] == "Extended Cost"
    assert cfg["columns"]["receipt_date"] == "Date Received"
    assert cfg["date_format"] == "MM/DD/YYYY"
    assert cfg["confirmed"] is False, "a preset is a suggestion until the user confirms it"

    # Committing before the user confirms is refused.
    r = c.post(f"/api/v1/imports/{bid}/validate")
    assert r.status_code == 409 and r.json()["code"] == "IMPORT_NOT_CONFIGURED"

    configure(c, bid, {"columns": cfg["columns"]})  # the user reviews and confirms
    assert c.get(f"/api/v1/imports/{bid}/preview").json()["applied_preset_id"] == "p21-purchases"
    batch = validate(c, bid)
    assert batch["stats"]["rows_valid"] == 2, batch["stats"]
    done = commit(c, bid)
    assert done["status"] == "committed", done
    assert done["stats"]["rows_committed"] == 2


def test_preset_that_does_not_fit_changes_nothing(app_client: TestClient, world: World) -> None:
    c = app_client
    _org(c, world)
    bid = upload(c, "plain.csv", b"Vendor,Invoice,Item,Qty,Ext\nacme,1,A,1,1.00\n").json()["id"]
    before = c.get(f"/api/v1/imports/{bid}").json()["config"]
    r = c.post(f"/api/v1/imports/{bid}/preset", json={"preset_id": "p21-purchases"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "PRESET_DOES_NOT_FIT"
    assert "supplier_code" in body["missing_fields"]
    assert c.get(f"/api/v1/imports/{bid}").json()["config"] == before
    assert c.get(f"/api/v1/imports/{bid}/preview").json()["preset_suggestion"] is None


def test_preset_for_another_import_type_is_refused(app_client: TestClient, world: World) -> None:
    c = app_client
    _org(c, world)
    bid = upload(c, "p21b.csv", P21_FILE).json()["id"]
    r = c.post(f"/api/v1/imports/{bid}/preset", json={"preset_id": "qbo-credits"})
    assert r.status_code == 422 and r.json()["code"] == "PRESET_TYPE_MISMATCH"
    r = c.post(f"/api/v1/imports/{bid}/preset", json={"preset_id": "no-such-preset"})
    assert r.status_code == 404


def test_presets_are_listed_and_filtered_for_viewers(app_client: TestClient, world: World) -> None:
    c = app_client
    t = world.tenant()
    login(c, world.member(t, "viewer"))
    all_ = c.get("/api/v1/import-presets").json()
    assert {p["id"] for p in all_} >= {"p21-purchases", "netsuite-credits"}
    assert all(p["verified"] is False for p in all_)
    credits = c.get("/api/v1/import-presets", params={"import_type": "credits"}).json()
    assert credits and all(p["import_type"] == "credits" for p in credits)

    r = c.get("/api/v1/import-presets/header.csv", params={"preset_id": "p21-purchases"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0].startswith("Supplier ID,Vendor Invoice No,Line No,Item ID")
    bad = c.get("/api/v1/import-presets/header.csv", params={"preset_id": "../etc"})
    assert bad.status_code == 422


def test_template_from_preset_is_a_normal_editable_template(
    app_client: TestClient, world: World
) -> None:
    c = app_client
    _org(c, world)
    r = c.post(
        "/api/v1/import-templates/from-preset",
        json={"preset_id": "netsuite-credits", "name": "Our NetSuite credits", "is_default": True},
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["import_type"] == "credits" and t["is_default"] is True
    assert t["config"]["columns"]["credit_reference"] == "Document Number"
    assert "preset_id" not in t["config"]
    listed = c.get("/api/v1/import-templates", params={"import_type": "credits"}).json()
    assert [x["id"] for x in listed] == [t["id"]]
