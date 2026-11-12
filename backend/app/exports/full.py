"""Full data export (SPEC §4.10, Owner only): a ZIP with one CSV per entity and the
original imported files and attachments.

Every tenant-scoped table is included except purely internal machinery (jobs,
idempotency keys, export records). Secret or internal columns are dropped. All CSV
cells pass through formula-injection neutralisation.
"""

from __future__ import annotations

import io
import zipfile
from typing import IO

from sqlalchemy import Table, select
from sqlalchemy.orm import Session

from app.core.csv_safe import write_csv
from app.core.storage import get_storage
from app.db.base import Base
from app.db.models.business import AgreementAttachment, ImportBatch
from app.db.models.identity import Membership, Tenant, User
from app.db.models.runs import ClaimAttachment

SKIP_TABLES = {"jobs", "idempotency_keys", "exports"}
SKIP_COLUMNS = {
    "token_hash",
    "storage_key",
    "dedupe_key",
    "secret_encrypted",
    "password_hash",
    "code_hash",
}
README = """RebateLedger full data export

One CSV per table (UTF-8, comma separated, header row). Amounts are exact decimals in USD.
Cells that start with = + - @ or a control character are prefixed with ' so spreadsheet
apps never run them as formulas; remove the leading ' when loading into a database.

files/imports/      the original files you uploaded (name prefixed with the import id)
files/attachments/  agreement documents and claim attachments
members.csv         people in your organization (names, emails, roles; no credentials)
"""


def _cell(value: object) -> object:
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    if isinstance(value, dict | list):
        import json

        return json.dumps(value, sort_keys=True, default=str)
    return value


def _tenant_tables() -> list[Table]:
    return [
        t
        for t in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        if "tenant_id" in t.columns and t.name not in SKIP_TABLES
    ]


def build_full_export(db: Session, tenant: Tenant, out: IO[bytes]) -> int:
    rows_written = 0
    storage = get_storage()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr("README.txt", README)
        for table in _tenant_tables():
            cols = [c for c in table.columns if c.name not in SKIP_COLUMNS]
            result = db.execute(select(*cols).where(table.c.tenant_id == tenant.id)).yield_per(5000)
            with z.open(f"{table.name}.csv", "w") as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                rows_written += write_csv(
                    text, [c.name for c in cols], ([_cell(v) for v in row] for row in result)
                )
                text.flush()
                text.detach()
        members = db.execute(
            select(User.name, User.email, Membership.role, Membership.status, Membership.created_at)
            .join(User, User.id == Membership.user_id)
            .where(Membership.tenant_id == tenant.id)
            .order_by(User.name)
        ).all()
        with z.open("members.csv", "w") as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            write_csv(text, ["name", "email", "role", "status", "joined_at"], members)
            text.flush()
            text.detach()
        for b in db.execute(
            select(ImportBatch).where(ImportBatch.tenant_id == tenant.id)
        ).scalars():
            _copy(z, storage, b.storage_key, f"files/imports/{b.id}-{_safe(b.filename)}")
        for a in db.execute(
            select(AgreementAttachment).where(AgreementAttachment.tenant_id == tenant.id)
        ).scalars():
            _copy(
                z,
                storage,
                a.storage_key,
                f"files/attachments/agreements/{a.id}-{_safe(a.filename)}",
            )
        for c in db.execute(
            select(ClaimAttachment).where(ClaimAttachment.tenant_id == tenant.id)
        ).scalars():
            _copy(z, storage, c.storage_key, f"files/attachments/claims/{c.id}-{_safe(c.filename)}")
    return rows_written


def _safe(name: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in name)
    return keep.strip(" .")[:150] or "file"


def _copy(z: zipfile.ZipFile, storage: object, key: str | None, arcname: str) -> None:
    if not key or not str(key).count("/"):
        return  # demo/seed rows have no stored file
    try:
        src = storage.open(key)  # type: ignore[attr-defined]
    except FileNotFoundError:
        return
    with src, z.open(arcname, "w", force_zip64=True) as dst:
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)
