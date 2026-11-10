# RebateLedger task runner. Run `make help` for the list.
# Backend env: backend/.env if present, else the dummy values in backend/.env.example.
SHELL := /bin/bash
.DEFAULT_GOAL := help
BACKEND_ENV := $(if $(wildcard backend/.env),.env,.env.example)
WITH_ENV := set -a && . ./$(BACKEND_ENV) && set +a &&
COMPOSE := docker compose

.PHONY: help setup up down ps check check-backend check-frontend lint types test test-backend test-frontend \
        e2e coverage-engine migrate migration seed api worker scheduler web pilot-sample openapi \
        audit secrets sast ci

help: ## Show this help
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies and create local env files (dummy values)
	@test -f .env || cp .env.example .env
	cd backend && uv sync --frozen
	cd frontend && pnpm install --frozen-lockfile

up: ## Start Postgres, Redis and Mailpit (waits for health checks)
	$(COMPOSE) up -d --wait

down: ## Stop the local stack (data volumes are kept)
	$(COMPOSE) down

ps: ## Show local stack health
	$(COMPOSE) ps

check: check-backend check-frontend ## Lint + types + all non-E2E tests (the phase gate)

check-backend: ## Backend: ruff, ruff format check, mypy strict, pytest (+ engine coverage gate)
	cd backend && uv run ruff check app tests migrations scripts
	cd backend && uv run ruff format --check app tests migrations scripts
	cd backend && uv run mypy app tests scripts migrations
	cd backend && uv run pytest -q --cov=app --cov-branch --cov-report=term:skip-covered --cov-fail-under=85
	$(MAKE) coverage-engine

coverage-engine: ## Engine must keep >= 95% line+branch coverage
	cd backend && uv run pytest -q tests/engine --cov=app/engine --cov-branch --cov-report=term --cov-fail-under=95

check-frontend: ## Frontend: eslint, tsc, vitest, OpenAPI client drift check
	cd frontend && pnpm lint --max-warnings=0
	cd frontend && pnpm typecheck
	cd frontend && pnpm test
	$(MAKE) openapi && git diff --exit-code -- frontend/generated || (echo "Generated API client is out of date: run 'make openapi' and commit." && exit 1)

test-backend: ## Backend tests only
	cd backend && uv run pytest -q

test-frontend: ## Frontend unit/component tests only
	cd frontend && pnpm test

e2e: ## Playwright end-to-end tests (starts API + web; needs `make up` and `make migrate`)
	cd frontend && pnpm e2e

openapi: ## Regenerate frontend/generated/api.ts from the backend OpenAPI schema
	cd backend && $(WITH_ENV) uv run python -m app.openapi > ../frontend/generated/openapi.json
	cd frontend && pnpm exec openapi-typescript generated/openapi.json -o generated/api.ts

migrate: ## Apply database migrations (owner role)
	cd backend && $(WITH_ENV) uv run alembic upgrade head

migration: ## Create a migration: make migration name="add widgets"
	@test -n "$(name)" || (echo 'usage: make migration name="what changed"' && exit 2)
	cd backend && $(WITH_ENV) uv run alembic revision --autogenerate -m "$(name)"

seed: ## Load the demo tenant (local only)
	cd backend && $(WITH_ENV) uv run rebateledger seed-demo

api: ## Run the API on :8000 with reload
	cd backend && $(WITH_ENV) uv run uvicorn app.asgi:app --reload --port 8000

worker: ## Run the background worker
	cd backend && $(WITH_ENV) uv run dramatiq app.workers.broker app.services.registry --processes 1 --threads 4

scheduler: ## Run the periodic scheduler
	cd backend && $(WITH_ENV) uv run python -m app.workers.scheduler

web: ## Run the Next.js dev server on :3000
	cd frontend && pnpm dev

pilot-sample: ## Run the pilot CLI on docs/pilot-samples into var/pilot-sample
	cd backend && uv run rebateledger pilot --agreements ../docs/pilot-samples/agreements.yaml \
	  --purchases ../docs/pilot-samples/purchases.csv --credits ../docs/pilot-samples/credits.csv \
	  --mapping ../docs/pilot-samples/mapping.yaml --baselines ../docs/pilot-samples/baselines.csv \
	  --allocations ../docs/pilot-samples/allocations.csv --resolutions ../docs/pilot-samples/resolutions.yaml \
	  --from 2026-01-01 --to 2026-06-30 --as-of 2026-09-15 --out ../var/pilot-sample

audit: ## Dependency vulnerability audit (Python + JS)
	cd backend && uv export --frozen --no-hashes --no-emit-project > ../var/requirements-audit.txt && uv run pip-audit -r ../var/requirements-audit.txt --strict
	cd frontend && pnpm audit --audit-level high

secrets: ## Secret scan of the working tree and history (gitleaks in Docker)
	docker run --rm -v "$$PWD:/repo" ghcr.io/gitleaks/gitleaks:v8.30.1 git /repo --redact --no-banner

sast: ## Static analysis (bandit for Python)
	cd backend && uv run bandit -q -c pyproject.toml -r app

ci: check audit sast ## Everything CI runs except the Docker-based secret scan
