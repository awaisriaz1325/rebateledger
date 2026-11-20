#!/bin/sh
# Local restore drill: `infra/scripts/restore_drill_local.sh` (docs/runbooks/restore.md steps 4–6) with the production image, archive
# settings and base-backup command. Uses throwaway containers, network and volumes only.
set -eu
IMG=postgres:18.6-alpine
N=rldrill
PW=drill-only-password
REPO=$(cd "$(dirname "$0")/../.." && pwd)
cleanup() { docker rm -f ${N}-src ${N}-restore >/dev/null 2>&1 || true; docker network rm ${N}-net >/dev/null 2>&1 || true; docker volume rm ${N}-archive ${N}-data ${N}-restored >/dev/null 2>&1 || true; }
cleanup
docker network create --subnet 172.31.251.0/24 ${N}-net >/dev/null
docker volume create ${N}-archive >/dev/null
docker run --rm -v ${N}-archive:/archive $IMG sh -c 'mkdir -p /archive/wal /archive/base && chown -R postgres:postgres /archive'

echo "== 1. source database with WAL archiving (as infra/prod/compose.yaml)"
docker run -d --name ${N}-src --network ${N}-net -e POSTGRES_PASSWORD=$PW -e REPLICATION_CIDR=172.31.251.0/24 -v "$REPO/infra/prod/postgres-init/02-replication.sh:/docker-entrypoint-initdb.d/02-replication.sh:ro" -v ${N}-data:/var/lib/postgresql -v ${N}-archive:/archive $IMG \
  postgres -c wal_level=replica -c archive_mode=on -c archive_timeout=60 \
  -c "archive_command=test ! -f /archive/wal/%f && cp %p /archive/wal/%f" >/dev/null
until docker exec ${N}-src pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
sleep 2
psql_src() { docker exec ${N}-src psql -U postgres -At -c "$1"; }
psql_src "CREATE TABLE ledger (id int primary key, note text, at timestamptz default now())"
psql_src "INSERT INTO ledger SELECT g, 'before backup' FROM generate_series(1,1000) g"

echo "== 2. base backup (same command as infra/prod/backup.sh)"
docker run --rm --network ${N}-net -e PGPASSWORD=$PW -v ${N}-archive:/archive $IMG \
  pg_basebackup -h ${N}-src -U postgres -D /archive/base/drill -Ft -z -X none
psql_src "INSERT INTO ledger SELECT g, 'after backup' FROM generate_series(1001,1500) g"
psql_src "SELECT pg_switch_wal()" >/dev/null
sleep 2
TARGET=$(psql_src "SELECT now()")
sleep 2
echo "   target time: $TARGET"
echo "== 3. incident after the target: rows deleted"
psql_src "DELETE FROM ledger WHERE id > 200"
psql_src "SELECT pg_switch_wal()" >/dev/null
sleep 3
echo "   rows now in source: $(psql_src 'SELECT count(*) FROM ledger')"
docker stop ${N}-src >/dev/null   # step 2–3 of the runbook: stop writers, keep damaged data

echo "== 4–5. restore into a NEW empty volume, replay WAL to the target, promote"
START=$(date +%s)
docker run --rm -v ${N}-archive:/archive -v ${N}-restored:/var/lib/postgresql $IMG sh -c '
  set -e
  D=/var/lib/postgresql/18/docker
  mkdir -p $D && tar -xzf /archive/base/drill/base.tar.gz -C $D
  chown -R postgres:postgres /var/lib/postgresql && chmod 700 $D'
docker run --rm -v ${N}-restored:/var/lib/postgresql -e TARGET="$TARGET" $IMG sh -c '
  D=/var/lib/postgresql/18/docker
  printf "%s\n" "restore_command = '"'"'cp /archive/wal/%f %p'"'"'" "recovery_target_time = '"'"'$TARGET'"'"'" "recovery_target_action = '"'"'promote'"'"'" >> $D/postgresql.auto.conf
  touch $D/recovery.signal && chown postgres:postgres $D/recovery.signal'
docker run -d --name ${N}-restore -e POSTGRES_PASSWORD=$PW -v ${N}-restored:/var/lib/postgresql -v ${N}-archive:/archive:ro $IMG >/dev/null
until docker exec ${N}-restore pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
until [ "$(docker exec ${N}-restore psql -U postgres -At -c 'SELECT pg_is_in_recovery()')" = "f" ]; do sleep 1; done
END=$(date +%s)

echo "== 6. verify"
COUNT=$(docker exec ${N}-restore psql -U postgres -At -c "SELECT count(*) FROM ledger")
AFTER=$(docker exec ${N}-restore psql -U postgres -At -c "SELECT count(*) FROM ledger WHERE note = 'after backup'")
echo "   restored rows: $COUNT (expected 1500), of which written after the base backup: $AFTER (expected 500)"
echo "   restore took $((END-START)) s"
docker logs ${N}-restore 2>&1 | grep -E "recovery stopping|archive recovery complete|redo done" | head -3
[ "$COUNT" = "1500" ] && [ "$AFTER" = "500" ] && echo "DRILL PASSED" || { echo "DRILL FAILED"; cleanup; exit 1; }
cleanup
