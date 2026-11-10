# ADR 0008 — Package managers, layout, database roles

Status: accepted

- **Python:** uv (lockfile `backend/uv.lock`, `uv sync --frozen` in CI).
- **JavaScript:** pnpm with `save-exact=true` (`frontend/pnpm-lock.yaml`).
  Build scripts of dependencies are disabled by default (`pnpm-workspace.yaml`).
- **Layout:** `backend/` (FastAPI, worker, engine, CLI), `frontend/` (Next.js),
  `infra/`, `docs/` as SPEC §7.
- **Database roles:** `rl_owner` owns the `rl` schema and runs migrations;
  `rl_app` is used by API/worker: not owner, `NOBYPASSRLS`, `NOSUPERUSER`, no
  `UPDATE/DELETE` on `audit_events`, read-only on `platform_admins`. Platform
  admins can only be created via the CLI with the owner role.
- All tables live in schema `rl` (tests drop and recreate it).
