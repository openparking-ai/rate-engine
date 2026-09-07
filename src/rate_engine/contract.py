"""The wire contract: version, request parsing, and ONE serializer.

Every surface -- `/v1/quote`, `/v1/validate-plan` and both CLI commands -- turns
its answer into JSON through the functions here and nowhere else. That is F6's
other half: proving the CLI and the HTTP route both MOVE when the engine changes
is weaker than proving they cannot differ, and a single serializer is what makes
the second statement true.

**Versioning, per §2.** A commercial contract is versioned on the assumption it
will GAIN fields, so consumers must tolerate fields appearing. The consequence
that keeps that safe runs the other way: this engine REJECTS a key it does not
understand and names it, rather than ignoring it. An ignored key is how a plan an
operator believes is live ends up pricing something else.
"""

from __future__ import annotations

import json
import textwrap
from typing import Any

from .breakdown import Ledger
from .engine import Quote, Stay, make_stay, quote
from .findings import Refused
from .money import NotMinorUnits
from .plan import InvalidPlan, load_plan, parse_instant
from .validator import undecided, validate_plan

SCHEMA_VERSION = 1

QUOTE_REQUEST_KEYS = frozenset({"plans", "entry_at", "exit_at", "space_class", "currency"})
VALIDATE_REQUEST_KEYS = frozenset({"plan"})


def _require(document: object, keys: frozenset[str], where: str) -> dict:
    if not isinstance(document, dict):
        raise InvalidPlan(f"{where} must be an object, got {type(document).__name__}.")
    missing = sorted(keys - set(document))
    unknown = sorted(set(document) - keys)
    if missing:
        raise InvalidPlan(f"{where} is missing required field(s): {', '.join(missing)}.")
    if unknown:
        raise InvalidPlan(
            f"{where} carries key(s) this version does not understand: "
            f"{', '.join(unknown)}. Rejected, not ignored."
        )
    return document


def parse_quote_request(document: object) -> tuple[list, Stay]:
    """Parse a quote request into plans and a stay.

    `plans` is a LIST because the entry-time rule needs something to choose
    between: the plan in force at entry prices the whole stay, and an engine
    handed exactly one plan can never demonstrate that it chose by entry rather
    than by exit. One element is the ordinary case and is fine. Nothing is stored
    -- the versions arrive on the call, and a plan STORE is round B.
    """
    body = _require(document, QUOTE_REQUEST_KEYS, "request")

    raw_plans = body["plans"]
    if not isinstance(raw_plans, list) or not raw_plans:
        raise InvalidPlan("request.plans must be a non-empty list of plan documents.")
    plans = [load_plan(p, f"request.plans[{i}]") for i, p in enumerate(raw_plans)]

    currency = body["currency"]
    wrong = sorted({p.currency for p in plans if p.currency != currency})
    if wrong:
        raise InvalidPlan(
            f"request.currency is {currency!r} but a plan prices in {', '.join(wrong)}. "
            "The engine will not convert; a rate quoted in the wrong currency is a "
            "wrong number that looks right."
        )
    versions = [p.plan_version for p in plans]
    if len(set(versions)) != len(versions):
        raise InvalidPlan("request.plans contains two versions with the same plan_version.")

    stay = make_stay(
        parse_instant(body["entry_at"], "request.entry_at"),
        parse_instant(body["exit_at"], "request.exit_at"),
        body["space_class"],
    )
    return plans, stay


def parse_validate_request(document: object):
    body = _require(document, VALIDATE_REQUEST_KEYS, "request")
    return load_plan(body["plan"], "request.plan")


# --- the one serializer ----------------------------------------------------
#
# It builds the BODY and it encodes the BYTES. Building it here while each
# surface called `json.dumps` for itself is what made "the CLI returns the same
# bytes as /v1/quote" false: there were three encode sites with two different
# argument lists, and `print()` added a newline the route does not. F6 asserted
# byte-equality and could not see any of it, because the test decoded both sides
# before comparing.


def encode(body: dict[str, Any]) -> bytes:
    """THE response bytes. Every surface writes exactly what this returns.

    No trailing newline: the route writes these bytes with a Content-Length, so a
    newline here would be part of the payload. The CLI writes them to stdout
    unchanged and adds the newline separately, outside the payload, so a terminal
    still behaves -- see cli.py.
    """
    return json.dumps(body, indent=2, sort_keys=False).encode()


def quote_response(result: Quote) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **result.to_json()}


