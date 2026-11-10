"""`rebateledger` command-line interface.

Subcommands:
  pilot                  run a reconciliation from files (Phase 1 concierge pilots)
  create-platform-admin  bootstrap an operator account (Phase 2)
  seed-demo              load a realistic demo tenant (Phase 3)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

Handler = Callable[[argparse.Namespace], int]
_EXTRA: list[Callable[[argparse._SubParsersAction[argparse.ArgumentParser]], None]] = []


def register(fn: Callable[[argparse._SubParsersAction[argparse.ArgumentParser]], None]) -> None:
    """Later modules add subcommands without this file importing web or DB code."""
    _EXTRA.append(fn)


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a YYYY-MM-DD date") from None


def _coverage(text: str) -> tuple[str, date]:
    supplier, sep, d = text.partition("=")
    if not sep or not supplier:
        raise argparse.ArgumentTypeError("use SUPPLIER=YYYY-MM-DD")
    return supplier, _date(d)


def _pilot(args: argparse.Namespace) -> int:
    from app.pilot.report import summary_text, write_outputs
    from app.pilot.run import PilotError, PilotInputs, run_pilot

    inputs = PilotInputs(
        agreements=args.agreements,
        purchases=args.purchases,
        credits=args.credits,
        mapping=args.mapping,
        range_start=args.date_from,
        range_end=args.date_to,
        as_of=args.as_of,
        baselines=args.baselines,
        allocations=args.allocations,
        resolutions=args.resolutions,
        coverage_overrides=dict(args.coverage_start or []),
        skip_invalid=args.skip_invalid,
    )
    try:
        outcome = run_pilot(inputs)
    except PilotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    written = write_outputs(outcome, args.out)
    print(summary_text(outcome))
    print("Wrote: " + ", ".join(str(p) for p in written))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rebateledger", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pilot", help="reconcile rebates from agreement YAML + CSV exports")
    p.add_argument("--agreements", type=Path, required=True, help="agreements YAML")
    p.add_argument("--purchases", type=Path, required=True, help="purchase lines CSV")
    p.add_argument("--credits", type=Path, required=True, help="supplier credits CSV")
    p.add_argument("--mapping", type=Path, required=True, help="column mapping + formats YAML")
    p.add_argument("--baselines", type=Path, help="baselines CSV (growth agreements)")
    p.add_argument("--allocations", type=Path, help="manual credit allocations CSV")
    p.add_argument("--resolutions", type=Path, help="version-change resolutions YAML")
    p.add_argument(
        "--from", dest="date_from", type=_date, required=True, help="first day of the range"
    )
    p.add_argument("--to", dest="date_to", type=_date, required=True, help="last day of the range")
    p.add_argument(
        "--as-of",
        type=_date,
        required=True,
        help="the date statuses are judged on (in the customer's timezone)",
    )
    p.add_argument(
        "--coverage-start",
        type=_coverage,
        action="append",
        metavar="SUPPLIER=DATE",
        help="purchase data for SUPPLIER is complete from DATE (repeatable)",
    )
    p.add_argument(
        "--skip-invalid", action="store_true", help="skip invalid rows instead of stopping"
    )
    p.add_argument("--out", type=Path, required=True, help="output directory")
    p.set_defaults(handler=_pilot)

    for fn in _EXTRA:
        fn(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
