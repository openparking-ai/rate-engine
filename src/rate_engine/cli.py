"""The CLI. The same two operations, because an operator testing a rate should
not need an HTTP client.

**This is not a simulation mode.** `rate-engine quote` builds the same request
object `/v1/quote` builds and hands it to the same function, `contract.run_quote`.
The bytes it prints in `--json` mode are the bytes the route returns. That is
F6, and F6 is the control that matters most here: a test function that answers
differently from the production path is a tool that tells an operator their
garage will charge something it will not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contract import SCHEMA_VERSION, breakdown_text, run_quote, run_validate
from .money import format_minor


def _load(path: str) -> object:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text())


def _cmd_quote(args) -> int:
    plans = _load(args.plan)
    request = {
        "plans": plans if isinstance(plans, list) else [plans],
        "entry_at": args.entry,
        "exit_at": args.exit,
        "space_class": args.space_class,
        "currency": args.currency,
    }
    status, body = run_quote(request)
    if args.json:
        print(json.dumps(body, indent=2))
        return 0 if status == 200 else 1

    if status == 200:
        print(f"\n  plan {body['plan_version']}")
        from .breakdown import Ledger, Line

        ledger = Ledger([Line(**line) for line in body["breakdown"]])
        print(breakdown_text(ledger, body["currency"]))
        print(f"\n  FEE  {format_minor(body['fee_minor'], body['currency'])}\n")
        return 0
    if body.get("refused"):
        print("\n  REFUSED -- nothing was guessed.\n")
        for finding in body["findings"]:
            print(f"    [{finding['kind']}] {finding['code']}")
            print(f"      {finding['text']}\n")
        return 1
    print(f"\n  the request could not be read: {body['error']}\n")
    return 2


def _cmd_validate(args) -> int:
    status, body = run_validate({"plan": _load(args.plan)})
    if args.json:
        print(json.dumps(body, indent=2))
        return 0 if status == 200 else 1
    if status != 200:
        print(f"\n  the plan could not be read: {body['error']}\n")
        return 2
    if not body["findings"]:
        print(f"\n  plan {body['plan_version']}: no gaps, no conflicts.\n")
        return 0
    print(
        f"\n  plan {body['plan_version']}: {body['gaps']} gap(s), "
        f"{body['conflicts']} conflict(s)"
    )
    print("  Each one is a decision for the owner. The engine will refuse a stay that")
    print("  hits an undecided gap rather than invent a fee for it.\n")
    for finding in body["findings"]:
        print(f"    [{finding['kind']}] {finding['code']}")
        print(f"      {finding['text']}\n")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rate-engine",
        description=(
            "Price a parking stay and explain every line of the answer. "
            f"Contract schema v{SCHEMA_VERSION}. Calculation only -- this takes no payment."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    q = sub.add_parser("quote", help="price a stay (the same path /v1/quote uses)")
    q.add_argument("--plan", required=True, help="a plan document, or a list of versions, or '-'")
    q.add_argument(
        "--entry", required=True,
        help="ISO 8601 with an offset, e.g. 2026-03-03T09:14:00-05:00",
    )
    q.add_argument("--exit", required=True, dest="exit", help="ISO 8601 with an offset")
    q.add_argument("--space-class", required=True)
    q.add_argument("--currency", required=True)
    q.add_argument("--json", action="store_true", help="the exact bytes /v1/quote returns")
    q.set_defaults(func=_cmd_quote)

    v = sub.add_parser("validate-plan", help="list a plan's gaps and conflicts")
    v.add_argument("--plan", required=True)
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=_cmd_validate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
