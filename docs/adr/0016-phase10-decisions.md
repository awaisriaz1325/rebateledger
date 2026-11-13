# ADR 0016 — Phase 10 hardening decisions

Status: accepted (founder decisions, 2026-11-13)

## Context
The Phase 10 report listed open decisions on performance, backups, accessibility testing,
penetration testing and breached-password checks. The founder answered them on 2026-11-13.

## Decisions
1. **Tier tracker and dashboard latency.** About 0.7 s p95 at 100k purchase lines is
   accepted for these two aggregate pages. No precompute table or cache is added.
2. **Engine unchanged.** The founder delegated this choice. The engine keeps its canonical
   SHA-256 line ordering and full traces for every call, including estimates. Reasons:
   with 0.7 s accepted there is no need; an "estimate mode" would create a second code
   path whose output could differ from a real run; and determinism and result hashes stay
   exactly as tested (golden fixtures, property tests, 99% coverage).
3. **Backup targets approved.** RPO ≤ 5 minutes (point-in-time recovery from WAL) and RTO
   ≤ 4 hours, 7-day minimum retention, quarterly restore drill using
   `infra/scripts/backup_restore_rehearsal.sh` against the restored copy. Phase 11
   implements these.
4. **Keyboard and screen-reader testing** are part of the automated E2E suite
   (`frontend/e2e/keyboard.spec.ts`, `frontend/e2e/screen-reader.spec.ts`). Results are in
   `docs/hardening/accessibility-performance.md`.
5. **No third-party penetration test** is bought. The Phase 10 internal review
   (`docs/hardening/security-review.md`) stands as the security assessment for launch.
6. **Breached-password check stays offline.** HIBP is not enabled; no outbound call is
   added to the request path. The offline common-password list remains.
7. **Remaining Phase 10 risks are accepted**: F5 (offline list only), F6 (rate limits fail
   closed while Redis is down), F7 (no per-user export quota yet), F8 (dev-only `minimatch`
   advisory), F9 (`server: uvicorn` header, still fixed in Phase 11 because it is a
   one-flag change), and the 50 × 1M run re-measure on the live environment.

## Consequences
- Security page copy and sales answers must not claim a third-party penetration test.
- If tier-tracker latency grows with real customer data, revisit option 2 (precompute) in
  `docs/hardening/load-tests.md` §3; it does not require an engine change.
