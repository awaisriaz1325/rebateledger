"""Test configuration. API/DB tests run against the compose Postgres (database
``rebateledger_test``) and Redis (db 15). Engine and pilot tests need neither."""

from __future__ import annotations

import os

os.environ.setdefault("RL_ENV", "test")
os.environ.setdefault("RL_APP_BASE_URL", "https://testserver")
os.environ.setdefault(
    "RL_DATABASE_URL", "postgresql+psycopg://rl_app:local-app-pw@localhost:5442/rebateledger_test"
)
os.environ.setdefault(
    "RL_MIGRATION_DATABASE_URL",
    "postgresql+psycopg://rl_owner:local-owner-pw@localhost:5442/rebateledger_test",
)
os.environ.setdefault("RL_REDIS_URL", "redis://localhost:6382/15")
os.environ.setdefault("RL_TOTP_ENCRYPTION_KEY", "dGVzdC1rZXktdGVzdC1rZXktdGVzdC1rZXktdGVzdDE=")
os.environ.setdefault("RL_SIGNING_KEY", "test-signing-key-0123456789abcdefghijklmnop")
os.environ.setdefault("RL_JOBS_MODE", "inline")
os.environ.setdefault("RL_STORAGE_DIR", "/tmp/rl-test-storage")
