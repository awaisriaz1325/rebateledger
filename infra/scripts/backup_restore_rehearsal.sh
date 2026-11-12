#!/usr/bin/env bash
# Backup and restore rehearsal against the LOCAL docker-compose database (PHASES §10.6).
# Dumps `rebateledger`, restores it into a scratch database, compares every table's row
# count, re-verifies every audit hash chain in the restored copy, then drops the scratch
# database. Never touches the source database. Not for cloud use (see docs/runbooks).
set -euo pipefail
cd "$(dirname "$0")/../.."

SRC=rebateledger
DST=rebateledger_restore_rehearsal
PSQL=(docker compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -At)

echo "1. Dump (custom format, compressed)"
start=$(date +%s)
docker compose exec -T postgres pg_dump -U postgres -Fc -d "$SRC" -f /tmp/rehearsal.dump
size=$(docker compose exec -T postgres stat -c %s /tmp/rehearsal.dump)
echo "   dump size: $size bytes in $(( $(date +%s) - start )) s"

echo "2. Restore into scratch database $DST"
"${PSQL[@]}" -c "DROP DATABASE IF EXISTS $DST" >/dev/null
"${PSQL[@]}" -c "CREATE DATABASE $DST" >/dev/null
start=$(date +%s)
docker compose exec -T postgres pg_restore -U postgres --exit-on-error -d "$DST" /tmp/rehearsal.dump
echo "   restored in $(( $(date +%s) - start )) s"

echo "3. Row counts per table (source vs restore)"
COUNT_SQL="SELECT string_agg(format('%s=%s', c.relname, (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM rl.%I', c.relname), false, true, '')))[1]::text), ',' ORDER BY c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'rl' AND c.relkind = 'r'"
src_counts=$("${PSQL[@]}" -d "$SRC" -c "$COUNT_SQL")
dst_counts=$("${PSQL[@]}" -d "$DST" -c "$COUNT_SQL")
tables=$(echo "$src_counts" | tr ',' '\n' | wc -l)
if [ "$src_counts" = "$dst_counts" ]; then echo "   all $tables tables match"; else echo "   MISMATCH"; diff <(echo "$src_counts" | tr ',' '\n') <(echo "$dst_counts" | tr ',' '\n'); exit 1; fi
echo "   largest: $(echo "$dst_counts" | tr ',' '\n' | sort -t= -k2 -n -r | head -3 | tr '\n' ' ')"

echo "4. Audit hash chains in the restored copy"
(cd backend && set -a && . ./.env.example && set +a && \
  RL_MIGRATION_DATABASE_URL="postgresql+psycopg://rl_owner:local-owner-pw@localhost:5442/$DST" \
  uv run python - <<'PY'
import os
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.db.models.identity import AuditEvent
from app.services.audit import verify_chain

engine = create_engine(os.environ["RL_MIGRATION_DATABASE_URL"])
with Session(engine) as db:
    chains = list(db.execute(select(AuditEvent.chain_key).distinct()).scalars())
    results = [verify_chain(db, c) for c in chains]
bad = [r for r in results if not r.ok]
print(f"   {len(results)} chains, {sum(r.events for r in results)} events, broken: {len(bad)}")
raise SystemExit(1 if bad else 0)
PY
)

echo "5. Clean up"
"${PSQL[@]}" -c "DROP DATABASE $DST" >/dev/null
docker compose exec -T postgres rm -f /tmp/rehearsal.dump
echo "Rehearsal passed."
