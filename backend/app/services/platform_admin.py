"""Platform-admin bootstrap (SPEC §2.2). Runs with the owner role: the application
role cannot insert into platform_admins, so no web request can create one."""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.security import hash_password, password_problem
from app.db.models.identity import PlatformAdmin, User
from app.services.audit import Actor, record
from app.services.auth import normalise_email


class PlatformAdminError(Exception):
    pass


def create_platform_admin(email: str, name: str, password: str) -> uuid.UUID:
    email = normalise_email(email)
    problem = password_problem(password, email=email, name=name)
    if problem:
        raise PlatformAdminError(problem)
    url = get_settings().migration_database_url
    if url is None:
        raise PlatformAdminError(
            "RL_MIGRATION_DATABASE_URL (owner role) is required for this command"
        )
    engine = create_engine(url.get_secret_value(), hide_parameters=True)
    try:
        with Session(engine) as db, db.begin():
            user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if user is None:
                user = User(
                    email=email,
                    name=name,
                    password_hash=hash_password(password),
                    email_verified_at=utcnow(),
                    password_changed_at=utcnow(),
                )
                db.add(user)
                db.flush()
            if db.get(PlatformAdmin, user.id) is None:
                db.add(PlatformAdmin(user_id=user.id))
            record(
                db,
                tenant_id=None,
                actor=Actor.system("cli"),
                action="platform_admin.created",
                object_type="user",
                object_id=user.id,
            )
            return user.id
    finally:
        engine.dispose()
