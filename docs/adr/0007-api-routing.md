# ADR 0007 — `/api` routing: Next.js rewrites to FastAPI

Status: accepted

## Context
The browser must talk to one origin (SPEC §7) so the `__Host-` session cookie is
first-party and there is no CORS.

## Options
1. **Next.js `rewrites()`** in every environment: the Next server proxies
   `/api/*` to the internal FastAPI URL (`RL_API_ORIGIN`, server-side only).
2. **Load balancer path routing** (GCP HTTPS LB: `/api/*` → API service, rest → web).

## Decision
Option 1 for local and staging (no extra infrastructure); Option 2 is preferred for
production because it removes a hop and isolates failures. Phase 11 prices both;
the app works unchanged under either because all API paths are absolute `/api/v1/...`.

## Consequences
- FastAPI sees the Next server as the client; uvicorn runs with
  `--proxy-headers --forwarded-allow-ips=<web service>` so rate limits use the real IP.
- The CSRF Origin check compares against `RL_APP_BASE_URL` (the public origin).
