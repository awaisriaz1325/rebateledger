#!/bin/sh
# Creates the two database roles described in ADR 0008:
#   rl_owner — owns schema objects, runs migrations
#   rl_app   — used by the API and worker; NOT owner, NOBYPASSRLS, so RLS always applies
set -eu
psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
  -v owner_pw="$RL_OWNER_PASSWORD" -v app_pw="$RL_APP_PASSWORD" <<'SQL'
CREATE ROLE rl_owner LOGIN PASSWORD :'owner_pw' NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
CREATE ROLE rl_app   LOGIN PASSWORD :'app_pw'   NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS;
CREATE DATABASE rebateledger OWNER rl_owner;
CREATE DATABASE rebateledger_test OWNER rl_owner;
SQL
for db in rebateledger rebateledger_test; do
  psql -v ON_ERROR_STOP=1 -U postgres -d "$db" <<SQL
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO rl_owner;
GRANT USAGE ON SCHEMA public TO rl_app;
REVOKE CREATE, TEMPORARY ON DATABASE $db FROM PUBLIC;
GRANT CONNECT ON DATABASE $db TO rl_app;
SQL
done