def refusal_response(refused: Refused) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **refused.to_json()}


def invalid_response(error: Exception) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "invalid": True, "error": str(error)}


def validate_response(plan) -> dict[str, Any]:
    """Every finding, split into the ones the owner still has to look at and the
    ones they have already acknowledged.

    **A DECISION IS AN ACKNOWLEDGEMENT, NOT A PRICE.** `decisions[]` carries a
    `code` and a free-text `note`, and a note cannot price a stay. So `settled`
    does NOT mean "the engine will now answer this" -- a stay hitting a SETTLED
    gap is refused exactly as one hitting an outstanding gap is, and
    `tests/test_f1_never_guesses.py::test_a_stay_hitting_a_DECIDED_gap_is_still_refused`
    is the line that holds it there. The split exists because an owner working
    through a list needs to know what is left, not because deciding changes an
    answer. The way to make a gap price is to add a RULE, which is a visible plan
    change -- that is how §8 says an owner resolves a gap.

    `decided` is stamped here rather than on the Finding, because decidedness is
    a property of (finding, plan) and a Finding does not know which plan it came
    from. The membership test itself is NOT re-implemented here: `undecided()`
    owns the rule that a decision matches on CODE, and a second copy of that rule
    at a second site is exactly the drift findings.py exists to prevent.
    """
    findings = validate_plan(plan)
    outstanding_codes = {f.code for f in undecided(plan)}
    serialized = [
        {**f.to_json(), "decided": f.code not in outstanding_codes} for f in findings
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_version": plan.plan_version,
        "findings": serialized,
        "gaps": sum(1 for f in findings if f.is_gap),
        "conflicts": sum(1 for f in findings if not f.is_gap),
        "outstanding": sum(1 for f in serialized if not f["decided"]),
        "settled": sum(1 for f in serialized if f["decided"]),
    }


def run_quote(document: object) -> tuple[int, dict[str, Any]]:
    """Parse, price, serialize -- the whole of `/v1/quote` and of `rate-engine quote`.

    Returns an HTTP-ish status alongside the body so both surfaces agree on what
    a refusal is, rather than each deciding for itself.

    **`NotMinorUnits` is named explicitly, and `TypeError` is NOT.** It subclasses
    `TypeError` rather than `ValueError`, so `except (InvalidPlan, ValueError)`
    did not catch it: a plain JSON float in a plan -- `8.0`, ordinary operator
    data -- escaped this function entirely, and `/v1/quote` dropped the connection
    without answering. Widening the clause to `TypeError` would have fixed that
    and broken something worse: every genuine programming error in this module is
    a `TypeError` too, and each one would come back to an operator as "your plan
    is invalid", which is a confident wrong answer in a module whose standing
    acceptance is that it is never wrong silently. The refusal is named; the bug
    is still allowed to crash.
    """
    try:
        plans, stay = parse_quote_request(document)
    except (InvalidPlan, NotMinorUnits, ValueError) as exc:
        return 400, invalid_response(exc)
    try:
        return 200, quote_response(quote(plans, stay))
    except Refused as refused:
        # 422: the request was well-formed and the plan cannot price it. That is
        # not a server error and not a bad request -- it is the module working.
        return 422, refusal_response(refused)


def run_validate(document: object) -> tuple[int, dict[str, Any]]:
    try:
        plan = parse_validate_request(document)
    except (InvalidPlan, NotMinorUnits, ValueError) as exc:
        return 400, invalid_response(exc)
    return 200, validate_response(plan)


def breakdown_text(ledger: Ledger, currency: str, width: int = 78) -> str:
    """The human rendering, for the CLI and for a receipt.

    Derived from the same lines the JSON carries -- the text and the amount are
    never composed twice. A line too long to sit beside its amount wraps under
    it rather than being truncated: the sentence explaining why a special did
    not apply is the one an operator reads, and a `...` in the middle of it is
    the module failing at the thing it exists to do.
    """
    from .money import format_minor

    out = []
    for line in ledger.lines:
        amount = format_minor(line.delta_minor, currency) if line.delta_minor else "--"
        if len(line.text) <= width:
            out.append(f"  {line.text.ljust(width)} {amount:>14}")
        else:
            wrapped = textwrap.wrap(line.text, width=width, subsequent_indent="    ")
            out.extend(f"  {part}" for part in wrapped[:-1])
            out.append(f"  {wrapped[-1].ljust(width)} {amount:>14}")
    return "\n".join(out)
