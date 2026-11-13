# Load tests (Phase 10, SPEC §11)

Machine: development VM, 4 vCPU, 14 GB RAM, local docker-compose Postgres 18 and Redis 8.
Times are in-process (ASGI TestClient or inline jobs): no network hop, no TLS, no Cloud
Run cold start. **Staging numbers will differ.** Re-run each script on staging in Phase 11
before launch.

## 1. 1,000,000-row import

`backend/scripts/import_load_test.py --rows 1000000` (upload → validate → commit through
the real API, jobs inline).

| Metric | Result | Target |
|---|---|---|
| End to end | 3.2 min | "within target" (SPEC §9 case 27; no number given) |
| Peak RSS | 258 MB | ≤ 768 MB per import worker (ADR 0012 §8) |
| Progress | Updated every 10,000 rows | Visible (case 27) |

Measured in Phase 3 (ADR 0012). The import path has not changed since.

## 2. Calculation run: 50 agreements × 1,000,000 purchase lines

`backend/scripts/run_load_test.py`

| Measurement (same machine unless noted) | Elapsed | Peak RSS | Result |
|---|---|---|---|
| Phase 4, 2026-11-11, smaller database | 242.7 s | 591 MB | met |
| Phase 10, old ORM-entity loader (A/B control) | 324.9 s | 624 MB | missed by 8% |
| Phase 10, column-tuple loader (twice) | 306.7 s / 306.7 s | 383 MB | missed by 2% |

Target: < 300 s **on staging** [PROPOSED TARGET]. All runs produced the same 200 period
results and the same total (8,907,119.10), so the loader change does not alter output.
The new loader cuts peak memory by 39% and time by 6% compared with the old one under
the same conditions. Today's slower runs, compared with Phase 4, come from the shared dev
VM (other services running; the database is about 0.7M rows larger), not from the code.
That is shown by the A/B control being slower than Phase 4 too.

The run has to be re-measured on staging (Cloud Run worker, Cloud SQL) in Phase 11. If it
misses there, the SPEC already allows pushing aggregation to SQL with an ADR (SPEC §4.6).

## 3. API latency at 100,000 rows

`backend/scripts/api_latency_test.py` seeds a demo tenant with 100,000 purchase lines and
100,000 supplier credits, runs one calculation, then times 50 requests per endpoint after 3
warm-up requests, as an analyst.

| Endpoint | Rows returned | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| `/api/v1/suppliers` | 5 | 8 | 10 | 11 |
| `/api/v1/agreements` | 5 | 8 | 9 | 11 |
| `/api/v1/imports` | 3 | 7 | 8 | 8 |
| `/api/v1/runs` | 1 | 7 | 8 | 12 |
| `/api/v1/runs/{run_id}/results` | 40 | 9 | 11 | 12 |
| `/api/v1/reconciliation` | 40 | 15 | 17 | 19 |
| `/api/v1/discrepancies` | 30 | 14 | 16 | 17 |
| `/api/v1/credits` | 200 | 10 | 10 | 10 |
| `/api/v1/credits/unmatched` | 500 | 75 | 118 | 248 |
| `/api/v1/claims` | 0 | 7 | 8 | 8 |
| `/api/v1/tiers` | 5 | 515 | 673 | 799 |
| `/api/v1/dashboard` | 1 | 548 | 698 | 711 |
| `/api/v1/reports/preview` | 40 | 13 | 14 | 14 |

**Target: p95 < 500 ms for list endpoints [PROPOSED TARGET].** Every list endpoint meets
it with a wide margin. `/tiers` and `/dashboard` are not list endpoints, but both are
landing pages. They miss 500 ms by about 200 ms.

### What changed in Phase 10

| Endpoint | Before | After | Change |
|---|---|---|---|
| `/credits/unmatched` | > 10 min per request (aborted) | p95 118 ms | N+1 removed: one grouped allocation subquery + one allocation query; `limit` 1–2000 |
| `/tiers` | p95 4,098 ms | p95 673 ms | Purchase lines loaded as column tuples instead of ORM entities; look-back limited to what the engine reads (`agreements.lines_needed_from`) |
| `/dashboard` | p95 4,030 ms | p95 698 ms | Same; it embeds the tier tracker |

### Remaining gap and proposal

The rest of the tier-tracker time is inside the pure engine: it sorts lines by a canonical
SHA-256 for deterministic traces and the input hash. Changing that would change result
hashes, so the engine was left alone. **Decision (ADR 0016, 2026-11-13): option 1, accepted; the engine is
unchanged.** Options that were considered:

1. **Accept** about 0.7 s for these two aggregate pages (they show skeletons while loading).
2. **Precompute** tier-tracker rows in a background job after each import commit, version
   activation, supplier merge or baseline change, and nightly for the date roll. The API
   then reads one small table. This adds a table and a job, and the "data as of" timestamp
   becomes visible to users.
3. **Engine option** to skip trace hashing for estimates only. This changes the engine, so
   it needs an ADR and must keep 95% coverage.

A cache was rejected: the tracker depends on imports, voids, supplier merges, versions and
baselines, and a stale tier estimate on a finance dashboard costs more trust than 0.7 s.
