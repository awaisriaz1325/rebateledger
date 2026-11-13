"""Import every module that registers job handlers.

The worker (`make worker`) loads only `app.workers.broker` and this module, so
each module with an `@handler(...)` must be imported here.
`tests/test_worker_registry.py` fails if a job type has no handler in that process.
"""

from __future__ import annotations

# Imported for their side effect (handler registration); `--fix` must not remove them.
import app.emails.service
import app.exports.service
import app.services.audit
import app.services.billing
import app.services.imports
import app.services.notifications
import app.services.runs
import app.services.spa  # noqa: F401
