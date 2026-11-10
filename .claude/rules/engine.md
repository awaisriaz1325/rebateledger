---
paths:
  - "backend/app/engine/**/*.py"
  - "backend/tests/engine/**/*"
---

# Rebate engine rules

The engine is the product. Treat every line here as financial code.

- Pure functions only. No database, filesystem, network, environment variables,
  logging of data, current time, randomness or global mutable state.
- Inputs are immutable, fully validated value objects (frozen dataclasses or
  Pydantic models with `frozen=True`). The engine never reads partial or raw rows.
- All arithmetic uses `decimal.Decimal` inside an explicit local decimal context
  (`decimal.localcontext()`), never the process-global context.
- Full precision internally; round exactly once at the end of each
  agreement-period result, using the rounding mode configured on the agreement.
  Keep both the unrounded and rounded values in the result.
- Every result carries a trace: the measure, eligible/excluded line counts with
  reasons, tier reached, each component's formula with numbers substituted,
  cap/minimum handling, and the final rounding step. A finance user must be able
  to recompute the result by hand from the trace.
- Ambiguity is never resolved silently. Return status `NEEDS_REVIEW` with a
  machine-readable reason code and human-readable message.
- Results are independent of input line order. Add a property test for it.
- Bump `ENGINE_VERSION` on any change that can alter a result, and add a golden
  fixture that demonstrates the change.
- Golden fixtures live in `backend/tests/engine/fixtures/*.yaml`; each one shows
  the hand calculation in a comment block. Never "fix" a fixture to match code
  output without confirming the hand calculation was wrong.
