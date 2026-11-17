#!/bin/sh
# Runs in the `backup` container: a compressed base backup every 24 h. Local copies are
# kept 2 days (WAL too); the GCS bucket keeps 30 days via its lifecycle rule.
mkdir -p /archive/base /archive/wal
while true; do
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  if pg_basebackup -h postgres -U postgres -D "/archive/base/$stamp" -Ft -z -X none; then
    echo "base backup $stamp ok"
  else
    echo "base backup $stamp FAILED"
  fi
  find /archive/base -mindepth 2 -type f -mtime +2 -delete
  find /archive/base -mindepth 1 -type d -empty -delete
  find /archive/wal -type f -mmin +2880 -delete
  sleep 86400
done
