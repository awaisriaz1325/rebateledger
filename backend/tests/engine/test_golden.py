"""Golden fixtures: hand-calculated expected values (see each YAML's header comment)."""

from __future__ import annotations

import pytest

from tests.engine.golden import Fixture, check, load_all, run_fixture

FIXTURES = load_all()


def test_at_least_thirty_fixtures() -> None:
    assert len(FIXTURES) >= 30


def test_every_fixture_has_hand_calculation() -> None:
    for fx in FIXTURES:
        head = fx.path.read_text(encoding="utf-8").splitlines()[0]
        assert head.startswith("# HAND CALCULATION"), fx.path.name


@pytest.mark.parametrize("fx", FIXTURES, ids=[f.path.stem for f in FIXTURES])
def test_golden(fx: Fixture) -> None:
    problems = check(fx, run_fixture(fx))
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("fx", FIXTURES, ids=[f.path.stem for f in FIXTURES])
def test_golden_is_order_independent(fx: Fixture) -> None:
    """Reversing every input list must give byte-identical results (SPEC §9 case 12)."""
    raw = dict(fx.raw)
    raw["purchases"] = list(reversed(raw.get("purchases", []) or []))
    raw["baselines"] = list(reversed(raw.get("baselines", []) or []))
    a = run_fixture(fx)
    b = run_fixture(Fixture(fx.path, raw))
    assert a == b
