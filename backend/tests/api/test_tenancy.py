"""Tenant isolation at the database layer, as the application role (SPEC §8.1)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from tests.api.conftest import World


@pytest.fixture
def app_conn(owner_engine: object) -> Iterator[Connection]:
    engine = create_engine(
        get_settings().database_url.get_secret_value(),
        connect_args={"options": "-c search_path=rl"},
    )
    with engine.connect() as conn:
        yield conn
    engine.dispose()


TENANT_TABLES = (
    "memberships",
    "invites",
    "support_access_grants",
    "audit_events",
    "idempotency_keys",
    "jobs",
    "notifications",
    "notification_preferences",
    "digest_sends",
    "buying_group_members",
    "sales_lines",
    "spas",
    "spa_items",
    "spa_claims",
    "spa_matches",
)


def test_app_role_is_not_privileged(app_conn: Connection) -> None:
    row = app_conn.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    assert tuple(row) == (False, False)
    owner = app_conn.execute(
        text("SELECT tableowner FROM pg_tables WHERE schemaname='rl' AND tablename='tenants'")
    ).scalar()
    assert owner != "rl_app"


def test_every_tenant_table_has_rls(app_conn: Connection) -> None:
    rows = app_conn.execute(
        text(
            "SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' "
            "WHERE n.nspname = 'rl' AND c.relkind = 'r'"
        )
    ).all()
    assert rows, "no tenant tables found"
    missing = [name for name, rls in rows if not rls]
    assert not missing, f"tenant tables without RLS: {missing}"


def test_direct_sql_sees_only_current_tenant(app_conn: Connection, world: World) -> None:
    a, b = world.tenant("A"), world.tenant("B")
    world.member(a, "viewer")
    world.member(b, "viewer")
    world.member(b, "analyst")
    with app_conn.begin():
        assert app_conn.execute(text("SELECT count(*) FROM rl.memberships")).scalar() == 0
        assert app_conn.execute(text("SELECT count(*) FROM rl.tenants")).scalar() == 0
    with app_conn.begin():
        app_conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a)})
        assert app_conn.execute(text("SELECT count(*) FROM rl.memberships")).scalar() == 1
        assert {r[0] for r in app_conn.execute(text("SELECT id FROM rl.tenants"))} == {a}
        # Even an explicit filter for B returns nothing.
        assert (
            app_conn.execute(
                text("SELECT count(*) FROM rl.memberships WHERE tenant_id = :b"), {"b": b}
            ).scalar()
            == 0
        )
    # Context is transaction-local: it does not leak into the next transaction.
    with app_conn.begin():
        assert app_conn.execute(text("SELECT count(*) FROM rl.memberships")).scalar() == 0


def test_cannot_write_into_another_tenant(app_conn: Connection, world: World) -> None:
    a, b = world.tenant("A"), world.tenant("B")
    uid, _ = world.user("x@example.com")
    with pytest.raises(DBAPIError, match="row-level security"), app_conn.begin():
        app_conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a)})
        app_conn.execute(
            text(
                "INSERT INTO rl.memberships (id, tenant_id, user_id, role, status) VALUES (:i, :b, :u, 'owner', 'active')"
            ),
            {"i": uuid.uuid7(), "b": b, "u": uid},
        )
    world.member(b, "viewer")
    with app_conn.begin():
        app_conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a)})
        changed = app_conn.execute(
            text("UPDATE rl.memberships SET role = 'owner' WHERE tenant_id = :b"), {"b": b}
        ).rowcount
        assert changed == 0


def test_audit_log_is_append_only(app_conn: Connection, world: World) -> None:
    a = world.tenant("A")
    for stmt in ("UPDATE rl.audit_events SET action = 'x'", "DELETE FROM rl.audit_events"):
        with pytest.raises(DBAPIError, match="permission denied"), app_conn.begin():
            app_conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a)})
            app_conn.execute(text(stmt))


def test_app_role_cannot_create_platform_admins(app_conn: Connection, world: World) -> None:
    uid, _ = world.user("y@example.com")
    with pytest.raises(DBAPIError, match="permission denied"), app_conn.begin():
        app_conn.execute(text("INSERT INTO rl.platform_admins (user_id) VALUES (:u)"), {"u": uid})


def test_platform_context_reads_metadata_but_not_memberships_writes(
    app_conn: Connection, world: World
) -> None:
    a = world.tenant("A")
    with app_conn.begin():
        app_conn.execute(text("SELECT set_config('app.platform_admin', 'on', true)"))
        assert app_conn.execute(text("SELECT count(*) FROM rl.tenants")).scalar() == 1
    with pytest.raises(DBAPIError, match="row-level security"), app_conn.begin():
        app_conn.execute(text("SELECT set_config('app.platform_admin', 'on', true)"))
        uid = world.user("z@example.com")[0]
        app_conn.execute(
            text(
                "INSERT INTO rl.memberships (id, tenant_id, user_id, role, status) VALUES (:i, :a, :u, 'owner', 'active')"
            ),
            {"i": uuid.uuid7(), "a": a, "u": uid},
        )


def test_invite_lookup_function_reveals_only_tenant_id(app_conn: Connection, world: World) -> None:
    a = world.tenant("A")
    h = b"\x01" * 32
    world.sql(
        "INSERT INTO rl.invites (id, tenant_id, email, role, token_hash, expires_at) VALUES (:i, :t, 'i@example.com', 'viewer', :h, now() + interval '1 day')",
        i=uuid.uuid7(),
        t=a,
        h=h,
    )
    with app_conn.begin():
        assert app_conn.execute(text("SELECT rl.invite_tenant(:h)"), {"h": h}).scalar() == a
        assert (
            app_conn.execute(text("SELECT rl.invite_tenant(:h)"), {"h": b"\x02" * 32}).scalar()
            is None
        )
        assert app_conn.execute(text("SELECT count(*) FROM rl.invites")).scalar() == 0
