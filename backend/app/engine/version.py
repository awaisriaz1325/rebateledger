"""Engine version. Bump on ANY change that can alter a result, and add a golden
fixture demonstrating the change (see .claude/rules/engine.md)."""

ENGINE_VERSION = "1.2.0"
"""1.1.0 (v1.1 Phase 16): buying-group programs read lines of member suppliers
(fixtures 41–43). Results of every supplier agreement are unchanged, including input_hash.
1.2.0 (v1.1 Phase 17): SPA / ship-and-debit matcher (app/engine/spa.py, tests/engine/test_spa.py).
Rebate results are unchanged."""
