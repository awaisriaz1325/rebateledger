"""Other-tenant object factories and sample bodies for the authorization matrix."""

from __future__ import annotations

import uuid
from typing import Any

from tests.api.conftest import World
from tests.api.test_authz_matrix import EXTRA_FACTORIES, SAMPLE_BODIES, SAMPLE_FILES


def supplier(w: World, t: uuid.UUID) -> uuid.UUID:
    sid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.suppliers (id, tenant_id, name, status, category_tags, payment_notes, notes, row_version) VALUES (:s, :t, 'Other', 'active', '{}', '', '', 1)",
        s=sid,
        t=t,
    )
    w.sql(
        "INSERT INTO rl.supplier_aliases (id, tenant_id, supplier_id, code) VALUES (:i, :t, :s, :c)",
        i=uuid.uuid7(),
        t=t,
        s=sid,
        c=f"OTHER-{sid.hex[-10:]}",
    )
    return sid


def agreement(w: World, t: uuid.UUID) -> uuid.UUID:
    return version_and_agreement(w, t)[1]


def version_and_agreement(w: World, t: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    sid = supplier(w, t)
    aid, vid = uuid.uuid7(), uuid.uuid7()
    w.sql(
        "INSERT INTO rl.agreements (id, tenant_id, supplier_id, name, status, notes, row_version) VALUES (:a, :t, :s, 'Other agreement', 'active', '', 1)",
        a=aid,
        t=t,
        s=sid,
    )
    w.sql(
        "INSERT INTO rl.agreement_versions (id, tenant_id, agreement_id, version_no, status, effective_from, period_type, fiscal_aligned, "
        "fiscal_year_start_month, custom_periods, date_basis, measure, spend_basis, threshold_comparison, negative_result, rounding_mode, "
        "payment_terms_days, stacking, prorate_thresholds_on_partial_period, zero_baseline_policy, summary, row_version) VALUES "
        "(:v, :t, :a, 1, 'draft', '2026-01-01', 'quarterly', true, 1, '[]', 'invoice_date', 'spend', 'net_of_returns', 'gte', "
        "'floor_at_zero', 'half_up', 30, 'stackable', false, 'needs_review', '', 1)",
        v=vid,
        t=t,
        a=aid,
    )
    w.sql(
        "INSERT INTO rl.agreement_components (id, tenant_id, version_id, position, component_key, type, rate) VALUES (:c, :t, :v, 0, 'base', 'flat_percent', 0.01)",
        c=uuid.uuid7(),
        t=t,
        v=vid,
    )
    return vid, aid


def version(w: World, t: uuid.UUID) -> uuid.UUID:
    return version_and_agreement(w, t)[0]


def approval(w: World, t: uuid.UUID) -> uuid.UUID:
    aid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.approvals (id, tenant_id, object_type, object_id, status, requested_by, requested_at, request_note, decision_note, payload) VALUES (:i, :t, 'agreement_version', :o, 'pending', :u, now(), '', '', '{}')",
        i=aid,
        t=t,
        o=version(w, t),
        u=uuid.uuid7(),
    )
    return aid


def contact(w: World, t: uuid.UUID) -> uuid.UUID:
    cid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.supplier_contacts (id, tenant_id, supplier_id, name, email, phone, role) VALUES (:c, :t, :s, 'X', '', '', '')",
        c=cid,
        t=t,
        s=supplier(w, t),
    )
    return cid


def attachment(w: World, t: uuid.UUID) -> uuid.UUID:
    att = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.agreement_attachments (id, tenant_id, agreement_id, filename, content_type, size_bytes, sha256, storage_key, uploaded_by, created_at) "
        "VALUES (:i, :t, :a, 'x.pdf', 'application/pdf', 1, '', 'none', :u, now())",
        i=att,
        t=t,
        a=agreement(w, t),
        u=uuid.uuid7(),
    )
    return att


def batch(w: World, t: uuid.UUID) -> uuid.UUID:
    bid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.import_batches (id, tenant_id, import_type, status, filename, file_format, size_bytes, file_hash, storage_key, config, stats, void_reason, row_version) "
        "VALUES (:b, :t, 'purchases', 'committed', 'x.csv', 'csv', 1, :h, 'none', '{\"confirmed\": true}', '{}', '', 1)",
        b=bid,
        t=t,
        h=uuid.uuid4().hex,
    )
    return bid


