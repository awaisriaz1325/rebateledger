"""Import pipeline (SPEC §4.5): upload → detect → map → formats → validate → commit → void."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Any, BinaryIO

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.clock import today_in, utcnow
from app.core.errors import AppError, conflict, not_found
from app.core.storage import get_storage, new_key
from app.db.models.business import (
    Agreement,
    BaselineRow,
    BatchStatus,
    CreditLineRow,
    ImportBatch,
    ImportMapping,
    ImportRowError,
    ImportType,
    Product,
    PurchaseLineRow,
    Supplier,
    SupplierAlias,
    SupplierContact,
)
from app.db.models.identity import Tenant
from app.imports import detect, fields, presets
from app.imports.parsing import date_format_candidates
from app.imports.reader import iter_rows, split_header, xlsx_sheets
from app.imports.validate import Context, Issue, RowResult, RowValidator
from app.services import subscriptions, suppliers
from app.services.audit import record
from app.workers.jobs import JobContext, enqueue, handler

PREVIEW_ROWS = 200
MAX_STORED_ISSUES = 100_000
CHUNK = 2_000


# --------------------------------------------------------------------------- helpers


def get_batch(
    db: Session, tenant_id: uuid.UUID, batch_id: uuid.UUID, *, lock: bool = False
) -> ImportBatch:
    q = select(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.tenant_id == tenant_id)
    if lock:
        q = q.with_for_update()
    b = db.execute(q).scalar_one_or_none()
    if b is None:
        raise not_found("Import")
    return b


@contextmanager
def _open(batch: ImportBatch) -> Iterator[BinaryIO]:
    fh = get_storage().open(batch.storage_key)
    try:
        yield fh
    finally:
        fh.close()


@contextmanager
def _table(batch: ImportBatch) -> Iterator[tuple[list[str], Iterator[tuple[int, list[str]]]]]:
    """Header + body rows; the row generator is closed before the file."""
    with _open(batch) as fh:
        rows = iter_rows(fh, batch.config, batch.file_format)
        try:
            header, body = split_header(rows, int(batch.config.get("header_row", 1)))
            try:
                yield header, body
            finally:
                close = getattr(body, "close", None)
                if close:
                    close()
        finally:
            close_rows = getattr(rows, "close", None)
            if close_rows:
                close_rows()


# --------------------------------------------------------------------------- upload


def upload(
    db: Session,
    ctx: Any,
    *,
    import_type: ImportType,
    filename: str,
    stream: BinaryIO,
    confirm_duplicate: bool,
) -> ImportBatch:
    """Store the original under a tenant-scoped random key (never served inline)."""
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as tmp:
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > detect.MAX_UPLOAD_BYTES:
                raise detect.reject(
                    "FILE_TOO_LARGE",
                    f"Files may be at most {detect.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                )
            digest.update(chunk)
            tmp.write(chunk)
        if size == 0:
            raise detect.reject("FILE_EMPTY", "The file is empty.")
        tmp.seek(0)
        head = tmp.read(64 * 1024)
        tmp.seek(0)
        fmt = detect.file_format(filename, head)
        if fmt == "xlsx":
            detect.check_xlsx(tmp)  # type: ignore[arg-type]
        file_hash = digest.hexdigest()
        previous = (
            db.execute(
                select(ImportBatch)
                .where(
                    ImportBatch.tenant_id == ctx.tenant_uuid,
                    ImportBatch.file_hash == file_hash,
                    ImportBatch.status != BatchStatus.VOIDED.value,
                )
                .order_by(ImportBatch.created_at.desc())
            )
            .scalars()
            .first()
        )
        if previous is not None and not confirm_duplicate:
            raise AppError(
                409,
                "FILE_ALREADY_IMPORTED",
                "This file was uploaded before",
                f"An identical file ({previous.filename}) was uploaded on {previous.created_at:%Y-%m-%d} as import {previous.id}. Upload again with confirmation to continue.",
                extra={
                    "previous_batch_id": str(previous.id),
                    "previous_uploaded_at": previous.created_at.isoformat(),
                    "previous_status": previous.status,
                },
            )
        subscriptions.check(db, ctx.tenant_uuid, storage_bytes=size)
        key = new_key(ctx.tenant_uuid, "imports")
        get_storage().put(key, tmp)  # type: ignore[arg-type]
    safe_name = "".join(ch for ch in filename if ch.isprintable())[-200:] or "upload"
    batch = ImportBatch(
        tenant_id=ctx.tenant_uuid,
        import_type=import_type.value,
        filename=safe_name,
        file_format=fmt,
        size_bytes=size,
        file_hash=file_hash,
        storage_key=key,
        created_by=ctx.user.id,
        duplicate_of_batch_id=previous.id if previous else None,
    )
    db.add(batch)
    db.flush()
    batch.config = _initial_config(db, ctx, batch, head)
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="import.uploaded",
        object_type="import_batch",
        object_id=batch.id,
        summary={
            "type": import_type.value,
            "format": fmt,
            "size_bytes": size,
            "duplicate_of": str(previous.id) if previous else None,
        },
    )
    return batch


def _initial_config(db: Session, ctx: Any, batch: ImportBatch, head: bytes) -> dict[str, Any]:
    config: dict[str, Any] = {"header_row": 1, "columns": {}, "flags": {}, "confirmed": False}
    if batch.file_format == "csv":
        encoding = detect.detect_encoding(head)
        config.update(
            encoding=encoding,
            delimiter=detect.detect_delimiter(detect.decode_sample(head, encoding)),
        )
    else:
        with _open(batch) as fh:
            sheets = xlsx_sheets(fh)
        config.update(sheet=sheets[0] if sheets else None, sheets=sheets)
    template = _default_template(db, ctx.tenant_uuid, batch.import_type)
    if template is not None:
        config.update(
            {
                k: v
                for k, v in template.config.items()
                if k not in ("encoding", "delimiter", "sheet", "sheets")
            }
        )
        config["template_id"] = str(template.id)
        batch.mapping_id = template.id
    return config


def _default_template(db: Session, tenant_id: uuid.UUID, import_type: str) -> ImportMapping | None:
    return (
        db.execute(
            select(ImportMapping)
            .where(
                ImportMapping.tenant_id == tenant_id,
                ImportMapping.import_type == import_type,
                ImportMapping.is_default.is_(True),
                ImportMapping.archived.is_(False),
            )
            .order_by(ImportMapping.version.desc())
        )
        .scalars()
        .first()
    )


# --------------------------------------------------------------------------- preview


def _validation_context(db: Session, ctx: Any, batch: ImportBatch, header: list[str]) -> Context:
    tenant: Tenant = ctx.tenant
    agreements = list(
        db.execute(select(Agreement).where(Agreement.tenant_id == batch.tenant_id)).scalars()
    )
    by_supplier: dict[uuid.UUID, list[uuid.UUID]] = {}
    for a in agreements:
        by_supplier.setdefault(a.supplier_id, []).append(a.id)
    return Context(
        import_type=ImportType(batch.import_type),
        header=header,
        config=batch.config,
        supplier_codes=suppliers.code_map(db, batch.tenant_id),
        today=today_in(tenant.timezone),
        agreements_by_ref={
            a.external_reference.lower(): a.id for a in agreements if a.external_reference
        },
        agreements_by_supplier=by_supplier,
    )


def preview(db: Session, ctx: Any, batch: ImportBatch) -> dict[str, Any]:
    """Detected settings, raw first rows, suggested mapping, date-format candidates."""
    with _table(batch) as (header, body):
        sample = []
        for _, cells in body:
            sample.append(cells[: len(header) + 5])
            if len(sample) >= 20:
                break
    itype = ImportType(batch.import_type)
    suggested = fields.suggest(itype, header)
    date_candidates: dict[str, list[str]] = {}
    for spec in fields.FIELDS[itype]:
        if spec.kind != "date":
            continue
        col = batch.config.get("columns", {}).get(spec.name) or suggested.get(spec.name)
        if col in header:
            i = header.index(col)
            date_candidates[spec.name] = date_format_candidates(
                [r[i] for r in sample if i < len(r)]
            )
    return {
        "header": header,
        "sample_rows": sample,
        "suggested_columns": suggested,
        "date_format_candidates": date_candidates,
        "fields": [
            {"name": f.name, "label": f.label, "required": f.required, "kind": f.kind}
            for f in fields.FIELDS[itype]
        ],
        "supports_flags": itype in fields.FLAG_TYPES,
        "preset_suggestion": _preset_out(presets.suggest(itype, header)),
        "applied_preset_id": batch.config.get("preset_id"),
    }


def _preset_out(p: presets.Preset | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"id": p.id, "erp": p.erp, "report": p.report, "verified": p.verified}


def _get_preset(preset_id: str, import_type: str) -> presets.Preset:
    p = presets.get(preset_id)
    if p is None:
        raise not_found("Preset")
    if p.import_type.value != import_type:
        raise AppError(
            422,
            "PRESET_TYPE_MISMATCH",
            "Preset is for another import type",
            f"{p.erp} — {p.report} is a {p.import_type.value} preset.",
        )
    return p


def apply_preset(db: Session, ctx: Any, batch: ImportBatch, preset_id: str) -> ImportBatch:
    """Map columns and formats from an ERP preset. The user still reviews and confirms.

    Refuses (and changes nothing) when a required field cannot be found in the file.
    """
    p = _get_preset(preset_id, batch.import_type)
    with _table(batch) as (header, _body):
        resolved = presets.resolve(p, header)
    missing = presets.missing_required(p, resolved)
    if missing:
        raise AppError(
            422,
            "PRESET_DOES_NOT_FIT",
            "This file does not match the preset",
            "Columns not found for: " + ", ".join(missing) + ". Map the columns yourself.",
            extra={"missing_fields": missing},
        )
    set_config(db, ctx, batch, {**p.config, "columns": resolved})
    # The mapping is applied but not yet reviewed: the user must still confirm it.
    batch.config = {**batch.config, "preset_id": p.id, "confirmed": False}
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="import.preset_applied",
        object_type="import_batch",
        object_id=batch.id,
        summary={"preset": p.id, "fields": sorted(resolved)},
    )
    return batch


def template_from_preset(
    db: Session, ctx: Any, *, preset_id: str, name: str, is_default: bool
) -> ImportMapping:
    p = presets.get(preset_id)
    if p is None:
        raise not_found("Preset")
    return save_template(
        db,
        ctx,
        name=name,
        import_type=p.import_type,
        config=presets.template_config(p),
        supplier_id=None,
        is_default=is_default,
    )


CONFIG_KEYS = {
    "encoding",
    "delimiter",
    "sheet",
    "header_row",
    "columns",
    "flags",
    "date_format",
    "decimal_separator",
    "thousands_separator",
    "negative_style",
    "currency_symbols",
    "credit_sign",
    "true_values",
    "false_values",
}


def set_config(db: Session, ctx: Any, batch: ImportBatch, values: dict[str, Any]) -> ImportBatch:
    if batch.status not in (
        BatchStatus.UPLOADED.value,
        BatchStatus.VALIDATED.value,
        BatchStatus.FAILED.value,
    ):
        raise conflict("IMPORT_NOT_EDITABLE", f"This import is {batch.status}.")
    unknown = set(values) - CONFIG_KEYS
    if unknown:
        raise AppError(422, "UNKNOWN_FIELD", "Unknown settings", ", ".join(sorted(unknown)))
    if "encoding" in values and values["encoding"] not in detect.ENCODINGS:
        raise AppError(
            422,
            "ENCODING_INVALID",
            "Unsupported encoding",
            f"Choose one of {', '.join(detect.ENCODINGS)}.",
        )
    if "delimiter" in values and values["delimiter"] not in detect.DELIMITERS:
        raise AppError(
            422,
            "DELIMITER_INVALID",
            "Unsupported delimiter",
            "Choose comma, semicolon, tab or pipe.",
        )
    if "sheet" in values and values["sheet"] not in batch.config.get("sheets", []):
        raise AppError(
            422, "SHEET_INVALID", "Unknown worksheet", "Choose one of the workbook's sheets."
        )
    batch.config = {**batch.config, **values, "confirmed": True}
    batch.status = BatchStatus.UPLOADED.value
    batch.updated_by = ctx.user.id
    return batch


def validate_preview(db: Session, ctx: Any, batch: ImportBatch) -> dict[str, Any]:
    """First 200 rows with per-cell errors (instant)."""
    with _table(batch) as (header, body):
        validator = RowValidator(_validation_context(db, ctx, batch, header))
        problems = validator.config_problems()
        if problems:
            return {"config_problems": problems, "rows": []}
        rows = []
        for number, cells in body:
            if not any(c.strip() for c in cells):
                continue
            res = validator.validate(number, cells)
            rows.append(
                {
                    "row": number,
                    "cells": cells[: len(header)],
                    "ok": res.ok,
                    "issues": [i.__dict__ for i in res.issues if i.severity != "info"],
                }
            )
            if len(rows) >= PREVIEW_ROWS:
                break
    return {"config_problems": [], "rows": rows}


# --------------------------------------------------------------------------- full validation + commit jobs


def start(
    db: Session, ctx: Any, batch: ImportBatch, *, commit: bool, mode: str = "all_or_nothing"
) -> uuid.UUID:
    if not batch.config.get("confirmed"):
        raise conflict("IMPORT_NOT_CONFIGURED", "Confirm the column mapping and formats first.")
    if commit:
        if batch.status not in (BatchStatus.VALIDATED.value, BatchStatus.UPLOADED.value):
            raise conflict("IMPORT_NOT_COMMITTABLE", f"This import is {batch.status}.")
        if mode not in ("all_or_nothing", "skip_invalid"):
            raise AppError(
                422,
                "COMMIT_MODE_INVALID",
                "Invalid commit mode",
                "Use all_or_nothing or skip_invalid.",
            )
        rows = int(batch.stats.get("rows_valid", 0) or 0)
        if rows:
            subscriptions.check(db, ctx.tenant_uuid, import_rows=rows)
        batch.commit_mode = mode
        batch.status = BatchStatus.COMMITTING.value
    else:
        if batch.status not in (
            BatchStatus.UPLOADED.value,
            BatchStatus.VALIDATED.value,
            BatchStatus.FAILED.value,
        ):
            raise conflict("IMPORT_BUSY", f"This import is {batch.status}.")
        batch.status = BatchStatus.VALIDATING.value
    job = enqueue(
        db,
        tenant_id=ctx.tenant_uuid,
        job_type="import_commit" if commit else "import_validate",
        payload={"batch_id": str(batch.id)},
        created_by=ctx.user.id,
        max_attempts=2,
    )
    batch.job_id = job.id
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="import.commit_started" if commit else "import.validation_started",
        object_type="import_batch",
        object_id=batch.id,
        summary={"mode": mode} if commit else {},
    )
    return job.id


class _JobCtx:
    """Minimal ctx for helpers that expect a request context."""

    def __init__(self, db: Session, tenant_id: uuid.UUID) -> None:
        self.tenant_uuid = tenant_id
        self.tenant = db.get(Tenant, tenant_id)


def _scan(db: Session, batch: ImportBatch, job: JobContext | None) -> Iterator[RowResult]:
    jctx = _JobCtx(db, batch.tenant_id)
    with _table(batch) as (header, body):
        validator = RowValidator(_validation_context(db, jctx, batch, header))
        problems = validator.config_problems()
        if problems:
            raise _UserError("IMPORT_NOT_CONFIGURED", " ".join(problems))
        for n, (number, cells) in enumerate(body, start=1):
            if not any(c.strip() for c in cells):
                continue  # fully empty rows are dropped (SPEC §4.5.3)
            if job is not None and n % 10_000 == 0:
                job.progress(n)
            yield validator.validate(number, cells)


class _UserError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.user_message = message
        self.code = code


def _store_issues(db: Session, batch: ImportBatch, issues: list[Issue]) -> None:
    if not issues:
        return
    db.execute(
        insert(ImportRowError),
        [
            {
                "id": uuid.uuid7(),
                "tenant_id": batch.tenant_id,
                "batch_id": batch.id,
                "row_number": i.row,
                "column_name": i.column[:200],
                "value": i.value[:200],
                "code": i.code,
                "message": i.message[:300],
                "severity": i.severity,
            }
            for i in issues
        ],
    )


class _Stats:
    def __init__(self) -> None:
        self.rows_read = 0
        self.rows_valid = 0
        self.rows_error = 0
        self.warnings = 0
        self.stored_issues = 0
        self.unknown_codes: dict[str, int] = {}
        self.error_codes: dict[str, int] = {}
        self.min_date: date | None = None
        self.max_date: date | None = None
        self.totals: dict[str, Decimal] = {}
        self.pending_issues: list[Issue] = []

    def add(self, res: RowResult, batch_type: ImportType) -> None:
        self.rows_read += 1
        for issue in res.issues:
            if issue.severity == "info":
                continue
            if issue.severity == "warning":
                self.warnings += 1
            else:
                self.error_codes[issue.code] = self.error_codes.get(issue.code, 0) + 1
            if self.stored_issues < MAX_STORED_ISSUES:
                self.pending_issues.append(issue)
                self.stored_issues += 1
        if res.unknown_code:
            self.unknown_codes[res.unknown_code] = self.unknown_codes.get(res.unknown_code, 0) + 1
        if not res.ok:
            self.rows_error += 1
            return
        self.rows_valid += 1
        rec = res.record
        assert rec is not None
        d = (
            rec.get("invoice_date")
            or rec.get("ship_date")
            or rec.get("receipt_date")
            or rec.get("credit_date")
            or rec.get("period_start")
        )
        if isinstance(d, date):
            self.min_date = d if self.min_date is None or d < self.min_date else self.min_date
            self.max_date = d if self.max_date is None or d > self.max_date else self.max_date
        if batch_type in (ImportType.PURCHASES, ImportType.CREDITS) and rec.get("supplier_id"):
            key = str(rec["supplier_id"])
            self.totals[key] = self.totals.get(key, Decimal(0)) + rec["amount"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows_read": self.rows_read,
            "rows_valid": self.rows_valid,
            "rows_error": self.rows_error,
            "warnings": self.warnings,
            "error_codes": self.error_codes,
            "unknown_supplier_codes": [
                {"code": c, "rows": n} for c, n in sorted(self.unknown_codes.items())
            ],
            "date_from": self.min_date.isoformat() if self.min_date else None,
            "date_to": self.max_date.isoformat() if self.max_date else None,
            "totals_by_supplier": {k: format(v, "f") for k, v in sorted(self.totals.items())},
            "issues_truncated": self.stored_issues >= MAX_STORED_ISSUES,
        }


@handler("import_validate")
def _validate_job(db: Session, job: JobContext) -> dict[str, Any]:
    batch = get_batch(db, job.tenant_id, uuid.UUID(job.payload["batch_id"]), lock=True)  # type: ignore[arg-type]
    db.execute(delete(ImportRowError).where(ImportRowError.batch_id == batch.id))
    stats = _Stats()
    try:
        for res in _scan(db, batch, job):
            stats.add(res, ImportType(batch.import_type))
            if len(stats.pending_issues) >= CHUNK:
                _store_issues(db, batch, stats.pending_issues)
                stats.pending_issues = []
    except (_UserError, AppError) as exc:
        batch.status = BatchStatus.FAILED.value
        batch.stats = {
            **batch.stats,
            "failure": getattr(exc, "user_message", None) or getattr(exc, "detail", ""),
        }
        return {"status": "failed"}
    _store_issues(db, batch, stats.pending_issues)
    batch.stats = stats.as_dict()
    batch.status = BatchStatus.VALIDATED.value
    batch.validated_at = utcnow()
    job.progress(stats.rows_read, stats.rows_read)
    return {
        "batch_id": str(batch.id),
        **{
            k: v
            for k, v in batch.stats.items()
            if k in ("rows_read", "rows_valid", "rows_error", "warnings")
        },
    }


def _insert(
    db: Session, batch: ImportBatch, kind: ImportType, records: list[tuple[int, dict[str, Any]]]
) -> set[int]:
    """Insert one chunk; returns source rows actually inserted (others were duplicates)."""
    if not records:
        return set()
    tid = batch.tenant_id
    if kind is ImportType.PURCHASES:
        values = [
            {"tenant_id": tid, "batch_id": batch.id, "source_row": row, **rec}
            for row, rec in records
        ]
        stmt = (
            insert(PurchaseLineRow)
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "supplier_id", "dedupe_key"],
                index_where=text("NOT voided"),
            )
            .returning(PurchaseLineRow.source_row, sort_by_parameter_order=True)
        )
        return set(db.execute(stmt, values).scalars())
    if kind is ImportType.CREDITS:
        values = [
            {"id": uuid.uuid7(), "tenant_id": tid, "batch_id": batch.id, "source_row": row, **rec}
            for row, rec in records
        ]
        credit_stmt = (
            insert(CreditLineRow)
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "supplier_id", "credit_reference"],
                index_where=text("NOT voided"),
            )
            .returning(CreditLineRow.source_row, sort_by_parameter_order=True)
        )
        return {r for r in db.execute(credit_stmt, values).scalars() if r is not None}
    if kind is ImportType.BASELINES:
        db.execute(
            insert(BaselineRow),
            [
                {
                    "id": uuid.uuid7(),
                    "tenant_id": tid,
                    "batch_id": batch.id,
                    "source_row": row,
                    **rec,
                }
                for row, rec in records
            ],
        )
        return {row for row, _ in records}
    if kind is ImportType.PRODUCTS:
        for _, rec in records:
            upsert = (
                insert(Product)
                .values(id=uuid.uuid7(), tenant_id=tid, batch_id=batch.id, **rec)
                .on_conflict_do_update(
                    index_elements=["tenant_id", "sku"],
                    set_={
                        "category": rec["category"],
                        "description": rec["description"],
                        "supplier_id": rec["supplier_id"],
                        "batch_id": batch.id,
                    },
                )
            )
            db.execute(upsert)
        return {row for row, _ in records}
    # suppliers
    inserted = set()
    codes = suppliers.code_map(db, tid)
    for row, rec in records:
        if rec["code"] in codes:
            continue
        s = Supplier(
            tenant_id=tid, name=rec["name"], category_tags=rec["tags"], created_by=batch.created_by
        )
        db.add(s)
        db.flush()
        db.add(SupplierAlias(tenant_id=tid, supplier_id=s.id, code=rec["code"]))
        if rec.get("contact_name"):
            db.add(
                SupplierContact(
                    tenant_id=tid,
                    supplier_id=s.id,
                    name=rec["contact_name"],
                    email=rec.get("contact_email") or "",
                    phone=rec.get("contact_phone") or "",
                )
            )
        codes[rec["code"]] = s.id
        inserted.add(row)
    db.flush()
    return inserted


@handler("import_commit")
def _commit_job(db: Session, job: JobContext) -> dict[str, Any]:
    """One transaction for the whole batch: a crash mid-commit rolls back everything
    (SPEC §9 case 29); nothing becomes visible until the commit succeeds."""
    batch = get_batch(db, job.tenant_id, uuid.UUID(job.payload["batch_id"]), lock=True)  # type: ignore[arg-type]
    kind = ImportType(batch.import_type)
    skip_invalid = batch.commit_mode == "skip_invalid"
    db.execute(delete(ImportRowError).where(ImportRowError.batch_id == batch.id))
    stats = _Stats()
    pending: list[tuple[int, dict[str, Any]]] = []
    inserted = duplicates = 0
    duplicate_issues: list[Issue] = []

    def flush() -> None:
        nonlocal inserted, duplicates
        done = _insert(db, batch, kind, pending)
        inserted += len(done)
        for row, _ in pending:
            if row not in done and kind in (
                ImportType.PURCHASES,
                ImportType.CREDITS,
                ImportType.SUPPLIERS,
            ):
                duplicates += 1
                if len(duplicate_issues) < MAX_STORED_ISSUES:
                    duplicate_issues.append(
                        Issue(
                            row,
                            "",
                            "",
                            "DUPLICATE_ROW",
                            "Duplicate of a row already imported or earlier in this file; skipped.",
                            "warning",
                        )
                    )
        pending.clear()

    savepoint = db.begin_nested()
    try:
        for res in _scan(db, batch, job):
            stats.add(res, kind)
            if res.ok and (skip_invalid or stats.rows_error == 0):
                assert res.record is not None
                pending.append((res.row, res.record))
            elif not skip_invalid and pending:
                pending.clear()  # all-or-nothing: stop collecting once a row fails
            if len(pending) >= CHUNK:
                flush()
            # Issues stay in memory (capped at MAX_STORED_ISSUES) and are written after
            # the commit/rollback decision so a rollback never loses the error report.
    except (_UserError, AppError) as exc:
        raise _UserError(
            "IMPORT_FAILED",
            str(
                getattr(exc, "user_message", None) or getattr(exc, "detail", "") or "Import failed"
            ),
        ) from None

    if stats.rows_error and not skip_invalid:
        # All-or-nothing: undo every chunk already written; keep the error report.
        savepoint.rollback()
        db.execute(delete(ImportRowError).where(ImportRowError.batch_id == batch.id))
        _store_issues(db, batch, stats.pending_issues)
        batch.stats = {
            **stats.as_dict(),
            "rows_committed": 0,
            "failure": f"{stats.rows_error} row(s) have errors. Fix the file, or commit with 'skip invalid rows'.",
        }
        batch.status = BatchStatus.VALIDATED.value
        return {"status": "failed", "rows_error": stats.rows_error}
    flush()
    _store_issues(db, batch, stats.pending_issues + duplicate_issues)
    if kind is ImportType.CREDITS:
        _flag_possible_duplicates(db, batch)
    batch.stats = {
        **stats.as_dict(),
        "rows_committed": inserted,
        "rows_skipped": stats.rows_error,
        "duplicates": duplicates,
    }
    batch.status = BatchStatus.COMMITTED.value
    batch.committed_at = utcnow()
    record(
        db,
        tenant_id=batch.tenant_id,
        actor=_actor(batch),
        action="import.committed",
        object_type="import_batch",
        object_id=batch.id,
        summary={
            "rows_committed": inserted,
            "duplicates": duplicates,
            "rows_skipped": stats.rows_error,
        },
    )
    from app.services.staleness import mark_stale_for_batch

    mark_stale_for_batch(db, batch.tenant_id, batch.id, "new import overlapping the period")
    job.progress(stats.rows_read, stats.rows_read)
    return {
        "batch_id": str(batch.id),
        "rows_committed": inserted,
        "duplicates": duplicates,
        "rows_skipped": stats.rows_error,
    }


def _actor(batch: ImportBatch) -> Any:
    from app.services.audit import Actor

    return Actor("user", batch.created_by, "import")


def _flag_possible_duplicates(db: Session, batch: ImportBatch) -> None:
    """Same supplier + amount + date, different reference → warning (SPEC §4.5.4)."""
    other = CreditLineRow.__table__.alias("other")
    me = CreditLineRow.__table__
    db.execute(
        update(CreditLineRow)
        .where(CreditLineRow.batch_id == batch.id, CreditLineRow.tenant_id == batch.tenant_id)
        .where(
            select(other.c.id)
            .where(
                other.c.tenant_id == me.c.tenant_id,
                other.c.supplier_id == me.c.supplier_id,
                other.c.amount == me.c.amount,
                other.c.credit_date == me.c.credit_date,
                other.c.credit_reference != me.c.credit_reference,
                other.c.voided.is_(False),
            )
            .exists()
        )
        .values(possible_duplicate=True)
    )


# --------------------------------------------------------------------------- supplier resolution, void, errors


def resolve_suppliers(
    db: Session, ctx: Any, batch: ImportBatch, actions: dict[str, dict[str, Any]]
) -> int:
    """Grouped unknown codes: create a supplier or map the code to an existing one."""
    done = 0
    for raw_code, action in actions.items():
        code = suppliers.normalise_code(raw_code)
        if code in suppliers.code_map(db, ctx.tenant_uuid):
            continue
        if action.get("action") == "create":
            name = str(action.get("name") or code)[:200]
            suppliers.create(
                db, ctx, name=name, codes=[code], category_tags=[], payment_notes="", notes=""
            )
        elif action.get("action") == "map":
            target = suppliers.get(db, ctx.tenant_uuid, uuid.UUID(str(action.get("supplier_id"))))
            db.add(SupplierAlias(tenant_id=ctx.tenant_uuid, supplier_id=target.id, code=code))
            db.flush()
            record(
                db,
                tenant_id=ctx.tenant_uuid,
                actor=ctx.actor,
                action="supplier.alias_added",
                object_type="supplier",
                object_id=target.id,
                summary={"code": code},
            )
        else:
            raise AppError(
                422, "ACTION_INVALID", "Invalid action", f"Choose create or map for {code}."
            )
        done += 1
    if batch.status == BatchStatus.VALIDATED.value:
        batch.status = BatchStatus.UPLOADED.value  # re-validate with the new codes
    return done


def void(db: Session, ctx: Any, batch: ImportBatch, reason: str) -> ImportBatch:
    """Soft void: rows are excluded from future runs; past runs keep their references."""
    if batch.status != BatchStatus.COMMITTED.value:
        raise conflict("IMPORT_NOT_COMMITTED", "Only committed imports can be voided.")
    for model in (PurchaseLineRow, CreditLineRow, BaselineRow):
        db.execute(
            update(model)
            .where(model.tenant_id == batch.tenant_id, model.batch_id == batch.id)
            .values(voided=True)
        )
    batch.status = BatchStatus.VOIDED.value
    batch.voided_at, batch.voided_by, batch.void_reason = utcnow(), ctx.user.id, reason
    if batch.import_type == ImportType.CREDITS.value:
        from app.services.reconciliation import reverse_for_voided_credits

        reverse_for_voided_credits(db, ctx, batch.id)
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="import.voided",
        object_type="import_batch",
        object_id=batch.id,
        summary={"reason": reason[:200]},
    )
    from app.services.staleness import mark_stale_for_batch

    mark_stale_for_batch(db, batch.tenant_id, batch.id, "an import used by this run was voided")
    return batch


def error_rows(db: Session, batch: ImportBatch) -> Iterator[ImportRowError]:
    yield from db.execute(
        select(ImportRowError)
        .where(ImportRowError.tenant_id == batch.tenant_id, ImportRowError.batch_id == batch.id)
        .order_by(ImportRowError.row_number, ImportRowError.id)
        .execution_options(yield_per=5000)
    ).scalars()


def error_count(db: Session, batch: ImportBatch) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(ImportRowError)
            .where(ImportRowError.batch_id == batch.id, ImportRowError.tenant_id == batch.tenant_id)
        ).scalar_one()
    )


# --------------------------------------------------------------------------- templates


def save_template(
    db: Session,
    ctx: Any,
    *,
    name: str,
    import_type: ImportType,
    config: dict[str, Any],
    supplier_id: uuid.UUID | None,
    is_default: bool,
) -> ImportMapping:
    keep = {
        k: v for k, v in config.items() if k in CONFIG_KEYS - {"encoding", "delimiter", "sheet"}
    }
    latest = (
        db.execute(
            select(func.max(ImportMapping.version)).where(
                ImportMapping.tenant_id == ctx.tenant_uuid,
                ImportMapping.import_type == import_type.value,
                ImportMapping.name == name,
            )
        ).scalar()
        or 0
    )
    if is_default:
        db.execute(
            update(ImportMapping)
            .where(
                ImportMapping.tenant_id == ctx.tenant_uuid,
                ImportMapping.import_type == import_type.value,
            )
            .values(is_default=False)
        )
    m = ImportMapping(
        tenant_id=ctx.tenant_uuid,
        name=name,
        import_type=import_type.value,
        version=latest + 1,
        supplier_id=supplier_id,
        config=keep,
        is_default=is_default,
        created_by=ctx.user.id,
    )
    db.add(m)
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="import_mapping.saved",
        object_type="import_mapping",
        object_id=m.id,
        summary={"name": name, "version": m.version},
    )
    return m
