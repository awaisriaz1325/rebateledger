#!/bin/sh
# Build and roll out one release on the production VM (ADR 0018). Run by a person, from the
# repo root, at a git tag:   infra/prod/deploy.sh v1.1.0
# Order: build images -> take a base backup -> migrate -> start -> smoke check.
# Rollback: docs/runbooks/deploy.md.
set -eu
RELEASE="${1:?usage: infra/prod/deploy.sh <git tag>}"
ENV_FILE=/etc/rebateledger/prod.env
APP_URL=$(sed -n 's/^RL_APP_BASE_URL=//p' "$ENV_FILE")
compose() { RELEASE="$RELEASE" docker compose -p rebateledger-prod -f infra/prod/compose.yaml --env-file "$ENV_FILE" "$@"; }

git diff --quiet || { echo "working tree is dirty; deploy only from a clean tag"; exit 1; }
git checkout --quiet "$RELEASE"

docker build -t "rebateledger-api:$RELEASE" backend
# The web container reaches the API by service name on the stack network.
# The public site URL is baked into the build (canonical links, sitemap).
docker build -t "rebateledger-web:$RELEASE" --build-arg RL_API_ORIGIN=http://api:8000 \
  --build-arg NEXT_PUBLIC_SITE_URL="$APP_URL" frontend

compose up -d postgres redis
if compose ps --services --status running | grep -qx backup; then
  compose exec -T backup sh -c 'pg_basebackup -h postgres -U postgres -D /archive/base/predeploy-$(date -u +%Y%m%dT%H%M%SZ) -Ft -z -X none'
fi
compose run --rm api alembic upgrade head
compose up -d --remove-orphans

for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if curl -fsS "http://127.0.0.1:3200/login" >/dev/null && compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz')"; then
    echo "release $RELEASE is up: $APP_URL"
    exit 0
  fi
  sleep 5
done
echo "smoke check FAILED for $RELEASE: see docs/runbooks/deploy.md (rollback)"
exit 1
