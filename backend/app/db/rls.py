"""SQL for Row-Level Security policies and grants, used by migrations.

Table names passed here are compile-time constants from migrations, never user
input. Policies read the transaction-local settings written by
``app.db.session.set_*_context``.
"""

from __future__ import annotations

from collections.abc import Callable

TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
USER = "NULLIF(current_setting('app.user_id', true), '')::uuid"
PLATFORM = "current_setting('app.platform_admin', true) = 'on'"

Execute = Callable[[str], object]


def enable_tenant_rls(execute: Execute, table: str, platform_read: bool = False) -> None:
    """Rows are visible/writable only inside their tenant's context.

    ``platform_read`` additionally lets platform admins *read* rows (metadata tables only).
    """
    execute(f"ALTER TABLE rl.{table} ENABLE ROW LEVEL SECURITY")
    execute(
        f"CREATE POLICY tenant_isolation ON rl.{table} "
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})"
    )
    if platform_read:
        execute(f"CREATE POLICY platform_read ON rl.{table} FOR SELECT USING ({PLATFORM})")


def grant_app(
    execute: Execute, table: str, privileges: str = "SELECT, INSERT, UPDATE, DELETE"
) -> None:
    execute(f"GRANT {privileges} ON rl.{table} TO rl_app")
