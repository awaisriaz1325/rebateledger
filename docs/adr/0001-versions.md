# ADR 0001 — Pinned versions (verified 2026-11-10)

Status: accepted

Every version below was read from the official registry or project source on
2026-11-10 (not from memory) and is pinned in `backend/uv.lock`,
`frontend/pnpm-lock.yaml`, `docker-compose.yml` and `.github/workflows/ci.yml`.

| Component | Version | Source checked |
|---|---|---|
| Python | 3.14.10 | `uv python list` (python.org builds); 3.15 exists but native-wheel deps (psycopg, WeasyPrint stack, cryptography) were validated on 3.14 |
| Node.js | 26.13.0 (Active LTS since 2026-10-28) | https://endoflife.date/api/nodejs.json |
| PostgreSQL | 18.6 (`postgres:18.6-alpine`) | https://endoflife.date/api/postgresql.json, Docker Hub tags |
| Redis | 8.10.3 (`redis:8.10.3-alpine`) | https://endoflife.date/api/redis.json, Docker Hub tags |
| Mailpit | v1.33.1 | Docker Hub `axllent/mailpit` tags |
| FastAPI | 0.162.4 | https://pypi.org/pypi/fastapi/json |
| Pydantic / pydantic-settings | 2.14.3 / 2.16.2 | PyPI JSON API |
| SQLAlchemy / Alembic | 2.1.8 / 1.20.1 | PyPI JSON API |
| psycopg | 3.3.8 | PyPI JSON API |
| Dramatiq / redis-py | 2.2.1 / 8.1.0 | PyPI JSON API |
| argon2-cffi / pyotp / cryptography | 25.1.0 / 2.10.0 / 50.0.2 | PyPI JSON API |
| WeasyPrint | 70.0 | PyPI JSON API; render verified locally |
| openpyxl / defusedxml | 3.1.5 / (lock) | PyPI JSON API |
| uv | 0.13.6 (local) | `uv --version` |
| Ruff / mypy / pytest / hypothesis | 0.17.4 / 2.4.1 / 9.2.0 / 6.170.15 | PyPI JSON API |
| bandit / pip-audit | 1.9.4 / 2.10.1 | PyPI JSON API |
| Next.js / React | 16.4.6 / 19.3.0 | `npm view next`, `create-next-app@16.4.6` |
| TypeScript | 5.9.3 | Chosen by `create-next-app@16.4.6`. TS 7.0.2 (native compiler) is `latest` on npm but Next.js tooling scaffolds 5.x; revisit when Next documents TS 7 support |
| ESLint / eslint-config-next | 9.39.5 / 16.4.6 | scaffolded by create-next-app |
| Tailwind CSS | 4.3.3 | scaffolded |
| TanStack Query / Table / Virtual | 5.107.1 / 9.3.1 / 3.14.26 | `npm view` |
| openapi-typescript / openapi-fetch | 7.13.0 / 0.17.0 | `npm view` |
| Vitest / Playwright / axe-core playwright | 5.1.0 / 1.65.0 / 4.14.0 | `npm view` |
| GitHub Actions | checkout v7.0.1, setup-uv v10.3.3, pnpm/action-setup v6.1.1, setup-node v7.1.0, upload-artifact v7.0.2 | `gh api repos/<repo>/releases/latest` |
| gitleaks | v8.30.1 | GitHub releases |
| OWASP ASVS | 5.0.0 (target for Phase 10 mapping) | UNVERIFIED in this session — confirm at https://owasp.org/www-project-application-security-verification-standard/ in Phase 10 |

Dependabot (weekly) proposes upgrades; each upgrade must pass the full check suite.
