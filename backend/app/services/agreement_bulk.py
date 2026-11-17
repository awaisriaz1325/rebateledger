"""Bulk agreement import from CSV (v1.2 Phase 21).

One row per tier (or one row per component without tiers). Rows sharing ``agreement_ref`` form
one agreement; rows sharing ``component_key`` inside it form one component. Every row is checked
with the same schema (``VersionTermsIn``) and engine validation as the editor, so there is no
second rulebook. Results are always **drafts**; activation stays the normal reviewed flow.

Commit is all-or-nothing: any error in the file means nothing is created.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models.business import Agreement, Supplier, VersionStatus
from app.engine.models import (
    BaselineSource,
    ComponentType,
    DateBasis,
    Measure,
    NegativeResult,
    PeriodType,
    PriorPeriodOffset,
    RoundingMode,
    SpendBasis,
    Stacking,
    ThresholdComparison,
    ZeroBaselinePolicy,
)
from app.imports.parsing import ParseError, parse_date
from app.services import agreements, suppliers
from app.services.agreement_terms import (
    VersionTermsIn,
    summarize,
    terms_from_rows,
    to_snapshot,
    warnings_for,
)
from app.services.audit import record

MAX_BYTES = 1024 * 1024
MAX_ROWS = 2000
MAX_AGREEMENTS = 500

RATE, MONEY, INT, BOOL, DATE, TEXT = "rate", "money", "int", "bool", "date", "text"


@dataclass(frozen=True)
class Column:
    name: str
    level: str  # agreement | version | component | tier
    kind: str
    required: bool
    help: str
    allowed: tuple[str, ...] = ()


def _enum(e: type[StrEnum]) -> tuple[str, ...]:
    return tuple(m.value for m in e)


_PERIODS = tuple(p for p in _enum(PeriodType) if p != PeriodType.CUSTOM.value)

COLUMNS: tuple[Column, ...] = (
    Column("agreement_ref", "agreement", TEXT, True, "Your unique reference for the agreement. Rows with the same reference form one agreement; re-importing it adds a new draft version."),
    Column("agreement_name", "agreement", TEXT, True, "Agreement name."),
    Column("supplier", "agreement", TEXT, True, "Supplier code or exact supplier name, as set up under Suppliers."),
    Column("notes", "agreement", TEXT, False, "Free text."),
    Column("effective_from", "version", DATE, True, "First day the terms apply (YYYY-MM-DD or MM/DD/YYYY)."),
    Column("effective_to", "version", DATE, False, "Last day the terms apply; empty for open-ended."),
    Column("period_type", "version", TEXT, True, "How often the rebate is calculated. Custom periods are set in the editor.", _PERIODS),
    Column("fiscal_aligned", "version", BOOL, True, "true to align periods with your fiscal year.", ("true", "false")),
    Column("date_basis", "version", TEXT, True, "Which purchase date places a line in a period.", _enum(DateBasis)),
    Column("measure", "version", TEXT, True, "What thresholds and rates apply to.", _enum(Measure)),
    Column("spend_basis", "version", TEXT, True, "Whether returns reduce spend.", _enum(SpendBasis)),
    Column("threshold_comparison", "version", TEXT, True, "gte: reaching a threshold qualifies; gt: it must be exceeded.", _enum(ThresholdComparison)),
    Column("negative_result", "version", TEXT, True, "What happens when a period calculates below zero.", _enum(NegativeResult)),
    Column("rounding_mode", "version", TEXT, True, "Rounding to cents.", _enum(RoundingMode)),
    Column("payment_terms_days", "version", INT, True, "Days after period end the supplier should pay (0–730)."),
    Column("stacking", "version", TEXT, True, "Whether this agreement may pay on the same lines as another.", _enum(Stacking)),
    Column("prorate_thresholds_on_partial_period", "version", BOOL, True, "true to scale thresholds in a partial first or last period.", ("true", "false")),
    Column("zero_baseline_policy", "version", TEXT, True, "Growth components when the baseline is zero.", _enum(ZeroBaselinePolicy)),
    Column("cap_amount", "version", MONEY, False, "Maximum rebate per period."),
    Column("minimum_payout", "version", MONEY, False, "Rebates below this amount are not paid."),
    Column("component_key", "component", TEXT, True, "Short id of the component within the agreement, e.g. base or bonus."),
    Column("component_type", "component", TEXT, True, "Kind of rebate component.", _enum(ComponentType)),
    Column("rate", "component", RATE, False, "Rate as 0.02 or 2%."),
    Column("amount_per_unit", "component", MONEY, False, "Amount per unit, for per_unit components."),
    Column("amount", "component", MONEY, False, "Fixed amount, for fixed_bonus components."),
    Column("threshold", "component", MONEY, False, "Threshold, for fixed_bonus components."),
    Column("growth_pct", "component", RATE, False, "Required growth as 0.05 or 5%, for growth components."),
    Column("baseline_source", "component", TEXT, False, "Where the growth baseline comes from.", _enum(BaselineSource)),
    Column("prior_period_offset", "component", TEXT, False, "Which earlier period is the computed baseline.", _enum(PriorPeriodOffset)),
    Column("tier_threshold", "tier", MONEY, False, "Tier starts at this spend or quantity (tiered components: one row per tier)."),
    Column("tier_rate", "tier", RATE, False, "Tier rate as 0.02 or 2%."),
    Column("tier_amount_per_unit", "tier", MONEY, False, "Tier amount per unit."),
)  # fmt: skip
BY_NAME = {c.name: c for c in COLUMNS}
VERSION_COLS = [c for c in COLUMNS if c.level == "version"]
COMPONENT_COLS = [c for c in COLUMNS if c.level == "component" and c.name != "component_key"]
TIER_COLS = [c for c in COLUMNS if c.level == "tier"]


def template() -> str:
    return ",".join(c.name for c in COLUMNS) + "\r\n"


# --------------------------------------------------------------------------- parsing


class CellError(ValueError):
    pass


_MONEY_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _decimal(text: str) -> Decimal:
    t = text.replace("$", "").replace(",", "").strip()
    if not _MONEY_RE.match(t):
        raise CellError("is not a number")
    try:
        return Decimal(t)
    except InvalidOperation:  # pragma: no cover - the pattern already guarantees a decimal
        raise CellError("is not a number") from None


def _rate(text: str) -> Decimal:
    t = text.strip()
    if t.endswith("%"):
        return _decimal(t[:-1]) / 100
    d = _decimal(t)
    if abs(d) >= 1:  # "2" could mean 2% or 200%: never guess with money
        raise CellError("is ambiguous: write 0.02 or 2%")
    return d


def _date(text: str) -> date:
    for fmt in ("YYYY-MM-DD", "MM/DD/YYYY"):
        try:
            return parse_date(text, fmt)
        except ParseError:
            continue
    raise CellError("is not a date (use YYYY-MM-DD or MM/DD/YYYY)")


def _convert(col: Column, raw: str) -> Any:
    text = raw.strip()
    if text == "":
        return None
    if col.kind == RATE:
        return format(_rate(text), "f")
    if col.kind == MONEY:
        return format(_decimal(text), "f")
    if col.kind == INT:
        if not re.fullmatch(r"\d+", text):
            raise CellError("must be a whole number")
        return int(text)
    if col.kind == BOOL:
        if text.lower() not in ("true", "false"):
            raise CellError("must be true or false")
        return text.lower() == "true"
    if col.kind == DATE:
        return _date(text).isoformat()
    if col.allowed:
        if text.lower() not in col.allowed:
            raise CellError(f"must be one of: {', '.join(col.allowed)}")
        return text.lower()
    return text


@dataclass
class RowError:
    row: int | None
    column: str | None
    message: str


@dataclass
class Item:
    ref: str
    name: str
    supplier_id: uuid.UUID | None
    supplier_name: str
    notes: str
    first_row: int
    terms: VersionTermsIn | None = None
    action: str = "create"  # create | new_version | unchanged
    agreement_id: uuid.UUID | None = None
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
    components: int = 0
    tiers: int = 0


@dataclass
class Plan:
    sha256: str
    items: list[Item]
    errors: list[RowError]


def _read(data: bytes) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    if len(data) > MAX_BYTES:
        raise AppError(
            422, "FILE_TOO_LARGE", "File too large", "Agreement files are limited to 1 MB."
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError(
            422, "FILE_ENCODING", "Unreadable file", "Save the file as CSV (UTF-8)."
        ) from None
    reader = csv.reader(io.StringIO(text))
    header = [h.strip().lower() for h in next(reader, [])]
    rows: list[tuple[int, dict[str, str]]] = []
    for line_no, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        if len(rows) >= MAX_ROWS:
            raise AppError(
                422, "TOO_MANY_ROWS", "Too many rows", f"At most {MAX_ROWS} rows per file."
            )
        rows.append((line_no, dict(zip(header, cells, strict=False))))
    return header, rows


def _supplier_lookup(
    db: Session, tenant_id: uuid.UUID
) -> tuple[dict[str, uuid.UUID], dict[str, list[Supplier]]]:
    codes = suppliers.code_map(db, tenant_id)
    by_name: dict[str, list[Supplier]] = {}
    for s in db.execute(
        select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.merged_into_id.is_(None))
    ).scalars():
        by_name.setdefault(s.name.strip().lower(), []).append(s)
    return codes, by_name


def _pydantic_errors(exc: ValidationError, rows: dict[str, Any]) -> list[RowError]:
    """Map a VersionTermsIn error location back to a CSV row and column."""
    out = []
    for e in exc.errors():
        loc = list(e["loc"])
        row, column = rows["first"], str(loc[0]) if loc else None
        if loc[:1] == ["components"] and len(loc) >= 2 and isinstance(loc[1], int):
            comp = rows["components"][loc[1]]
            row, column = comp["first"], str(loc[2]) if len(loc) > 2 else "component_key"
            if len(loc) >= 4 and loc[2] == "tiers" and isinstance(loc[3], int):
                row = comp["tiers"][loc[3]]
                column = f"tier_{loc[4]}" if len(loc) > 4 else "tier_threshold"
        out.append(RowError(row, column, str(e["msg"])))
    return out


def parse(db: Session, ctx: Any, data: bytes) -> Plan:
    digest = hashlib.sha256(data).hexdigest()
    header, rows = _read(data)
    errors: list[RowError] = []
    unknown = [h for h in header if h and h not in BY_NAME]
    missing = [c.name for c in COLUMNS if c.required and c.name not in header]
    for h in unknown:
        errors.append(RowError(1, h, "Unknown column (check the spelling against the template)."))
    for m in missing:
        errors.append(RowError(1, m, "Required column is missing."))
    if errors:
        return Plan(digest, [], errors)
    if not rows:
        return Plan(digest, [], [RowError(None, None, "The file has no data rows.")])

    # Convert every cell first so each bad cell is reported once, with its row and column.
    parsed: list[tuple[int, dict[str, Any]]] = []
    bad_rows: set[int] = set()
    for line_no, raw in rows:
        values: dict[str, Any] = {}
        for col in COLUMNS:
            try:
                values[col.name] = _convert(col, raw.get(col.name, ""))
            except CellError as exc:
                errors.append(
                    RowError(line_no, col.name, f"“{raw.get(col.name, '').strip()}” {exc}")
                )
                values[col.name] = None
                bad_rows.add(line_no)
                continue
            if col.required and values[col.name] is None:
                errors.append(RowError(line_no, col.name, "Required value is empty."))
                bad_rows.add(line_no)
        parsed.append((line_no, values))

    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for line_no, values in parsed:
        if values["agreement_ref"]:
            groups.setdefault(values["agreement_ref"].lower(), []).append((line_no, values))
    if len(groups) > MAX_AGREEMENTS:
        errors.append(RowError(None, None, f"At most {MAX_AGREEMENTS} agreements per file."))
        return Plan(digest, [], errors)

    codes, by_name = _supplier_lookup(db, ctx.tenant_uuid)
    items: list[Item] = []
    for group in groups.values():
        if any(line_no in bad_rows for line_no, _ in group):
            continue  # its cells are already reported; building it would only repeat them
        item = _build_item(db, ctx, group, codes, by_name, errors)
        if item:
            items.append(item)
    errors.sort(key=lambda e: (e.row or 0, e.column or ""))
    return Plan(digest, items, errors)


def _same(group: list[tuple[int, dict[str, Any]]], cols: list[str], errors: list[RowError]) -> bool:
    ok = True
    first_row, first = group[0]
    for line_no, values in group[1:]:
        for c in cols:
            if values[c] != first[c]:
                errors.append(
                    RowError(
                        line_no,
                        c,
                        f"Differs from row {first_row}; it must be the same on every row of this {'agreement' if c in {x.name for x in VERSION_COLS} or c in ('agreement_name', 'supplier', 'notes') else 'component'}.",
                    )
                )
                ok = False
    return ok


def _build_item(
    db: Session,
    ctx: Any,
    group: list[tuple[int, dict[str, Any]]],
    codes: dict[str, uuid.UUID],
    by_name: dict[str, list[Supplier]],
    errors: list[RowError],
) -> Item | None:
    first_row, first = group[0]
    if not _same(
        group, ["agreement_name", "supplier", "notes", *(c.name for c in VERSION_COLS)], errors
    ):
        return None
    supplier_text = first["supplier"] or ""
    sid = codes.get(suppliers.normalise_code(supplier_text))
    supplier_name = supplier_text
    if sid is None:
        matches = by_name.get(supplier_text.strip().lower(), [])
        if len(matches) == 1:
            sid, supplier_name = matches[0].id, matches[0].name
        elif len(matches) > 1:
            errors.append(
                RowError(
                    first_row,
                    "supplier",
                    f"“{supplier_text}” matches several suppliers; use the supplier code.",
                )
            )
        elif supplier_text:
            errors.append(
                RowError(first_row, "supplier", f"No supplier with code or name “{supplier_text}”.")
            )
    else:
        supplier_name = suppliers.get(db, ctx.tenant_uuid, sid).name
    item = Item(
        first["agreement_ref"],
        first["agreement_name"] or "",
        sid,
        supplier_name,
        first["notes"] or "",
        first_row,
    )

    comps: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for line_no, values in group:
        if values["component_key"]:
            comps.setdefault(values["component_key"], []).append((line_no, values))
    body: dict[str, Any] = {c.name: first[c.name] for c in VERSION_COLS}
    body["components"] = []
    locs: dict[str, Any] = {"first": first_row, "components": []}
    for key, crow in comps.items():
        if not _same(crow, ["component_type", *(c.name for c in COMPONENT_COLS)], errors):
            return None
        c0 = crow[0][1]
        comp: dict[str, Any] = {"key": key, "type": c0["component_type"]}
        comp.update(
            {
                c.name: c0[c.name]
                for c in COMPONENT_COLS
                if c.name != "component_type" and c0[c.name] is not None
            }
        )
        with_tier = [(n, v) for n, v in crow if any(v[t.name] is not None for t in TIER_COLS)]
        if with_tier and len(with_tier) != len(crow):
            errors.append(
                RowError(
                    crow[0][0],
                    "tier_threshold",
                    f"Component “{key}” mixes rows with and without tier values.",
                )
            )
            return None
        if not with_tier and len(crow) > 1:
            errors.append(
                RowError(
                    crow[1][0],
                    "component_key",
                    f"Component “{key}” appears on several rows but has no tier values.",
                )
            )
            return None
        comp["tiers"] = [
            {t.name.removeprefix("tier_"): v[t.name] for t in TIER_COLS if v[t.name] is not None}
            for _, v in with_tier
        ]
        body["components"].append(comp)
        locs["components"].append({"first": crow[0][0], "tiers": [n for n, _ in with_tier]})
        item.tiers += len(with_tier)
    item.components = len(comps)
    try:
        item.terms = VersionTermsIn.model_validate(body)
    except ValidationError as exc:
        errors.extend(_pydantic_errors(exc, locs))
        return item
    if sid is None:
        return item
    try:
        snap = to_snapshot(
            item.terms,
            agreement_id="bulk",
            version_id="bulk",
            version_no=1,
            supplier_id=str(sid),
            fiscal_start=int(ctx.tenant.fiscal_year_start_month),
            name=item.name,
            external_reference=item.ref,
        )
    except AppError as exc:
        errors.append(RowError(first_row, None, exc.detail or "Agreement terms are invalid."))
        return item
    item.summary = summarize(snap)
    item.warnings = warnings_for(item.terms)
    _decide_action(db, ctx, item, errors)
    return item


def _decide_action(db: Session, ctx: Any, item: Item, errors: list[RowError]) -> None:
    existing = db.execute(
        select(Agreement).where(
            Agreement.tenant_id == ctx.tenant_uuid,
            func.lower(Agreement.external_reference) == item.ref.lower(),
        )
    ).scalar_one_or_none()
    if existing is None:
        return
    item.agreement_id = existing.id
    if existing.supplier_id != item.supplier_id:
        errors.append(
            RowError(
                item.first_row,
                "supplier",
                f"Agreement “{item.ref}” already exists for a different supplier.",
            )
        )
        return
    if existing.status == "archived":
        errors.append(
            RowError(
                item.first_row,
                "agreement_ref",
                f"Agreement “{item.ref}” is archived; unarchive it first.",
            )
        )
        return
    if existing.name != item.name:
        item.warnings.append(
            f"Existing name “{existing.name}” is kept; rename it in the editor if needed."
        )
    open_drafts = [
        v
        for v in agreements.versions(db, ctx.tenant_uuid, existing.id)
        if v.status in (VersionStatus.DRAFT.value, VersionStatus.PENDING_APPROVAL.value)
    ]
    if not open_drafts:
        item.action = "new_version"
        return
    assert item.terms is not None
    if terms_from_rows(db, open_drafts[0]).model_dump() == item.terms.model_dump():
        item.action = "unchanged"
        return
    errors.append(
        RowError(
            item.first_row,
            "agreement_ref",
            f"Agreement “{item.ref}” already has draft version {open_drafts[0].version_no} with different terms. Finish or delete it first.",
        )
    )


# --------------------------------------------------------------------------- commit


def commit(db: Session, ctx: Any, data: bytes) -> Plan:
    plan = parse(db, ctx, data)
    if plan.errors:
        raise AppError(
            422,
            "BULK_INVALID",
            "The file has errors",
            f"{len(plan.errors)} problem(s) found; nothing was created. Fix the file and preview it again.",
        )
    created = new_versions = unchanged = 0
    for item in plan.items:
        assert item.terms is not None and item.supplier_id is not None
        if item.action == "create":
            a, _v, _w = agreements.create(
                db,
                ctx,
                supplier_id=item.supplier_id,
                name=item.name,
                external_reference=item.ref,
                notes=item.notes,
                terms=item.terms,
            )
            item.agreement_id = a.id
            created += 1
        elif item.action == "new_version":
            assert item.agreement_id is not None
            agreements.new_version(db, ctx, item.agreement_id, item.terms)
            new_versions += 1
        else:
            unchanged += 1
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.bulk_imported",
        object_type="tenant",
        object_id=ctx.tenant_uuid,
        summary={
            "created": created,
            "new_versions": new_versions,
            "unchanged": unchanged,
            "sha256": plan.sha256,
        },
    )
    return plan
