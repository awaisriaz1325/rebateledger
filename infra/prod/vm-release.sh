#!/bin/sh
# Runs ON the production VM (ADR 0020), sent over ssh by infra/prod/deploy.sh:
#   sh -s -- <tag> <compose image> deploy     load the uploaded release, migrate, start
#   sh -s -- <tag> <compose image> rollback   start an earlier release still on the VM, no migration
# Layout on the VM: ~/rebateledger/releases/<tag>/ (infra files), ~/rebateledger/current and
# ~/rebateledger/previous (tags), /var/lib/rebateledger/prod.env (secrets, root, mode 600).
set -eu
REF="$1"
COMPOSE_IMAGE="$2"
MODE="$3"
SUDO="${SUDO-sudo}"             # empty only for the local rehearsal
ENV_DIR="${RL_ENV_DIR:-/var/lib/rebateledger}"
EDGE="${RL_EDGE_NETWORK:-opspilot-clinic-frontdesk_default}"
BASE="$HOME/rebateledger"
DIR="$BASE/releases/$REF"
docker_() { $SUDO docker "$@"; }

$SUDO test -f "$ENV_DIR/prod.env" || { echo "missing $ENV_DIR/prod.env (docs/runbooks/deploy.md, first install)"; exit 1; }
docker_ network inspect "$EDGE" >/dev/null 2>&1 || { echo "network $EDGE not found (is OpsPilot running?)"; exit 1; }

if [ "$MODE" = deploy ]; then
  mkdir -p "$BASE/releases"
  rm -rf "$DIR"
  gunzip -c "$HOME/rl-infra.tgz" | tar x -C "$BASE/releases"
  gunzip -c "$HOME/rl-images.tgz" | docker_ load -q
  rm -f "$HOME/rl-infra.tgz" "$HOME/rl-images.tgz"
fi
[ -d "$DIR" ] || { echo "release $REF is not on this VM"; exit 1; }

# Compose runs in a container; the release directory is mounted at the same path so relative
# bind mounts resolve to real host paths (OpsPilot learned this the hard way). stdin is closed:
# this script itself arrives on stdin (sh -s), and a command reading it would eat the rest.
compose() {
  docker_ run --rm -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$DIR:$DIR:ro" -w "$DIR" -v "$ENV_DIR:$ENV_DIR:ro" \
    -e RELEASE="$REF" -e RL_ENV_FILE="$ENV_DIR/prod.env" -e RL_EDGE_NETWORK="$EDGE" \
    "$COMPOSE_IMAGE" docker compose -p rebateledger-prod -f infra/prod/compose.yaml \
    --env-file "$ENV_DIR/prod.env" "$@" </dev/null
}

compose up -d postgres redis
if [ "$MODE" = deploy ]; then
  if compose ps --services --status running | grep -qx backup; then
    compose exec -T backup sh -c 'pg_basebackup -h postgres -U postgres -D /archive/base/predeploy-$(date -u +%Y%m%dT%H%M%SZ) -Ft -z -X none'
  fi
  compose run --rm api alembic upgrade head
fi
compose up -d --remove-orphans

ok=""
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz')" >/dev/null 2>&1 \
    && compose exec -T web node -e "fetch('http://127.0.0.1:3000/login').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 5
done
[ -n "$ok" ] || { echo "smoke check FAILED for $REF: see docs/runbooks/deploy.md (rollback)"; exit 1; }

# Keep this release and the one before it (images and files); remove older ones (disk).
cur=$(cat "$BASE/current" 2>/dev/null || true)
if [ "$cur" != "$REF" ]; then
  [ -n "$cur" ] && echo "$cur" >"$BASE/previous"
  echo "$REF" >"$BASE/current"
fi
prev=$(cat "$BASE/previous" 2>/dev/null || true)
for img in rebateledger-api rebateledger-web; do
  docker_ images "$img" --format '{{.Tag}}' | while read -r t; do
    [ "$t" = "$REF" ] || [ "$t" = "$prev" ] || docker_ rmi "$img:$t" >/dev/null || true
  done
done
for d in "$BASE"/releases/*; do
  t=$(basename "$d")
  [ "$t" = "$REF" ] || [ "$t" = "$prev" ] || rm -rf "$d"
done
echo "release $REF is up"
