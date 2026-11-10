# ADR 0002 — Synchronous SQLAlchemy 2.x with psycopg 3

Status: accepted

## Context
FastAPI supports sync and async handlers. RLS needs a per-transaction tenant
setting, and the engine is CPU-bound pure Python.

## Options
1. **Async SQLAlchemy + asyncpg/psycopg async** — higher concurrency per process,
   but every service, the worker and tests become async; easy to block the loop
   with CPU-bound engine work; more failure modes for transaction scoping.
2. **Sync SQLAlchemy + psycopg 3** — FastAPI runs sync handlers in a threadpool;
   simple, explicit transactions (`Depends(get_db, scope="function")` commits
   before the response is sent); the same code runs in the worker and CLI.

## Decision
Option 2. Each request is one transaction; `set_config('app.tenant_id', …, true)`
is transaction-local so pooled connections never leak context.

## Consequences
Concurrency is bounded by threadpool × processes; scale horizontally (Cloud Run
instances). Revisit only if load tests (Phase 10) show thread exhaustion.