def template(w: World, t: uuid.UUID) -> uuid.UUID:
    mid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.import_mappings (id, tenant_id, name, import_type, version, config, is_default, archived) VALUES (:m, :t, 'T', 'purchases', 1, '{}', false, false)",
        m=mid,
        t=t,
    )
    return mid


EXTRA_FACTORIES.update(
    {
        "supplier_id": supplier,
        "agreement_id": agreement,
        "version_id": version,
        "approval_id": approval,
        "contact_id": contact,
        "attachment_id": attachment,
        "batch_id": batch,
        "template_id": template,
    }
)

TERMS: dict[str, Any] = {
    "effective_from": "2026-01-01",
    "effective_to": None,
    "period_type": "quarterly",
    "fiscal_aligned": True,
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
    "components": [{"key": "base", "type": "flat_percent", "rate": "0.02"}],
}

SAMPLE_BODIES.update(
    {
        ("PATCH", "/api/v1/suppliers/{supplier_id}"): {"name": "X"},
        ("POST", "/api/v1/suppliers/{supplier_id}/contacts"): {"name": "X"},
        ("PATCH", "/api/v1/agreements/{agreement_id}"): {"name": "X"},
        ("POST", "/api/v1/agreements/{agreement_id}/versions"): TERMS,
        ("PUT", "/api/v1/agreement-versions/{version_id}"): TERMS,
        ("POST", "/api/v1/agreement-versions/{version_id}/preview"): {
            "period_containing": "2026-02-01"
        },
        ("POST", "/api/v1/approvals/{approval_id}/decision"): {"decision": "approve"},
        ("PUT", "/api/v1/imports/{batch_id}/config"): {"header_row": 1},
        ("POST", "/api/v1/imports/{batch_id}/resolve-suppliers"): {"codes": {}},
        ("POST", "/api/v1/imports/{batch_id}/void"): {"reason": "wrong file"},
        ("POST", "/api/v1/imports/{batch_id}/commit"): {"mode": "all_or_nothing"},
        ("PATCH", "/api/v1/import-templates/{template_id}"): {"name": "Y"},
    }
)

SAMPLE_FILES.update(
    {
        ("POST", "/api/v1/agreements/{agreement_id}/attachments"): {
            "files": {"file": ("terms.pdf", b"%PDF-1.4 test", "application/pdf")}
        },
        ("POST", "/api/v1/imports"): {
            "files": {"file": ("p.csv", b"a,b\n1,2\n", "text/csv")},
            "data": {"import_type": "purchases"},
        },
    }
)


def run(w: World, t: uuid.UUID) -> uuid.UUID:
    rid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.calculation_runs (id, tenant_id, number, status, scope, period_start, period_end, snapshot, engine_version, totals, error, created_at, updated_at) "
        "VALUES (:r, :t, (SELECT coalesce(max(number), 0) + 1 FROM rl.calculation_runs WHERE tenant_id = :t), 'succeeded', '{}', '2026-01-01', '2026-03-31', '{}', '1.0.0', '{}', '', now(), now())",
        r=rid,
        t=t,
    )
    return rid


def result(w: World, t: uuid.UUID) -> uuid.UUID:
    vid, aid = version_and_agreement(w, t)
    sid = w.sql("SELECT supplier_id FROM rl.agreements WHERE id = :a", a=aid)[0][0]
    rid, res = run(w, t), uuid.uuid7()
    w.sql(
        "INSERT INTO rl.period_results (id, tenant_id, run_id, agreement_id, agreement_version_id, supplier_id, version_no, period_start, period_end, full_period_start, "
        "full_period_end, period_label, expected, spend, quantity, measure, components, statuses, reasons, eligible_count, excluded_counts, payment_terms_days, due_date, "
        "input_hash, engine_version, created_at) VALUES (:i, :t, :r, :a, :v, :s, 1, '2026-01-01', '2026-03-31', '2026-01-01', '2026-03-31', '2026-Q1', 100, 0, 0, 0, "
        "'[]', '{OK}', '[]', 0, '{}', 30, '2026-04-30', 'h', '1.0.0', now())",
        i=res,
        t=t,
        r=rid,
        a=aid,
        v=vid,
        s=sid,
    )
    return res


