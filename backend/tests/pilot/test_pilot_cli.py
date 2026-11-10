"""End-to-end tests of the pilot CLI on docs/pilot-samples and on crafted bad inputs."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.cli import main

SAMPLES = Path(__file__).resolve().parents[3] / "docs" / "pilot-samples"


def _args(out: Path, *extra: str) -> list[str]:
    return [
        "pilot",
        "--agreements",
        str(SAMPLES / "agreements.yaml"),
        "--purchases",
        str(SAMPLES / "purchases.csv"),
        "--credits",
        str(SAMPLES / "credits.csv"),
        "--mapping",
        str(SAMPLES / "mapping.yaml"),
        "--baselines",
        str(SAMPLES / "baselines.csv"),
        "--allocations",
        str(SAMPLES / "allocations.csv"),
        "--from",
        "2026-01-01",
        "--to",
        "2026-06-30",
        "--as-of",
        "2026-09-15",
        "--out",
        str(out),
        *extra,
    ]


def _results(out: Path) -> dict[tuple[str, str], dict[str, str]]:
    with (out / "results.csv").open(encoding="utf-8") as fh:
        return {(r["agreement_id"], r["period_start"]): r for r in csv.DictReader(fh)}


def test_sample_run_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_args(tmp_path)) == 0
    summary = capsys.readouterr().out
    assert "identified, NOT recovered" in summary
    rows = _results(tmp_path)
    acme_q1 = rows[("ACME-VOL", "2026-01-01")]
    assert (acme_q1["expected"], acme_q1["recon_status"]) == ("18707.46", "MATCHED")
    assert rows[("ACME-VOL", "2026-04-01")]["recon_status"] == "SHORT_PAID"
    assert rows[("COOLAIR-GROWTH", "2026-01-01")]["recon_status"] == "MISSING"
    assert rows[("COOLAIR-GROWTH", "2026-04-01")]["recon_status"] == "PENDING"
    assert rows[("PIPE-PEX", "2026-01-01")]["recon_status"] == "MATCHED"  # manual allocation
    review = rows[("PIPE-PEX", "2026-04-01")]
    assert review["recon_status"] == "NEEDS_REVIEW"
    assert "VERSION_CHANGE_IN_PERIOD" in review["review_reasons"]
    # Negative variances are neutralised against formula injection in CSV.
    assert rows[("ACME-VOL", "2026-04-01")]["variance"] == "'-4629.78"
    with (tmp_path / "unmatched_credits.csv").open(encoding="utf-8") as fh:
        unmatched = list(csv.DictReader(fh))
    assert [u["credit_reference"] for u in unmatched] == ["CA-CM-2290"]
    assert "COOLAIR-GROWTH 2026-01-01..2026-03-31" in unmatched[0]["suggestions"]
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "tier 2 reached" in html and "identified</strong>, not recovered" in html


def test_resolutions_split_the_period(tmp_path: Path) -> None:
    assert main(_args(tmp_path, "--resolutions", str(SAMPLES / "resolutions.yaml"))) == 0
    rows = _results(tmp_path)
    assert rows[("PIPE-PEX", "2026-04-01")]["period_end"] == "2026-04-30"
    assert rows[("PIPE-PEX", "2026-05-01")]["engine_statuses"] == "OK PARTIAL_PERIOD"


def test_outputs_are_deterministic(tmp_path: Path) -> None:
    assert main(_args(tmp_path / "a")) == 0
    assert main(_args(tmp_path / "b")) == 0
    for name in ("results.csv", "discrepancies.csv", "unmatched_credits.csv", "report.html"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def _write(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.write_text(text, encoding="utf-8")
    return p


MAPPING = """
purchases:
  date_format: MM/DD/YYYY
  columns: {supplier_code: V, invoice_number: I, line_number: L, sku: S, quantity: Q, amount: A, invoice_date: D, currency: C, unit_price: P}
  flags: {promo: F}
credits:
  date_format: MM/DD/YYYY
  credit_sign: negative
  columns: {supplier_code: V, credit_reference: R, credit_date: D, amount: A, period_start: PS, period_end: PE, agreement_reference: G}
