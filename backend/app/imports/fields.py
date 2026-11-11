"""Import field definitions per type (SPEC §4.5.1) and header auto-suggestion."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.db.models.business import ImportType


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    required: bool
    kind: str  # text | decimal | date | code
    synonyms: tuple[str, ...] = ()


def _f(name: str, label: str, required: bool, kind: str, *syn: str) -> FieldSpec:
    return FieldSpec(name, label, required, kind, syn)


FIELDS: dict[ImportType, tuple[FieldSpec, ...]] = {
    ImportType.PURCHASES: (
        _f(
            "supplier_code",
            "Supplier code",
            True,
            "code",
            "vendor",
            "vendor no",
            "vendor number",
            "vendor code",
            "supplier",
            "supplier no",
            "mfr",
            "manufacturer",
        ),
        _f(
            "invoice_number",
            "Invoice number",
            True,
            "text",
            "invoice",
            "invoice no",
            "inv no",
            "invoice #",
            "doc no",
            "document number",
        ),
        _f("line_number", "Line number", False, "text", "line", "line no", "line #", "seq"),
        _f(
            "sku",
            "SKU",
            True,
            "text",
            "item",
            "item no",
            "item number",
            "part",
            "part number",
            "product",
            "sku",
        ),
        _f("quantity", "Quantity", True, "decimal", "qty", "quantity", "units", "qty shipped"),
        _f(
            "unit_price", "Unit price", False, "decimal", "unit cost", "price", "unit price", "cost"
        ),
        _f(
            "amount",
            "Extended amount",
            True,
            "decimal",
            "ext cost",
            "extended",
            "extended cost",
            "ext amount",
            "amount",
            "line total",
            "net amount",
        ),
        _f("invoice_date", "Invoice date", False, "date", "invoice date", "inv date", "date"),
        _f("ship_date", "Ship date", False, "date", "ship date", "shipped", "ship dt"),
        _f(
            "receipt_date",
            "Receipt date",
            False,
            "date",
            "receipt date",
            "received",
            "receive date",
        ),
        _f("branch", "Branch", False, "text", "branch", "location", "warehouse", "store"),
        _f(
            "category",
            "Category",
            False,
            "text",
            "category",
            "product class",
            "class",
            "product category",
        ),
        _f("description", "Description", False, "text", "description", "desc", "item description"),
        _f("currency", "Currency", False, "text", "currency", "curr"),
    ),
    ImportType.CREDITS: (
        _f("supplier_code", "Supplier code", True, "code", "vendor", "vendor no", "supplier"),
        _f("credit_date", "Credit date", True, "date", "credit date", "memo date", "date"),
        _f("amount", "Amount", True, "decimal", "amount", "credit amount", "total"),
        _f(
            "credit_reference",
            "Credit reference",
            True,
            "text",
            "credit memo",
            "reference",
            "credit no",
            "memo no",
            "document number",
        ),
        _f("memo", "Memo", False, "text", "memo", "description", "notes"),
        _f(
            "agreement_reference",
            "Agreement reference",
            False,
            "text",
            "program",
            "agreement",
            "program id",
            "rebate program",
        ),
        _f("period_start", "Period start", False, "date", "period from", "from", "period start"),
        _f("period_end", "Period end", False, "date", "period to", "to", "period end"),
        _f("period_label", "Period label", False, "text", "period", "quarter"),
        _f("currency", "Currency", False, "text", "currency"),
    ),
    ImportType.BASELINES: (
        _f("agreement_reference", "Agreement reference", False, "text", "program", "agreement"),
        _f("supplier_code", "Supplier code", False, "code", "vendor", "supplier"),
        _f("period_start", "Period start", True, "date", "from", "period start"),
        _f("period_end", "Period end", True, "date", "to", "period end"),
        _f("value", "Baseline measure", True, "decimal", "baseline", "baseline spend", "value"),
        _f("notes", "Notes", False, "text", "notes"),
    ),
    ImportType.PRODUCTS: (
        _f("sku", "SKU", True, "text", "item", "sku", "item no", "part number"),
        _f("category", "Category", True, "text", "category", "product class", "class"),
        _f("description", "Description", False, "text", "description", "desc"),
        _f("supplier_code", "Supplier code", False, "code", "vendor", "supplier"),
    ),
    ImportType.SUPPLIERS: (
        _f("name", "Supplier name", True, "text", "name", "supplier name", "vendor name"),
        _f("supplier_code", "Supplier code", True, "code", "code", "vendor no", "supplier code"),
        _f("tags", "Category tags", False, "text", "tags", "category"),
        _f("contact_name", "Contact name", False, "text", "contact", "contact name"),
        _f("contact_email", "Contact email", False, "text", "email", "contact email"),
        _f("contact_phone", "Contact phone", False, "text", "phone"),
    ),
}

FLAG_TYPES = {ImportType.PURCHASES}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def suggest(import_type: ImportType, header: list[str]) -> dict[str, str]:
    """Map fields to headers by exact field name, label or synonym (first match wins)."""
    normalized = {_norm(h): h for h in header if h}
    used: set[str] = set()
    out: dict[str, str] = {}
    for spec in FIELDS[import_type]:
        for cand in (spec.name.replace("_", " "), spec.label, *spec.synonyms):
            h = normalized.get(_norm(cand))
            if h and h not in used:
                out[spec.name] = h
                used.add(h)
                break
    return out


def spec(import_type: ImportType, name: str) -> FieldSpec | None:
    return next((f for f in FIELDS[import_type] if f.name == name), None)
