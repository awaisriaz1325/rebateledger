#!/usr/bin/env bash
# Deploy one release to production (ADR 0020). Run by a person ON THE DEVBOX, from the repo,
# at a git tag:   infra/prod/deploy.sh v1.3.0
#
# Images are built HERE, never on the VM: an on-VM build used up opspilot-production's memory
# and took OpsPilot down on 2026-11-20. The images and the infra files the stack mounts are
# copied to the VM over IAP, then infra/prod/vm-release.sh runs there:
# pre-deploy base backup -> migrate -> start -> smoke check.
# Rollback: docs/runbooks/deploy.md.
set -euo pipefail
cd "$(dirname "$0")/../.."
REF="${1:?usage: infra/prod/deploy.sh <git tag>}"
VM=opspilot-production
ZONE=us-central1-a
SITE_URL=https://rebateledger.imageme.tech
# Docker CLI image with the compose plugin, run on the VM (Container-Optimized OS has no
# runnable compose). Verified 2026-11-20: docker:29.1.3-cli ships Docker Compose v5.0.0.
COMPOSE_IMAGE=docker:29.1.3-cli

git rev-parse -q --verify "refs/tags/$REF" >/dev/null || { echo "$REF is not a git tag"; exit 1; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git archive "$REF" | tar x -C "$work"

echo "building rebateledger-api:$REF and rebateledger-web:$REF"
docker build -q -t "rebateledger-api:$REF" "$work/backend" >/dev/null
docker build -q -t "rebateledger-web:$REF" --build-arg RL_API_ORIGIN=http://api:8000 \
  --build-arg NEXT_PUBLIC_SITE_URL="$SITE_URL" "$work/frontend" >/dev/null
docker save "rebateledger-api:$REF" "rebateledger-web:$REF" | gzip -1 >"$work/rl-images.tgz"
# Only the files the stack mounts at run time (compose file, scripts, Postgres init).
git archive --prefix="$REF/" "$REF" infra/prod infra/postgres | gzip >"$work/rl-infra.tgz"

echo "uploading $(du -h "$work/rl-images.tgz" | cut -f1) of images to $VM"
gcloud compute scp --zone "$ZONE" --tunnel-through-iap \
  "$work/rl-images.tgz" "$work/rl-infra.tgz" "$VM:~/"
# The release script is sent on stdin: /home is mounted noexec on the VM.
gcloud compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap \
  --command "sh -s -- '$REF' '$COMPOSE_IMAGE' deploy" <infra/prod/vm-release.sh
docker rmi "rebateledger-api:$REF" "rebateledger-web:$REF" >/dev/null 2>&1 || true  # local copies
echo "check from outside: curl -sI $SITE_URL/login"
