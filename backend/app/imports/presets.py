"""ERP report presets for imports (v1.1 Phase 12, ADR 0017 §5).

A preset is a read-only, best-guess description of a common ERP report: which header names
each import field usually has, and the number/date formats the report usually uses.

UNVERIFIED: no public vendor documentation of these report layouts was found (search of
2026-11-13) and every ERP lets users customise report columns. Presets are therefore only
ever *suggested*; the user confirms the mapping, and each preset is shown as unverified
until a real customer export confirms it (then set ``verified=True`` with a note).

Matching is by normalised header text (case, spaces and punctuation ignored).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.db.models.business import ImportType
from app.imports import fields

US_FORMATS: dict[str, Any] = {
    "date_format": "MM/DD/YYYY",
    "decimal_separator": ".",
    "thousands_separator": ",",
}


@dataclass(frozen=True)
class Preset:
    id: str
    erp: str
    report: str
    import_type: ImportType
    #: field name → accepted header names; the first one is the canonical header.
    columns: dict[str, tuple[str, ...]]
    #: headers that must all be present before this preset is suggested (distinctive names).
    signature: tuple[str, ...]
    config: dict[str, Any] = field(default_factory=lambda: dict(US_FORMATS))
    verified: bool = False
    notes: str = ""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


PRESETS: tuple[Preset, ...] = (
    # ------------------------------------------------------------------ purchases
    Preset(
        id="p21-purchases",
        erp="Epicor Prophet 21",
        report="PO receipt / purchase history export",
        import_type=ImportType.PURCHASES,
        signature=("Supplier ID", "Item ID"),
        columns={
            "supplier_code": ("Supplier ID", "Vendor ID"),
            "invoice_number": ("Vendor Invoice No", "Invoice No", "Voucher No", "Receipt No"),
            "line_number": ("Line No", "PO Line No"),
            "sku": ("Item ID",),
            "quantity": ("Qty Received", "Quantity Received", "Qty"),
            "unit_price": ("Unit Cost", "Unit Price"),
            "amount": ("Extended Cost", "Ext Cost", "Extended Price"),
            "invoice_date": ("Invoice Date",),
            "receipt_date": ("Date Received", "Receipt Date", "Received Date"),
            "branch": ("Location ID", "Branch ID", "Location"),
            "category": ("Product Group ID", "Product Group"),
            "description": ("Item Desc", "Item Description"),
        },
    ),
    Preset(
        id="eclipse-purchases",
        erp="Epicor Eclipse",
        report="Purchase order receiving history export",
        import_type=ImportType.PURCHASES,
        signature=("Product #", "Price Line"),
        columns={
            "supplier_code": ("Vendor #", "Vendor Number", "Pay-To Vendor"),
            "invoice_number": ("Invoice #", "Vendor Invoice #", "PO #"),
            "sku": ("Product #", "Product ID"),
            "quantity": ("Qty Rcvd", "Received Qty", "Qty"),
            "unit_price": ("Unit Cost", "Cost"),
            "amount": ("Ext Cost", "Extended Cost", "Ext Amount"),
            "invoice_date": ("Invoice Date",),
            "receipt_date": ("Rcvd Date", "Received Date", "Receive Date"),
            "branch": ("Branch", "Ship Branch"),
            "category": ("Price Line",),
            "description": ("Description", "Product Description"),
        },
    ),
    Preset(
        id="infor-csd-purchases",
        erp="Infor CloudSuite Distribution (SX.e)",
        report="PO line / receipt export (table field names)",
        import_type=ImportType.PURCHASES,
        signature=("vendno", "prod"),
        columns={
            "supplier_code": ("vendno",),
            "invoice_number": ("apinvno", "invno", "pono"),
            "line_number": ("lineno",),
            "sku": ("prod",),
            "quantity": ("qtyrcv", "qtyrcvd", "qty"),
            "unit_price": ("price", "prccost"),
            "amount": ("netamt", "netrcv", "extcost"),
            "invoice_date": ("invdt", "apinvdt"),
            "receipt_date": ("receiptdt", "rcvdt"),
            "branch": ("whse",),
            "category": ("prodcat", "prodline"),
            "description": ("descrip", "proddesc"),
        },
    ),
    Preset(
        id="netsuite-purchases",
        erp="NetSuite",
        report="Transaction saved search (bills, item lines)",
        import_type=ImportType.PURCHASES,
        signature=("Document Number", "Name", "Item"),
        columns={
            "supplier_code": ("Name", "Vendor"),
            "invoice_number": ("Document Number", "Reference No."),
            "line_number": ("Line ID", "Line Sequence Number"),
            "sku": ("Item",),
            "quantity": ("Quantity",),
            "unit_price": ("Item Rate", "Rate"),
            "amount": ("Amount", "Amount (Net)"),
            "invoice_date": ("Date",),
            "branch": ("Location", "Subsidiary"),
            "category": ("Class",),
            "description": ("Memo", "Description"),
        },
        notes="The vendor column usually holds vendor names: add them as supplier aliases.",
    ),
    Preset(
        id="acumatica-purchases",
        erp="Acumatica",
        report="Purchase receipt or AP bill details (generic inquiry export)",
        import_type=ImportType.PURCHASES,
        signature=("Inventory ID", "Vendor"),
        columns={
            "supplier_code": ("Vendor", "Vendor ID"),
            "invoice_number": ("Vendor Ref.", "Reference Nbr.", "Receipt Nbr."),
            "line_number": ("Line Nbr.",),
            "sku": ("Inventory ID",),
            "quantity": ("Receipt Qty.", "Quantity", "Qty."),
            "unit_price": ("Unit Cost",),
            "amount": ("Ext. Cost", "Amount"),
            "invoice_date": ("Date", "Doc. Date"),
            "branch": ("Branch", "Warehouse"),
            "category": ("Item Class",),
            "description": ("Description", "Transaction Descr."),
        },
    ),
    Preset(
        id="qbo-purchases",
        erp="QuickBooks Online",
        report="Purchases by Product/Service Detail (customised to show vendor)",
        import_type=ImportType.PURCHASES,
        signature=("Product/Service", "Vendor"),
        columns={
            "supplier_code": ("Vendor",),
            "invoice_number": ("Num", "No."),
            "sku": ("Product/Service",),
            "quantity": ("Qty", "Quantity"),
            "unit_price": ("Rate",),
            "amount": ("Amount",),
            "invoice_date": ("Date", "Transaction Date"),
            "branch": ("Location",),
            "category": ("Class", "Category"),
            "description": ("Memo/Description", "Description"),
        },
        notes="QuickBooks vendors are names: add them as supplier aliases.",
    ),
    Preset(
        id="qbd-purchases",
        erp="QuickBooks Desktop",
        report="Purchases by Item Detail (exported flat, item as a column)",
        import_type=ImportType.PURCHASES,
        signature=("Source Name", "Cost Price"),
        columns={
            "supplier_code": ("Source Name", "Name"),
            "invoice_number": ("Num",),
            "sku": ("Item",),
            "quantity": ("Qty",),
            "unit_price": ("Cost Price",),
            "amount": ("Amount",),
            "invoice_date": ("Date",),
            "branch": ("Class",),
            "description": ("Memo",),
        },
        notes="Export without item subtotal rows so the item is a column on every line.",
    ),
    # ------------------------------------------------------------------ credits
    Preset(
        id="netsuite-credits",
        erp="NetSuite",
        report="Vendor credit saved search",
        import_type=ImportType.CREDITS,
        signature=("Document Number", "Name", "Type"),
        columns={
            "supplier_code": ("Name", "Vendor"),
            "credit_date": ("Date",),
            "amount": ("Amount", "Amount (Net)"),
            "credit_reference": ("Document Number", "Reference No."),
            "memo": ("Memo",),
        },
    ),
    Preset(
        id="acumatica-credits",
        erp="Acumatica",
        report="AP debit adjustments (generic inquiry export)",
        import_type=ImportType.CREDITS,
        signature=("Reference Nbr.", "Vendor"),
        columns={
            "supplier_code": ("Vendor", "Vendor ID"),
            "credit_date": ("Date", "Doc. Date"),
            "amount": ("Amount", "Orig. Amount"),
            "credit_reference": ("Reference Nbr.", "Vendor Ref."),
            "memo": ("Description",),
        },
    ),
    Preset(
        id="qbo-credits",
        erp="QuickBooks Online",
        report="Transaction List by Vendor (vendor credits)",
        import_type=ImportType.CREDITS,
        signature=("Transaction Type", "Vendor"),
        columns={
            "supplier_code": ("Vendor",),
            "credit_date": ("Date", "Transaction Date"),
            "amount": ("Amount",),
            "credit_reference": ("Num", "No."),
            "memo": ("Memo/Description", "Description"),
        },
    ),
    Preset(
        id="qbd-credits",
        erp="QuickBooks Desktop",
        report="Vendor Transaction List (credits)",
        import_type=ImportType.CREDITS,
        signature=("Type", "Num", "Name"),
        columns={
            "supplier_code": ("Name", "Source Name"),
            "credit_date": ("Date",),
            "amount": ("Amount",),
            "credit_reference": ("Num",),
            "memo": ("Memo",),
        },
    ),
)

_BY_ID = {p.id: p for p in PRESETS}


def get(preset_id: str) -> Preset | None:
    return _BY_ID.get(preset_id)


def for_type(import_type: ImportType | None) -> list[Preset]:
    return [p for p in PRESETS if import_type is None or p.import_type == import_type]


def resolve(preset: Preset, header: list[str]) -> dict[str, str]:
    """Field → the file's own header text, for every preset field found (each header used once)."""
    by_norm: dict[str, str] = {}
    for h in header:
        if h and _norm(h) not in by_norm:
            by_norm[_norm(h)] = h
    used: set[str] = set()
    out: dict[str, str] = {}
    for name, aliases in preset.columns.items():
        for alias in aliases:
            found = by_norm.get(_norm(alias))
            if found is not None and found not in used:
                out[name] = found
                used.add(found)
                break
    return out


def missing_required(preset: Preset, resolved: dict[str, str]) -> list[str]:
    return [
        f.name for f in fields.FIELDS[preset.import_type] if f.required and f.name not in resolved
    ]


def suggest(import_type: ImportType, header: list[str]) -> Preset | None:
    """The one preset whose signature is present and whose required fields all resolve.

    Returns None when nothing fits or when two presets fit equally well: we never guess
    between ERPs.
    """
    present = {_norm(h) for h in header if h}
    scored: list[tuple[int, Preset]] = []
    for p in for_type(import_type):
        if not all(_norm(s) in present for s in p.signature):
            continue
        resolved = resolve(p, header)
        if missing_required(p, resolved):
            continue
        scored.append((len(p.signature) * 100 + len(resolved), p))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def template_config(preset: Preset) -> dict[str, Any]:
    """Saved-template config using each field's canonical header."""
    return {**preset.config, "columns": {k: v[0] for k, v in preset.columns.items()}}
