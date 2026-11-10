"""Validation messages of the agreements YAML format."""

from __future__ import annotations

from typing import Any

import pytest

from app.pilot.agreements import AgreementFormatError, decimal_value, parse_agreements

VERSION: dict[str, Any] = {
    "version_no": 1,
    "effective_from": "2026-01-01",
    "period": {
        "type": "custom",
        "fiscal_year_start_month": 1,
        "custom_periods": [{"start": "2026-01-01", "end": "2026-02-14", "label": "P1"}],
    },
    "date_basis": "invoice_date",
    "measure": "spend",
    "spend_basis": "net_of_returns",
    "threshold_comparison": "gte",
    "negative_result": "floor_at_zero",
    "rounding_mode": "half_up",
    "payment_terms_days": 30,
    "stacking": "stackable",
    "prorate_thresholds_on_partial_period": False,
    "zero_baseline_policy": "needs_review",
    "eligibility": [{"action": "include", "field": "sku", "values": ["A", 100]}],
    "components": [
        {"id": "t", "type": "tiered_all_units", "tiers": [{"threshold": 5, "rate": "0.01"}]}
    ],
}


def doc(**version_overrides: Any) -> dict[str, Any]:
    return {
        "agreements": [
            {"id": "A1", "supplier": "S1", "versions": [{**VERSION, **version_overrides}]}
        ]
    }


def test_valid_document() -> None:
    [spec] = parse_agreements(doc())
    v = spec.versions[0]
    assert v.custom_periods[0].label == "P1"
    assert v.eligibility[0].values == frozenset({"A", "100"})
    assert v.eligibility[0].id == "rule01"


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (None, "top level"),
        ({"agreements": []}, "non-empty list"),
        ({"agreements": ["x"]}, "must be a mapping"),
        ({"agreements": [{"id": "A", "supplier": "S", "versions": []}]}, "versions"),
        ({"agreements": [{"id": "A", "supplier": "S", "versions": ["x"]}]}, "must be a mapping"),
        (
            {"agreements": [{"id": " ", "supplier": "S", "versions": [VERSION]}]},
            "must not be empty",
        ),
        ({"agreements": [{"id": True, "supplier": "S", "versions": [VERSION]}]}, "must be text"),
        (
            {"agreements": [{"id": "A", "supplier": "S", "versions": [VERSION]}] * 2},
            "duplicate agreement id",
        ),
        (doc(measure="weight"), "not one of"),
        (doc(effective_from="01/01/2026"), "YYYY-MM-DD"),
        (doc(payment_terms_days="30"), "whole number"),
        (doc(prorate_thresholds_on_partial_period="no"), "true or false"),
        (doc(period="quarterly"), "period: must be a mapping"),
        (doc(components=[]), "non-empty list"),
        (doc(components=["x"]), "must be a mapping"),
        (doc(components=[{"id": "t", "type": "tiered_all_units", "tiers": []}]), "non-empty list"),
        (
            doc(components=[{"id": "t", "type": "tiered_all_units", "tiers": ["x"]}]),
            "must be a mapping",
        ),
        (doc(components=[{"id": "t", "type": "flat_percent"}]), "needs rate"),
        (doc(eligibility="sku"), "must be a list"),
        (doc(eligibility=["x"]), "must be a mapping"),
        (doc(eligibility=[{"action": "include", "field": "sku", "values": "A"}]), "must be a list"),
        (doc(cap_amount="ten"), "not a decimal"),
        (doc(cap_amount="Infinity"), "finite"),
        (doc(cap_amount=[1]), "decimal number in quotes"),
    ],
)
def test_errors_name_the_path(data: Any, fragment: str) -> None:
    with pytest.raises(AgreementFormatError) as exc:
        parse_agreements(data)
    assert fragment in str(exc.value)


def test_decimal_value_rejects_floats() -> None:
    with pytest.raises(AgreementFormatError, match="quoted"):
        decimal_value(0.1, "x")
