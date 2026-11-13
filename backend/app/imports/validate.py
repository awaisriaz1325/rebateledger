"""Row-level validation and normalisation (SPEC §4.5.3). Pure: no DB access."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.db.models.business import ImportType
from app.imports.fields import FIELDS
from app.imports.parsing import (
    DEFAULT_FALSE,
    DEFAULT_TRUE,
    NegativeStyle,
    NumberFormat,
    ParseError,
    check_date_window,
    clean_text,
    looks_like_scientific,
    parse_bool,
    parse_date,
    parse_decimal,
)

MAX_VALUE_SHOWN = 120


@dataclass(frozen=True)
class Issue:
    row: int
    column: str
    value: str
    code: str
    message: str
    severity: str = "error"


@dataclass
class RowResult:
    row: int
    record: dict[str, Any] | None
    issues: list[Issue] = field(default_factory=list)
    unknown_code: str | None = None

    @property
    def ok(self) -> bool:
        return self.record is not None and not any(i.severity == "error" for i in self.issues)


@dataclass(frozen=True)
class Context:
    import_type: ImportType
    header: list[str]
    config: dict[str, Any]
    supplier_codes: dict[str, uuid.UUID]
    today: date
    agreements_by_ref: dict[str, uuid.UUID] = field(default_factory=dict)
    agreements_by_supplier: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)
    buying_groups: frozenset[uuid.UUID] = frozenset()

    def number_format(self) -> NumberFormat:
        c = self.config
        return NumberFormat(
            decimal_separator=c.get("decimal_separator", "."),
            thousands_separator=c.get("thousands_separator", ","),
            negative_style=NegativeStyle(c.get("negative_style", "minus")),
            currency_symbols=tuple(c.get("currency_symbols", ["$"])),
        )


class RowValidator:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.index = {h: i for i, h in enumerate(ctx.header) if h}
        self.columns: dict[str, str] = dict(ctx.config.get("columns", {}))
        self.flags: dict[str, str] = dict(ctx.config.get("flags", {}))
        self.fmt = ctx.number_format()
        self.date_format: str = ctx.config.get("date_format", "")
        self.credits_negative = ctx.config.get("credit_sign") == "negative"
        self.true_values = frozenset(v.upper() for v in ctx.config.get("true_values", DEFAULT_TRUE))
        self.false_values = frozenset(
            v.upper() for v in ctx.config.get("false_values", DEFAULT_FALSE)
        )

    def config_problems(self) -> list[str]:
        out = []
        specs = FIELDS[self.ctx.import_type]
        for spec in specs:
            if spec.required and spec.name not in self.columns:
                out.append(f"Map a column to “{spec.label}”.")
        for name, header in [*self.columns.items(), *self.flags.items()]:
            if header not in self.index:
                out.append(f"Column “{header}” (for {name}) is not in the header row.")
        known = {s.name for s in specs}
        out.extend(f"Unknown field {name}." for name in self.columns if name not in known)
        if any(s.kind == "date" and s.name in self.columns for s in specs) and not self.date_format:
            out.append("Choose the date format (dates are never guessed).")
        if self.ctx.import_type is ImportType.PURCHASES and not any(
            n in self.columns for n in ("invoice_date", "ship_date", "receipt_date")
        ):
            out.append("Map at least one date column (invoice, ship or receipt date).")
        if self.ctx.import_type is ImportType.BASELINES and not (
            {"agreement_reference", "supplier_code"} & set(self.columns)
        ):
            out.append("Map an agreement reference or a supplier code.")
        return out

    # ------------------------------------------------------------------ cells

    def _raw(self, cells: list[str], name: str) -> str:
        header = self.columns.get(name)
        if header is None:
            return ""
        i = self.index[header]
        return clean_text(cells[i]) if i < len(cells) else ""

    def _issue(
        self, r: RowResult, name: str, raw: str, code: str, message: str, severity: str = "error"
    ) -> None:
        r.issues.append(
            Issue(
                r.row, self.columns.get(name, name), raw[:MAX_VALUE_SHOWN], code, message, severity
            )
        )

    def _text(
        self, r: RowResult, cells: list[str], name: str, required: bool, max_len: int = 100
    ) -> str | None:
        raw = self._raw(cells, name)
        if not raw:
            if required:
                self._issue(r, name, raw, "REQUIRED", "Value is required.")
            return None
        if len(raw) > max_len:
            self._issue(r, name, raw, "TOO_LONG", f"At most {max_len} characters.")
            return None
        return raw

    def _decimal(self, r: RowResult, cells: list[str], name: str, required: bool) -> Decimal | None:
        raw = self._raw(cells, name)
        if not raw:
            if required:
                self._issue(r, name, raw, "REQUIRED", "Value is required.")
            return None
        try:
            value = parse_decimal(raw, self.fmt)
        except ParseError as exc:
            self._issue(r, name, raw, exc.code, exc.message)
            return None
        if abs(value) >= Decimal("1e14"):
            self._issue(r, name, raw, "TOO_LARGE", "Value is too large.")
            return None
        return value

    def _date(self, r: RowResult, cells: list[str], name: str, required: bool) -> date | None:
        raw = self._raw(cells, name)
        if not raw:
            if required:
                self._issue(r, name, raw, "REQUIRED", "Value is required.")
            return None
        try:
            d = parse_date(raw, self.date_format)
            check_date_window(d, self.ctx.today)
            return d
        except ParseError as exc:
            self._issue(r, name, raw, exc.code, exc.message)
            return None

    def _currency(self, r: RowResult, cells: list[str]) -> None:
        raw = self._raw(cells, "currency")
        if raw and raw.upper() != "USD":
            self._issue(r, "currency", raw, "CURRENCY_NOT_USD", "Only USD is supported in v1.")

    def _supplier(self, r: RowResult, cells: list[str], required: bool = True) -> uuid.UUID | None:
        raw = self._raw(cells, "supplier_code")
        if not raw:
            if required:
                self._issue(r, "supplier_code", raw, "REQUIRED", "Supplier code is required.")
            return None
        code = raw.upper()
        sid = self.ctx.supplier_codes.get(code)
        if sid is None:
            r.unknown_code = code
            self._issue(
                r,
                "supplier_code",
                raw,
                "UNKNOWN_SUPPLIER",
                "Supplier code is not mapped to a supplier.",
            )
        elif (
            self.ctx.import_type in (ImportType.PURCHASES, ImportType.SALES)
            and sid in self.ctx.buying_groups
        ):
            self._issue(
                r,
                "supplier_code",
                raw,
                "SUPPLIER_IS_BUYING_GROUP",
                "This code belongs to a buying group. Import purchases under the member supplier.",
            )
            return None
        return sid

    # ------------------------------------------------------------------ rows

    def validate(self, row: int, cells: list[str]) -> RowResult:
        r = RowResult(row, None)
        if len(cells) > len(self.ctx.header) and any(
            clean_text(c) for c in cells[len(self.ctx.header) :]
        ):
            r.issues.append(
                Issue(
                    row,
                    "",
                    "",
                    "RAGGED_ROW",
                    f"Row has {len(cells)} cells but the header has {len(self.ctx.header)}. Values were not shifted.",
                )
            )
            return r
        method = getattr(self, f"_row_{self.ctx.import_type.value}")
        record = method(r, cells)
        if not any(i.severity == "error" for i in r.issues):
            r.record = record
        return r

    def _row_purchases(self, r: RowResult, cells: list[str]) -> dict[str, Any]:
        supplier = self._supplier(r, cells)
        invoice = self._text(r, cells, "invoice_number", True)
        line_no = self._text(r, cells, "line_number", False, 50)
        sku = self._text(r, cells, "sku", True)
        qty = self._decimal(r, cells, "quantity", True)
        price = self._decimal(r, cells, "unit_price", False)
        amount = self._decimal(r, cells, "amount", True)
        dates = {
            n: self._date(r, cells, n, False) for n in ("invoice_date", "ship_date", "receipt_date")
        }
        if not any(self._raw(cells, n) for n in dates):
            r.issues.append(
                Issue(r.row, "", "", "NO_DATE", "The row has no invoice, ship or receipt date.")
            )
        self._currency(r, cells)
        flags: dict[str, bool] = {}
        for flag, header in self.flags.items():
            raw = clean_text(cells[self.index[header]]) if self.index[header] < len(cells) else ""
            try:
                value = parse_bool(raw, self.true_values, self.false_values)
            except ParseError as exc:
                r.issues.append(Issue(r.row, header, raw[:MAX_VALUE_SHOWN], exc.code, exc.message))
                continue
            if value is not None:
                flags[flag] = value
        if sku and looks_like_scientific(sku):
            self._issue(
                r,
                "sku",
                sku,
                "SKU_SCIENTIFIC",
                "Looks like Excel scientific notation; the source file may have been corrupted by Excel.",
                "warning",
            )
        if (
            qty is not None
            and price is not None
            and amount is not None
            and abs(qty * price - amount) > max(Decimal("0.01"), abs(amount) * Decimal("0.001"))
        ):
            self._issue(
                r,
                "amount",
                str(amount),
                "AMOUNT_MISMATCH",
                "Quantity × unit price differs from the extended amount.",
                "warning",
            )
        is_return = (qty is not None and qty < 0) or (amount is not None and amount < 0)
        if is_return:
            self._issue(
                r,
                "amount",
                str(amount),
                "RETURN_LINE",
                "Negative line treated as a return.",
                "info",
            )
        branch = self._text(r, cells, "branch", False)
        category = self._text(r, cells, "category", False)
        description = self._text(r, cells, "description", False, 300) or ""
        if line_no:
            key_src = f"L|{invoice}|{line_no}"
        else:
            key_src = "H|" + "|".join(
                str(x)
                for x in (
                    invoice,
                    sku,
                    qty,
                    price,
                    amount,
                    dates["invoice_date"],
                    dates["ship_date"],
                    dates["receipt_date"],
                    branch,
                    category,
                    sorted(flags.items()),
                )
            )
        return {
            "supplier_id": supplier,
            "invoice_number": invoice,
            "line_number": line_no,
            "sku": sku,
            "description": description,
            "quantity": qty,
            "unit_price": price,
            "amount": amount,
            **dates,
            "branch": branch,
            "category": category,
            "flags": flags,
            "is_return": is_return,
            "dedupe_key": hashlib.sha256(key_src.encode()).digest(),
        }

    def _row_sales(self, r: RowResult, cells: list[str]) -> dict[str, Any]:
        supplier = self._supplier(r, cells)
        invoice = self._text(r, cells, "invoice_number", True)
        line_no = self._text(r, cells, "line_number", False, 50)
        invoice_date = self._date(r, cells, "invoice_date", True)
        customer = self._text(r, cells, "customer", False, 200)
        job = self._text(r, cells, "job", False, 200)
        sku = self._text(r, cells, "sku", True)
        qty = self._decimal(r, cells, "quantity", True)
        cost = self._decimal(r, cells, "unit_cost", False)
        price = self._decimal(r, cells, "sell_price", False)
        if sku and looks_like_scientific(sku):
            self._issue(
                r,
                "sku",
                sku,
                "SKU_SCIENTIFIC",
                "Looks like Excel scientific notation; the source file may have been corrupted by Excel.",
                "warning",
            )
        key_src = (
            f"L|{invoice}|{line_no}"
            if line_no
            else "H|"
            + "|".join(
                str(x) for x in (invoice, invoice_date, customer, job, sku, qty, cost, price)
            )
        )
        return {
            "supplier_id": supplier,
            "invoice_number": invoice,
            "line_number": line_no,
            "invoice_date": invoice_date,
            "customer": customer,
            "job": job,
            "sku": sku,
            "quantity": qty,
            "unit_cost": cost,
            "sell_price": price,
            "dedupe_key": hashlib.sha256(key_src.encode()).digest(),
        }

    def _row_credits(self, r: RowResult, cells: list[str]) -> dict[str, Any]:
        supplier = self._supplier(r, cells)
        credit_date = self._date(r, cells, "credit_date", True)
        amount = self._decimal(r, cells, "amount", True)
        ref = self._text(r, cells, "credit_reference", True)
        p_start = self._date(r, cells, "period_start", False)
        p_end = self._date(r, cells, "period_end", False)
        if p_start and p_end and p_end < p_start:
            self._issue(
                r, "period_end", str(p_end), "PERIOD_INVALID", "Period end is before period start."
            )
        self._currency(r, cells)
        if amount is not None and self.credits_negative:
            amount = -amount
        if amount is not None and amount < 0:
            self._issue(
                r,
                "amount",
                str(amount),
                "CREDIT_REVERSAL",
                "Negative credit treated as a reversal.",
                "info",
            )
        return {
            "supplier_id": supplier,
            "credit_date": credit_date,
            "amount": amount,
            "credit_reference": ref,
            "memo": self._text(r, cells, "memo", False, 500) or "",
            "agreement_reference": self._text(r, cells, "agreement_reference", False),
            "period_start": p_start,
            "period_end": p_end,
            "period_label": self._text(r, cells, "period_label", False, 40),
        }

    def _row_baselines(self, r: RowResult, cells: list[str]) -> dict[str, Any]:
        ref = self._text(r, cells, "agreement_reference", False)
        agreement: uuid.UUID | None = None
        if ref:
            agreement = self.ctx.agreements_by_ref.get(ref.lower())
            if agreement is None:
                self._issue(
                    r,
                    "agreement_reference",
                    ref,
                    "UNKNOWN_AGREEMENT",
                    "No agreement has this external reference.",
                )
        else:
            supplier = self._supplier(r, cells, required=True)
            if supplier is not None:
                options = self.ctx.agreements_by_supplier.get(supplier, [])
                if len(options) == 1:
                    agreement = options[0]
                else:
                    self._issue(
                        r,
                        "supplier_code",
                        self._raw(cells, "supplier_code"),
                        "AGREEMENT_AMBIGUOUS",
                        "The supplier has no agreement or several; use an agreement reference.",
                    )
        start = self._date(r, cells, "period_start", True)
        end = self._date(r, cells, "period_end", True)
        if start and end and end < start:
            self._issue(
                r, "period_end", str(end), "PERIOD_INVALID", "Period end is before period start."
            )
        value = self._decimal(r, cells, "value", True)
        return {
            "agreement_id": agreement,
            "period_start": start,
            "period_end": end,
            "value": value,
            "notes": self._text(r, cells, "notes", False, 500) or "",
        }

    def _row_products(self, r: RowResult, cells: list[str]) -> dict[str, Any]:
        sku = self._text(r, cells, "sku", True)
        if sku and looks_like_scientific(sku):
            self._issue(
                r, "sku", sku, "SKU_SCIENTIFIC", "Looks like Excel scientific notation.", "warning"
            )
        supplier = (
            self._supplier(r, cells, required=False) if self._raw(cells, "supplier_code") else None
        )
        return {
            "sku": sku,
            "category": self._text(r, cells, "category", True),
            "description": self._text(r, cells, "description", False, 500) or "",
            "supplier_id": supplier,
        }

    def _row_suppliers(self, r: RowResult, cells: list[str]) -> dict[str, Any]:
        name = self._text(r, cells, "name", True, 200)
        code = self._text(r, cells, "supplier_code", True)
        tags = [
            t.strip()
            for t in (self._text(r, cells, "tags", False, 500) or "").split(",")
            if t.strip()
        ]
        return {
            "name": name,
            "code": code.upper() if code else None,
            "tags": tags[:20],
            "contact_name": self._text(r, cells, "contact_name", False, 200),
            "contact_email": self._text(r, cells, "contact_email", False, 254),
            "contact_phone": self._text(r, cells, "contact_phone", False, 50),
        }
