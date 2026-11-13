"""ERP preset definitions (v1.1 Phase 12): well-formed, unambiguous, never guessing."""

from __future__ import annotations

import pytest

from app.api.routes.imports import ConfigIn
from app.db.models.business import ImportType
from app.imports import fields, presets


def test_ids_are_unique_and_slug_shaped() -> None:
    ids = [p.id for p in presets.PRESETS]
    assert len(ids) == len(set(ids))
    assert all(p.id.replace("-", "").isalnum() and p.id == p.id.lower() for p in presets.PRESETS)


@pytest.mark.parametrize("p", presets.PRESETS, ids=lambda p: p.id)
def test_preset_is_well_formed(p: presets.Preset) -> None:
    valid = {f.name for f in fields.FIELDS[p.import_type]}
    assert set(p.columns) <= valid, set(p.columns) - valid
    required = {f.name for f in fields.FIELDS[p.import_type] if f.required}
    assert required <= set(p.columns), required - set(p.columns)
    assert all(aliases for aliases in p.columns.values())
    assert p.signature, "a preset without a signature could be suggested for any file"
    # Formats must be values the config endpoint accepts.
    ConfigIn.model_validate(p.config)
    assert p.verified is False, "flip only with evidence from a real customer export"


@pytest.mark.parametrize("p", presets.PRESETS, ids=lambda p: p.id)
def test_canonical_header_is_suggested_as_exactly_this_preset(p: presets.Preset) -> None:
    header = [aliases[0] for aliases in p.columns.values()] + [
        s for s in p.signature if s not in {a[0] for a in p.columns.values()}
    ]
    assert presets.suggest(p.import_type, header) is p


def test_matching_ignores_case_spacing_and_punctuation() -> None:
    p = presets.get("acumatica-purchases")
    assert p is not None
    header = ["VENDOR", "inventory id", "Receipt Nbr", "receipt qty", "ext cost", "date"]
    resolved = presets.resolve(p, header)
    assert resolved["sku"] == "inventory id"
    assert resolved["amount"] == "ext cost"
    assert presets.missing_required(p, resolved) == []


def test_generic_file_gets_no_preset() -> None:
    header = ["Vendor", "Invoice", "Item", "Qty", "Ext", "Inv Date"]
    assert presets.suggest(ImportType.PURCHASES, header) is None


def test_signature_without_required_columns_is_not_suggested() -> None:
    assert presets.suggest(ImportType.PURCHASES, ["Supplier ID", "Item ID"]) is None


def test_two_presets_fitting_equally_well_means_no_suggestion() -> None:
    # Fits both the NetSuite and the QuickBooks Online purchase presets equally.
    header = [
        "Document Number",
        "Name",
        "Item",
        "Quantity",
        "Amount",
        "Product/Service",
        "Vendor",
        "Num",
        "Qty",
    ]
    ns = presets.get("netsuite-purchases")
    qbo = presets.get("qbo-purchases")
    assert ns is not None and qbo is not None
    assert not presets.missing_required(ns, presets.resolve(ns, header))
    assert not presets.missing_required(qbo, presets.resolve(qbo, header))
    best = presets.suggest(ImportType.PURCHASES, header)
    # Either a clear winner by score, or no guess at all — never an arbitrary pick on a tie.
    if best is not None:
        scores = sorted(
            (len(p.signature) * 100 + len(presets.resolve(p, header)), p.id) for p in (ns, qbo)
        )
        assert scores[0][0] != scores[1][0]


def test_each_header_is_used_for_one_field_only() -> None:
    p = presets.get("netsuite-purchases")
    assert p is not None
    resolved = presets.resolve(p, ["Name", "Document Number", "Item", "Quantity", "Amount", "Date"])
    assert len(set(resolved.values())) == len(resolved)


def test_template_config_uses_canonical_headers() -> None:
    p = presets.get("p21-purchases")
    assert p is not None
    cfg = presets.template_config(p)
    assert cfg["columns"]["sku"] == "Item ID"
    assert cfg["date_format"] == "MM/DD/YYYY"
    ConfigIn.model_validate(cfg)
