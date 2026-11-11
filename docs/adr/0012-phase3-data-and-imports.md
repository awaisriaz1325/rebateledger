# ADR 0012 — Agreement versioning and import pipeline decisions (Phase 3)

Status: accepted for v1 — items marked [FOUNDER] are listed in the Phase 3 report

1. **Terms storage** follows SPEC §5 tables (`agreement_versions`, `agreement_components`,
   `agreement_tiers`, `eligibility_rules`). Engine validation (`VersionSnapshot`) is the
   single source of truth for structural rules; the API rejects anything it rejects.
2. **Immutability** is enforced twice: services refuse edits to non-drafts (409), and
   Postgres triggers reject UPDATE/DELETE of terms on non-draft versions and their
   child rows, even for the application role.
3. **Supersession** [FOUNDER]: activating version N whose `effective_from` is after an
   active version's start sets the old version to `superseded` and closes its
   `effective_to` to the day before (the only post-activation change allowed; terms
   untouched). Any other overlap is refused (`VERSION_OVERLAP`).
4. **Four-eyes** compares user identity (requester ≠ decider) at decision time and
   requires the decider to hold `approve` *then*; a DB CHECK forbids
   `decided_by = requested_by`. Role changes mid-flow therefore cannot enable
   self-approval.
5. **Commit atomicity**: one database transaction per batch. All-or-nothing mode uses a
   SAVEPOINT so failed batches leave zero rows but keep their error report. A worker
   crash mid-commit rolls back; the job is retried and resumes from scratch.
6. **Deduplication** uses partial unique indexes on non-voided rows
   (`purchase_lines(tenant, supplier, dedupe_key)`, `credit_lines(tenant, supplier,
   credit_reference)`) with `ON CONFLICT DO NOTHING … RETURNING source_row`, which
   catches duplicates both against committed data and within the file without
   holding keys in memory.
7. **Limits** [FOUNDER]: SPEC §4.5.2 defaults of 50 MB *and* 1,000,000 rows conflict for
   typical exports (~60–80 bytes/row → 60–80 MB at 1M rows). v1 keeps both as written;
   the load test uses compact rows (42 MB). Proposal: raise the byte cap to 150 MB or
   accept gzip-compressed CSV.
8. **Memory budget**: ≤ 768 MB peak RSS per import worker. Measured: 258 MB for 1M rows
   (`scripts/import_load_test.py`), 3.2 minutes end to end on the dev machine.
9. **Plans** are seeded by migration 0002 with the SPEC prices ([PROPOSED DEFAULT]); no
   subscription row = no limits (tenants are provisioned by the operator in Phase 8).
