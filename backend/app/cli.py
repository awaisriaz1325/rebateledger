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

    a = sub.add_parser(
        "create-platform-admin",
        help="create an operator account (MFA set-up is forced at first sign-in)",
    )
    a.add_argument("--email", required=True)
    a.add_argument("--name", required=True)
    a.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from stdin instead of prompting",
    )
    a.set_defaults(handler=_create_platform_admin)

    s = sub.add_parser(
        "seed-demo", help="create the demo tenant with realistic fake data (local/staging only)"
    )
    s.add_argument("--purchase-lines", type=int, default=100_000)
    s.add_argument("--owner-email", default="demo.owner@example.com")
    s.set_defaults(handler=_seed_demo)

    e = sub.add_parser(
        "seed-e2e", help="create a fresh tenant and MFA-enrolled users for E2E tests (local only)"
    )
    e.add_argument("--out", required=True, help="write the throwaway credentials (JSON) here")
    e.set_defaults(handler=_seed_e2e)
    return parser


def _create_platform_admin(args: argparse.Namespace) -> int:
    import getpass

    from app.services.platform_admin import PlatformAdminError, create_platform_admin

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            print("error: passwords do not match", file=sys.stderr)
            return 2
    try:
        create_platform_admin(args.email, args.name, password)
    except PlatformAdminError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("Platform admin created. Sign in to set up two-factor authentication (required).")
    return 0


def _seed_demo(args: argparse.Namespace) -> int:
    from app.services.seed import seed_demo

    print(seed_demo(purchase_lines=args.purchase_lines, owner_email=args.owner_email))
    return 0


def _seed_e2e(args: argparse.Namespace) -> int:
    import json
    import os
    from pathlib import Path

    from app.services.e2e_seed import seed_e2e

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(seed_e2e(), fh)
    print(f"E2E tenant created; credentials written to {out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
