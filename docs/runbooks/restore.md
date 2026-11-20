# Runbook — restore (RPO ≤ 5 min, RTO ≤ 4 h; ADR 0016, ADR 0018)

Backups: nightly base backups and WAL segments in `gs://BUCKET/archive/` (30 days), uploaded
files in `gs://BUCKET/storage/`. `compose` is defined in docs/runbooks/deploy.md.

## Point-in-time restore (bad migration, mistaken bulk change, lost VM)
1. Decide the target time (UTC), e.g. one minute before the incident. Tell customers.
2. Stop writers: `compose stop web api worker scheduler backup offsite`.
3. Keep the damaged data: `compose stop postgres` and leave the `pgdata` volume untouched
   (rename it later only after the restore is verified).
4. Fetch backups to a scratch directory on the VM (or a new VM if this one is lost):
   `gcloud storage cp -r gs://BUCKET/archive ./restore-src`
5. Start a throwaway Postgres 18.6 container with a NEW empty volume, extract the latest base
   backup taken before the target (`base.tar.gz` into the data directory, which for the
   `postgres:18.6-alpine` image is `/var/lib/postgresql/18/docker`; `chown -R postgres` and
   `chmod 700` it; `pg_wal.tar.gz` is not needed with `-X none`), then add to `postgresql.auto.conf`:
   ```
   restore_command = 'cp /restore-src/archive/wal/%f %p'
   recovery_target_time = '2026-11-17 10:41:00+00'
   recovery_target_action = 'promote'
   ```
   and create an empty `recovery.signal`. Start it; it replays WAL to the target and promotes.
6. Verify on the restored copy: row counts per table, the audit chain
   (`infra/scripts/backup_restore_rehearsal.sh` checks), and the incident data.
7. Point production at the restored volume (swap volumes in compose), start the stack, and
   restore `gs://BUCKET/storage/` into the `storage` volume if files were lost.
8. Record what happened in `docs/PROGRESS.md` and the incident log.

## Drill (quarterly)
Run steps 4–6 into a scratch container with a recent target time; record the elapsed time
against the 4-hour RTO in `docs/hardening/backup-restore.md`.

Rehearsed locally on 2026-11-20 with `infra/scripts/restore_drill_local.sh` (production image,
archive settings and base-backup command; no cloud): restored to the target time in 3 s with every
row before the target and none of the simulated incident. The drill found and fixed two production
defects (WAL archive folder not writable by Postgres; no replication access for the `backup`
container). Still to do: the same drill on the production VM with backups fetched from GCS
(steps 1–8), before launch.