"""
AGREEMENTS = """
agreements:
  - id: A1
    supplier: S1
    external_reference: REF-1
    versions:
      - version_no: 1
        effective_from: 2026-01-01
        period: {type: quarterly, fiscal_year_start_month: 1}
        date_basis: invoice_date
        measure: spend
        spend_basis: net_of_returns
        threshold_comparison: gte
        negative_result: floor_at_zero
        rounding_mode: half_up
        payment_terms_days: 30
        stacking: stackable
        prorate_thresholds_on_partial_period: false
        zero_baseline_policy: needs_review
        components: [{id: base, type: flat_percent, rate: "0.02"}]
"""


def _bad_inputs(tmp_path: Path) -> list[str]:
    purchases = _write(
        tmp_path,
        "p.csv",
        "V,I,L,S,Q,A,D,C,F,P\n"
        "S1,INV1,1,00123,1,1000.00,01/15/2026,USD,Y,1000\n"
        "S1,INV1,1,00123,1,1000.00,01/15/2026,USD,Y,1000\n"  # duplicate key
        "S1,INV2,1,1.23E+11,2,10.00,01/16/2026,usd,N,9\n"  # sci SKU warning + price mismatch
        "S1,INV3,1,X,1,10.00,13/45/2026,USD,N,10\n"  # invalid date
        "S1,INV4,1,X,1,10.00,01/16/2026,EUR,N,10\n"  # non-USD
        "S1,INV5,1,X,1,10.00,01/16/2026,USD,N,10,extra\n"  # ragged
        "S1,INV6,1,X,abc,10.00,01/16/2026,USD,maybe,10\n"  # bad qty, bad flag
        ",,,,,,,,,\n",  # empty row dropped
    )
    credits = _write(
        tmp_path, "c.csv", "V,R,D,A,PS,PE,G\nS1,CR1,04/10/2026,-20.00,01/01/2026,03/31/2026,ref-1\n"
    )
    return [
        "pilot",
        "--agreements",
        str(_write(tmp_path, "a.yaml", AGREEMENTS)),
        "--purchases",
        str(purchases),
        "--credits",
        str(credits),
        "--mapping",
        str(_write(tmp_path, "m.yaml", MAPPING)),
        "--from",
        "2026-01-01",
        "--to",
        "2026-03-31",
        "--as-of",
        "2026-06-01",
        "--out",
        str(tmp_path / "out"),
    ]


def test_row_errors_stop_the_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_bad_inputs(tmp_path)) == 2
    assert "row error" in capsys.readouterr().err


def test_skip_invalid_reports_every_issue(tmp_path: Path) -> None:
    assert main([*_bad_inputs(tmp_path), "--skip-invalid"]) == 0
    with (tmp_path / "out" / "issues.csv").open(encoding="utf-8") as fh:
        codes = sorted(r["code"] for r in csv.DictReader(fh))
    assert codes == sorted(
        [
            "DUPLICATE_ROW",
            "SKU_SCIENTIFIC",
            "AMOUNT_MISMATCH",
            "INVALID_DATE",
            "CURRENCY_NOT_USD",
            "RAGGED_ROW",
            "NOT_A_NUMBER",
            "NOT_A_BOOLEAN",
        ]
    )
    rows = _results(tmp_path / "out")
    q1 = rows[("A1", "2026-01-01")]
    # 1000.00 + 10.00 kept → 2% = 20.20; credit −20.00 in file with negative sign convention = +20.00
    assert (q1["expected"], q1["received"], q1["recon_status"]) == ("20.20", "20.00", "MATCHED")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda a: a.__setitem__(a.index("--to") + 1, "2025-01-01"), "--to is before --from"),
        (lambda a: a.__setitem__(a.index("--agreements") + 1, "/nonexistent.yaml"), "cannot read"),
    ],
)
def test_input_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutate: object, message: str
) -> None:
    args = _args(tmp_path)
    mutate(args)  # type: ignore[operator]
    assert main(args) == 2
    assert message in capsys.readouterr().err


def test_bad_agreement_yaml_reports_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = AGREEMENTS.replace('rate: "0.02"', "rate: 0.02")
    args = _bad_inputs(tmp_path)
    args[args.index("--agreements") + 1] = str(_write(tmp_path, "bad.yaml", bad))
    assert main(args) == 2
    err = capsys.readouterr().err
    assert "components[0]" in err and "quoted text" in err


def test_bad_argument_formats() -> None:
    with pytest.raises(SystemExit):
        main(["pilot", "--from", "01/01/2026"])
    with pytest.raises(SystemExit):
        main(["pilot", "--coverage-start", "nodate"])
