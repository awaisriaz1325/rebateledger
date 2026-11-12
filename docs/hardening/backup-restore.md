# Backup and restore rehearsal (Phase 10)

Script: `infra/scripts/backup_restore_rehearsal.sh`. Run 2026-11-12 against the local
docker-compose Postgres 18 (the "staging-like" environment available before Phase 11).
The script dumps the application database, restores it into a scratch database, compares
every table's row count, re-verifies every audit hash chain in the restored copy, then
drops the scratch database. It never writes to the source database.

## Result (actual output)

```
1. Dump (custom format, compressed)
   dump size: 34447927 bytes in 4 s
2. Restore into scratch database rebateledger_restore_rehearsal
   restored in 5 s
3. Row counts per table (source vs restore)
   all 55 tables match
   largest: purchase_lines=612000 credit_lines=144 reconciliation_items=120
4. Audit hash chains in the restored copy
   6 chains, 66 events, broken: 0
5. Clean up
Rehearsal passed.
real 0m9.900s
```

The restore also re-creates RLS policies, invoice-immutability triggers and the
`rl.tenant_usage()` function, because they are part of the schema dump.

## Production plan (Phase 11; prepared, not executed)

| Item | Plan | Target |
|---|---|---|
| Backups | Cloud SQL automated daily backups + point-in-time recovery (WAL), 7-day retention minimum [PROPOSED] | RPO ≤ 5 min (PITR) |
| Restore drill | Quarterly: clone to a new instance at a timestamp, run this script's row-count and audit-chain checks against the clone | RTO ≤ 4 h [PROPOSED] |
| Object storage | GCS bucket with object versioning and a retention policy for uploads and exports | — |
| Encryption | Google-managed keys at rest. CMEK is a founder decision (cost) | — |
| Ownership | Runbook `docs/runbooks/restore.md` (Phase 11) | — |

The RPO and RTO above are proposals; SPEC §11 does not set them. They are listed under
Undecided in the Phase 10 report.
