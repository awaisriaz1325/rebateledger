#!/bin/sh
# Lets the `backup` container take base backups over the stack network (pg_basebackup needs a
# replication connection; the official image only allows those locally). Limited to the stack's
# private subnet and password-authenticated. Found by the 2026-11-20 restore drill: without it the
# nightly base backups fail and point-in-time restore is impossible. Runs once, on a new volume.
set -eu
echo "host replication postgres ${REPLICATION_CIDR:-172.31.250.0/24} scram-sha-256" >> "$PGDATA/pg_hba.conf"
