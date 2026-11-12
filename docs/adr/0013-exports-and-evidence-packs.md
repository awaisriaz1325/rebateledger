# ADR 0013 — Reports, exports and evidence packs

Status: accepted (retention defaults marked [PROPOSED DEFAULT] need founder confirmation)

## Context
SPEC §4.10 and §4.8 require on-screen reports, CSV/XLSX/PDF exports with formula
neutralisation, a claim evidence pack, an Owner-only full data export, and downloads
through short-lived signed links. PHASES §7 adds three acceptance tests.

## Decisions
1. **One pipeline for every file.** `POST` creates an `exports` row (RLS-protected) and a
   `build_export` job (202 + job, SPEC §6). The worker renders the file, stores it under
   a tenant-prefixed random key, and notifies the requester (`export_ready`).
2. **Downloads.** `POST /exports/{id}/link` re-checks authorisation and returns an
   HMAC-signed URL valid for **15 minutes**, bound to export, user and tenant. The
   download endpoint also requires the session and re-checks visibility, then streams
   with `Content-Disposition: attachment`, `Cache-Control: no-store`, `nosniff`.
   Every download writes `export.downloaded` to the audit log.
3. **Visibility.** People see their own exports; holders of `full_export` (Owners) see
   all. Other users' exports answer 404, never 403.
4. **Retention.** Full data exports: **24 h** (SPEC [PROPOSED DEFAULT]). Report and
   evidence-pack files: **7 days** [PROPOSED DEFAULT — my choice, needs founder
   confirmation]. A daily `expire_exports` job deletes expired files; rows stay as history.
5. **Same numbers as the screen.** Reports use the same `live_items` reconciliation the
   Results screen uses; totals are exact `Decimal` sums. The evidence pack's amounts come
   from that same source, and its eligible-line appendix is rebuilt with the engine's own
   `select_lines` over exactly the import batches the run used, with an explicit
   "matches the run's eligible spend" check printed in the PDF.
6. **Formula injection.** CSV: every cell through `csv_safe.neutralize`. XLSX: genuine
   numbers and dates are typed cells; every text cell is neutralised *and* forced to the
   string type (openpyxl would otherwise turn `=…` into a formula). PDF has no formulas;
   all user text is Jinja-autoescaped.
7. **PDF isolation.** WeasyPrint 70 with `NoNetworkFetcher` (a `URLFetcher` subclass that
   refuses everything except inline `data:` URIs, redirects off). Verified against the
   installed source (`weasyprint/urls.py`: `fetch()` calls `url_fetcher(url)`). A test
   with a live local HTTP server proves zero requests, including `file://`.
8. **Full export contents.** One CSV per tenant table except `jobs`,
   `idempotency_keys`, `exports`; columns `token_hash`, `storage_key`, `dedupe_key`,
   `secret_encrypted`, `password_hash`, `code_hash` dropped; plus `members.csv` (no
   credentials), original import files and attachments. Requires Owner + step-up; one
   in progress per tenant.

## Consequences
- The worker image must include WeasyPrint's system libraries (Pango, HarfBuzz incl.
  `libharfbuzz-subset0`); Phase 11 Dockerfile.
- Spreadsheet users see a leading `'` on neutralised cells (accepted by SPEC §4.10).
- sonner's runtime `<style>` injection stays blocked by CSP (harmless console message);
  its CSS is shipped as a normal stylesheet.
