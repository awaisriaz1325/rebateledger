"""CSV loaders for the pilot CLI, driven by a mapping config (docs/pilot-cli.md)."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.engine.models import Baseline, PurchaseLine
from app.engine.reconcile import Allocation, Credit, Tolerance
from app.imports.parsing import (
    DEFAULT_FALSE,
    DEFAULT_TRUE,
    NegativeStyle,
    NumberFormat,
    ParseError,
    clean_text,
    looks_like_scientific,
    parse_bool,
    parse_date,
    parse_decimal,
)
from app.pilot.agreements import AgreementFormatError, decimal_value


@dataclass(frozen=True)
class FileFormat:
    columns: Mapping[str, str]
    flags: Mapping[str, str]
    date_format: str
    number: NumberFormat
    encoding: str
    delimiter: str
    credits_negative_in_file: bool = False


@dataclass(frozen=True)
class MappingConfig:
    purchases: FileFormat
    credits: FileFormat
    baselines: FileFormat | None
    allocations: FileFormat | None
    tolerance: Tolerance
    true_values: frozenset[str] = DEFAULT_TRUE
    false_values: frozenset[str] = DEFAULT_FALSE


@dataclass
class RowIssue:
    file: str
    row: int
    column: str
    value: str
    code: str
    message: str
    severity: str = "error"


@dataclass
class Loaded[T]:
    items: list[T] = field(default_factory=list)
    issues: list[RowIssue] = field(default_factory=list)
    rows_read: int = 0
    duplicates: int = 0

    @property
    def errors(self) -> list[RowIssue]:
        return [i for i in self.issues if i.severity == "error"]


REQUIRED = {
    "purchases": ("supplier_code", "sku", "quantity", "amount", "invoice_number"),
    "credits": ("supplier_code", "credit_date", "amount", "credit_reference"),
    "baselines": ("agreement_reference", "period_start", "period_end", "value"),
    "allocations": (
        "credit_reference",
        "supplier_code",
        "agreement_reference",
        "period_start",
        "period_end",
        "amount",
    ),
}


def _file_format(raw: Any, kind: str) -> FileFormat:
    path = f"$.{kind}"
    if not isinstance(raw, dict):
        raise AgreementFormatError(path, "must be a mapping")
    columns = raw.get("columns")
    if not isinstance(columns, dict):
        raise AgreementFormatError(f"{path}.columns", "must map field names to CSV headers")
    for name in REQUIRED[kind]:
        if name not in columns:
            raise AgreementFormatError(f"{path}.columns", f"'{name}' is required")
    if "date_format" not in raw:
        raise AgreementFormatError(path, "'date_format' is required (dates are never guessed)")
    sign = raw.get("credit_sign", "positive")
    if sign not in {"positive", "negative"}:
        raise AgreementFormatError(f"{path}.credit_sign", "must be positive or negative")
    try:
        number = NumberFormat(
            decimal_separator=str(raw.get("decimal_separator", ".")),
            thousands_separator=str(raw.get("thousands_separator", ",")),
            negative_style=NegativeStyle(raw.get("negative_style", "minus")),
            currency_symbols=tuple(raw.get("currency_symbols", ["$"])),
        )
    except ValueError as exc:
        raise AgreementFormatError(path, str(exc)) from None
    return FileFormat(
        columns={str(k): str(v) for k, v in columns.items()},
        flags={str(k): str(v) for k, v in (raw.get("flags") or {}).items()},
        date_format=str(raw["date_format"]),
        number=number,
        encoding=str(raw.get("encoding", "utf-8-sig")),
        delimiter=str(raw.get("delimiter", ",")),
        credits_negative_in_file=sign == "negative",
    )


def parse_mapping(data: Any) -> MappingConfig:
    if not isinstance(data, dict):
        raise AgreementFormatError("$", "mapping config must be a mapping")
    tol = data.get("tolerance", {}) or {}
    return MappingConfig(
        purchases=_file_format(data.get("purchases"), "purchases"),
        credits=_file_format(data.get("credits"), "credits"),
        baselines=_file_format(data["baselines"], "baselines") if data.get("baselines") else None,
        allocations=_file_format(data["allocations"], "allocations")
        if data.get("allocations")
        else None,
        tolerance=Tolerance(
            decimal_value(tol.get("abs", "1.00"), "$.tolerance.abs"),
            decimal_value(tol.get("pct", "0.005"), "$.tolerance.pct"),
        ),
    )


def _rows(
    path: Path, fmt: FileFormat, kind: str
) -> Iterator[tuple[int, dict[str, str], list[RowIssue]]]:
    with path.open("r", encoding=fmt.encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=fmt.delimiter)
        header = [clean_text(h) for h in next(reader, [])]
        missing = [h for h in fmt.columns.values() if h not in header]
        missing += [h for h in fmt.flags.values() if h not in header]
        if missing:
            raise AgreementFormatError(
                str(path), f"columns not found in header: {', '.join(missing)}"
            )
        for number, cells in enumerate(reader, start=2):
            if not any(clean_text(c) for c in cells):
                continue  # fully empty rows are dropped (SPEC §4.5.3)
            issues: list[RowIssue] = []
            if len(cells) > len(header):
                issues.append(
                    RowIssue(
                        kind,
                        number,
                        "",
                        "",
                        "RAGGED_ROW",
                        f"row has {len(cells)} cells but the header has {len(header)}",
                    )
                )
                yield number, {}, issues
                continue
            record = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}
            yield number, record, issues


class _RowReader:
    def __init__(
        self,
        kind: str,
        number: int,
        record: dict[str, str],
        fmt: FileFormat,
        issues: list[RowIssue],
    ) -> None:
        self.kind, self.number, self.record, self.fmt, self.issues = (
            kind,
            number,
            record,
            fmt,
            issues,
        )

    def text(self, name: str, required: bool = False) -> str | None:
        header = self.fmt.columns.get(name)
        value = clean_text(self.record.get(header, "")) if header else ""
        if not value:
            if required:
                self.issues.append(
                    RowIssue(
                        self.kind,
                        self.number,
                        header or name,
                        "",
                        "REQUIRED",
                        f"{name} is required",
                    )
                )
            return None
        return value

    def decimal(self, name: str, required: bool = False) -> Decimal | None:
        raw = self.text(name, required)
        if raw is None:
            return None
        try:
            return parse_decimal(raw, self.fmt.number)
        except ParseError as exc:
            self.issues.append(
                RowIssue(self.kind, self.number, self.fmt.columns[name], raw, exc.code, exc.message)
            )
            return None

    def date(self, name: str, required: bool = False) -> date | None:
        raw = self.text(name, required)
        if raw is None:
            return None
        try:
            return parse_date(raw, self.fmt.date_format)
        except ParseError as exc:
            self.issues.append(
                RowIssue(self.kind, self.number, self.fmt.columns[name], raw, exc.code, exc.message)
            )
            return None


def load_purchases(path: Path, cfg: MappingConfig) -> Loaded[PurchaseLine]:
    fmt = cfg.purchases
    out: Loaded[PurchaseLine] = Loaded()
    seen: set[str] = set()
    for number, record, issues in _rows(path, fmt, "purchases"):
        out.rows_read += 1
        if issues:
            out.issues.extend(issues)
            continue
        r = _RowReader("purchases", number, record, fmt, issues)
        supplier = r.text("supplier_code", True)
        invoice = r.text("invoice_number", True)
        line_no = r.text("line_number")
        sku = r.text("sku", True)
        quantity = r.decimal("quantity", True)
        amount = r.decimal("amount", True)
        inv_date = r.date("invoice_date")
        ship = r.date("ship_date")
        receipt = r.date("receipt_date")
        currency = r.text("currency")
        if currency is not None and currency.upper() != "USD":
            issues.append(
                RowIssue(
                    "purchases",
                    number,
                    fmt.columns["currency"],
                    currency,
                    "CURRENCY_NOT_USD",
                    "only USD is supported in v1",
                )
            )
        if not any(r.text(n) for n in ("invoice_date", "ship_date", "receipt_date")):
            issues.append(
                RowIssue(
                    "purchases",
                    number,
                    "",
                    "",
                    "NO_DATE",
                    "row has no invoice, ship or receipt date",
                )
            )
        flags: dict[str, bool] = {}
        for flag, header in fmt.flags.items():
            try:
                value = parse_bool(record.get(header, ""), cfg.true_values, cfg.false_values)
            except ParseError as exc:
                issues.append(
                    RowIssue(
                        "purchases", number, header, record.get(header, ""), exc.code, exc.message
                    )
                )
                continue
            if value is not None:
                flags[flag] = value
        if sku is not None and looks_like_scientific(sku):
            issues.append(
                RowIssue(
                    "purchases",
                    number,
                    fmt.columns["sku"],
                    sku,
                    "SKU_SCIENTIFIC",
                    "SKU looks like Excel scientific notation; the source file may be corrupted",
                    "warning",
                )
            )
        unit_price = r.decimal("unit_price")
        if (
            unit_price is not None
            and quantity is not None
            and amount is not None
            and abs(quantity * unit_price - amount)
            > max(Decimal("0.01"), abs(amount) * Decimal("0.001"))
        ):
            issues.append(
                RowIssue(
                    "purchases",
                    number,
                    fmt.columns["amount"],
                    str(amount),
                    "AMOUNT_MISMATCH",
                    "quantity × unit price differs from the extended amount",
                    "warning",
                )
            )
        out.issues.extend(issues)
        if any(i.severity == "error" for i in issues):
            continue
        assert supplier and invoice and quantity is not None and amount is not None
        if line_no:
            key = f"{supplier}|{invoice}|{line_no}"
        else:
            payload = "|".join(
                [
                    supplier,
                    invoice,
                    sku or "",
                    str(quantity),
                    str(amount),
                    str(inv_date),
                    str(ship),
                    str(receipt),
                    r.text("branch") or "",
                    r.text("category") or "",
                    repr(sorted(flags.items())),
                ]
            )
            key = f"{supplier}|{invoice}|#" + hashlib.sha256(payload.encode()).hexdigest()[:16]
        if key in seen:
            out.duplicates += 1
            out.issues.append(
                RowIssue(
                    "purchases",
                    number,
                    "",
                    key,
                    "DUPLICATE_ROW",
                    "duplicate of an earlier row; skipped",
                    "warning",
                )
            )
            continue
        seen.add(key)
        out.items.append(
            PurchaseLine(
                line_id=key,
                supplier_id=supplier,
                quantity=quantity,
                amount=amount,
                sku=sku,
                invoice_date=inv_date,
                ship_date=ship,
                receipt_date=receipt,
                branch=r.text("branch"),
                category=r.text("category"),
                flags=PurchaseLine.make_flags(flags),
            )
        )
    return out


def load_credits(path: Path, cfg: MappingConfig) -> Loaded[Credit]:
    fmt = cfg.credits
    out: Loaded[Credit] = Loaded()
    seen: set[tuple[str, str]] = set()
    for number, record, issues in _rows(path, fmt, "credits"):
        out.rows_read += 1
        if issues:
            out.issues.extend(issues)
            continue
        r = _RowReader("credits", number, record, fmt, issues)
        supplier = r.text("supplier_code", True)
        credit_date = r.date("credit_date", True)
        amount = r.decimal("amount", True)
        reference = r.text("credit_reference", True)
        p_start, p_end = r.date("period_start"), r.date("period_end")
        currency = r.text("currency")
        if currency is not None and currency.upper() != "USD":
            issues.append(
                RowIssue(
                    "credits",
                    number,
                    fmt.columns["currency"],
                    currency,
                    "CURRENCY_NOT_USD",
                    "only USD is supported in v1",
                )
            )
        out.issues.extend(issues)
        if any(i.severity == "error" for i in issues):
            continue
        assert supplier and credit_date and amount is not None and reference
        if (supplier, reference) in seen:
            out.duplicates += 1
            out.issues.append(
                RowIssue(
                    "credits",
                    number,
                    "",
                    reference,
                    "DUPLICATE_ROW",
                    "duplicate credit reference; skipped",
                    "warning",
                )
            )
            continue
        seen.add((supplier, reference))
        out.items.append(
            Credit(
                credit_id=f"{supplier}|{reference}",
                supplier_id=supplier,
                credit_date=credit_date,
                amount=-amount if fmt.credits_negative_in_file else amount,
                reference=reference,
                agreement_reference=r.text("agreement_reference"),
                period_start=p_start,
                period_end=p_end,
                period_label=r.text("period_label"),
            )
        )
    return out


def load_baselines(
    path: Path, cfg: MappingConfig, agreement_by_ref: Mapping[str, str]
) -> Loaded[Baseline]:
    assert cfg.baselines is not None
    fmt = cfg.baselines
    out: Loaded[Baseline] = Loaded()
    for number, record, issues in _rows(path, fmt, "baselines"):
        out.rows_read += 1
        if issues:
            out.issues.extend(issues)
            continue
        r = _RowReader("baselines", number, record, fmt, issues)
        ref = r.text("agreement_reference", True)
        start, end, value = (
            r.date("period_start", True),
            r.date("period_end", True),
            r.decimal("value", True),
        )
        agreement = agreement_by_ref.get(ref.casefold()) if ref else None
        if ref and agreement is None:
            issues.append(
                RowIssue(
                    "baselines",
                    number,
                    fmt.columns["agreement_reference"],
                    ref,
                    "UNKNOWN_AGREEMENT",
                    "no agreement has this id or external reference",
                )
            )
        out.issues.extend(issues)
        if any(i.severity == "error" for i in issues):
            continue
        assert agreement and start and end and value is not None
        out.items.append(Baseline(agreement, start, end, value, f"baseline-row-{number}"))
    return out


def load_allocations(
    path: Path, cfg: MappingConfig, agreement_by_ref: Mapping[str, str]
) -> Loaded[Allocation]:
    assert cfg.allocations is not None
    fmt = cfg.allocations
    out: Loaded[Allocation] = Loaded()
    for number, record, issues in _rows(path, fmt, "allocations"):
        out.rows_read += 1
        if issues:
            out.issues.extend(issues)
            continue
        r = _RowReader("allocations", number, record, fmt, issues)
        credit_ref, supplier = r.text("credit_reference", True), r.text("supplier_code", True)
        ref = r.text("agreement_reference", True)
        start, end, amount = (
            r.date("period_start", True),
            r.date("period_end", True),
            r.decimal("amount", True),
        )
        agreement = agreement_by_ref.get(ref.casefold()) if ref else None
        if ref and agreement is None:
            issues.append(
                RowIssue(
                    "allocations",
                    number,
                    fmt.columns["agreement_reference"],
                    ref,
                    "UNKNOWN_AGREEMENT",
                    "no agreement has this id or external reference",
                )
            )
        out.issues.extend(issues)
        if any(i.severity == "error" for i in issues):
            continue
        assert credit_ref and supplier and agreement and start and end and amount is not None
        out.items.append(
            Allocation(f"{supplier}|{credit_ref}", agreement, start, end, amount, "manual")
        )
    return out
