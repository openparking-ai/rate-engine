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

import textwrap
from typing import Any

from .breakdown import Ledger
from .engine import Quote, Stay, make_stay, quote
from .findings import Refused
from .plan import InvalidPlan, load_plan, parse_instant
from .validator import validate_plan

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


def quote_response(result: Quote) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **result.to_json()}


def refusal_response(refused: Refused) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **refused.to_json()}


def invalid_response(error: Exception) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "invalid": True, "error": str(error)}


def validate_response(plan) -> dict[str, Any]:
    findings = validate_plan(plan)
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_version": plan.plan_version,
        "findings": [f.to_json() for f in findings],
        "gaps": sum(1 for f in findings if f.is_gap),
        "conflicts": sum(1 for f in findings if not f.is_gap),
    }


def run_quote(document: object) -> tuple[int, dict[str, Any]]:
    """Parse, price, serialize -- the whole of `/v1/quote` and of `rate-engine quote`.

    Returns an HTTP-ish status alongside the body so both surfaces agree on what
    a refusal is, rather than each deciding for itself.
    """
    try:
        plans, stay = parse_quote_request(document)
    except (InvalidPlan, ValueError) as exc:
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
    except (InvalidPlan, ValueError) as exc:
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
