"""The worker process loads only `app.workers.broker` and `app.services.registry`
(see `make worker`). Every job type must have a handler in exactly that process,
otherwise jobs fail at runtime (regression: send_email KeyError in the worker)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

EXPECTED = {
    "billing_lapse",
    "build_export",
    "calculation_run",
    "expire_exports",
    "claim_reminders",
    "import_commit",
    "import_validate",
    "send_email",
    "tier_alerts",
    "verify_audit_chain",
}


def test_worker_modules_register_every_job_handler() -> None:
    code = (
        "import json, app.workers.broker, app.services.registry\n"
        "from app.workers.jobs import HANDLERS\n"
        "print(json.dumps(sorted(HANDLERS)))\n"
    )
    out = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "RL_JOBS_MODE": "inline"},
    )
    assert set(json.loads(out.stdout.strip().splitlines()[-1])) >= EXPECTED