def credit(w: World, t: uuid.UUID) -> uuid.UUID:
    cid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.credit_lines (id, tenant_id, supplier_id, credit_reference, credit_date, amount, memo, possible_duplicate, voided, created_at) "
        "VALUES (:c, :t, :s, :r, '2026-05-01', 100, '', false, false, now())",
        c=cid,
        t=t,
        s=supplier(w, t),
        r=f"CR-{cid.hex[-8:]}",
    )
    return cid


def allocation(w: World, t: uuid.UUID) -> uuid.UUID:
    res = result(w, t)
    aid = w.sql("SELECT agreement_id FROM rl.period_results WHERE id = :r", r=res)[0][0]
    al = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.credit_allocations (id, tenant_id, credit_id, agreement_id, period_start, period_end, amount, method, created_at) "
        "VALUES (:i, :t, :c, :a, '2026-01-01', '2026-03-31', 10, 'manual', now())",
        i=al,
        t=t,
        c=credit(w, t),
        a=aid,
    )
    return al


def claim(w: World, t: uuid.UUID) -> uuid.UUID:
    cl = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.claims (id, tenant_id, number, supplier_id, title, status, identified_amount, claimed_amount, claimed_amount_reason, channel, notes, "
        "write_off_reason, pending_write_off, last_reminder, row_version, created_at, updated_at) VALUES (:i, :t, (SELECT coalesce(max(number), 0) + 1 FROM rl.claims WHERE tenant_id = :t), :s, 'X', 'draft', 10, 10, '', 'email', '', '', false, '{}', 1, now(), now())",
        i=cl,
        t=t,
        s=supplier(w, t),
    )
    return cl


def recovery(w: World, t: uuid.UUID) -> uuid.UUID:
    rec = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.claim_recoveries (id, tenant_id, claim_id, credit_id, amount, linked_by, linked_at) VALUES (:i, :t, :c, :cr, 5, :u, now())",
        i=rec,
        t=t,
        c=claim(w, t),
        cr=credit(w, t),
        u=uuid.uuid7(),
    )
    return rec


EXTRA_FACTORIES.update(
    {
        "run_id": run,
        "other_run_id": run,
        "result_id": result,
        "credit_id": credit,
        "allocation_id": allocation,
        "claim_id": claim,
        "recovery_id": recovery,
    }
)
SAMPLE_BODIES.update(
    {
        ("POST", "/api/v1/credits/{credit_id}/allocations"): {
            "parts": [
                {
                    "agreement_id": str(uuid.uuid4()),
                    "period_start": "2026-01-01",
                    "period_end": "2026-03-31",
                    "amount": "1",
                }
            ]
        },
        ("PATCH", "/api/v1/claims/{claim_id}"): {"title": "X"},
        ("POST", "/api/v1/claims/{claim_id}/transition"): {"to": "ready"},
        ("POST", "/api/v1/claims/{claim_id}/notes"): {"text": "hello"},
        ("POST", "/api/v1/claims/{claim_id}/recoveries"): {"credit_id": str(uuid.uuid4())},
    }
)
SAMPLE_FILES.update(
    {
        ("POST", "/api/v1/claims/{claim_id}/attachments"): {
            "files": {"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}
        },
    }
)


def export(w: World, t: uuid.UUID) -> uuid.UUID:
    eid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.exports (id, tenant_id, kind, report, format, params, status, filename, requested_by, error, created_at) "
        "VALUES (:e, :t, 'report', 'claims_register', 'csv', '{}', 'succeeded', 'x.csv', :u, '', now())",
        e=eid,
        t=t,
        u=uuid.uuid7(),
    )
    return eid


EXTRA_FACTORIES["export_id"] = export
SAMPLE_BODIES[("POST", "/api/v1/exports")] = {"report": "claims_register", "format": "csv"}
