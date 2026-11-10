"""RebateLedger rebate engine: pure, deterministic, no I/O.

Public surface:
- ``calculate`` — one agreement-period (SPEC §4.6 entry point)
- ``plan_agreement`` / ``run_jobs`` — periods, version boundaries, stacking
- ``reconcile`` module — credit matching and reconciliation status
"""

from app.engine.calculate import PeriodResult, calculate
from app.engine.planner import PeriodJob, plan_agreement, run_jobs
from app.engine.version import ENGINE_VERSION

__all__ = ["ENGINE_VERSION", "PeriodJob", "PeriodResult", "calculate", "plan_agreement", "run_jobs"]
