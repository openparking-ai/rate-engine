#!/usr/bin/env python3
"""Generate docs/CONTRACT.md. Nothing in the generated blocks is hand-typed.

    python scripts/generate_contract.py            # write it
    python scripts/generate_contract.py --check     # fail if it is out of date

GENERATION IS NOT VERIFICATION. Moving a sentence from a document into a template
does not stop it being hand-written -- everywhere except the holes it is still
prose nobody checks. So the blocks below DERIVE everything they assert: the rule
types from the registry, the gap codes from findings.py, the guarantees from
tests/_guarantees.py, and the worked example by actually running the engine and
printing what it returned. `tests/test_contract_is_generated.py` plants values
that contradict the prose and requires the prose to change.

The unmarked prose outside the `<!--gen:-->` blocks is ordinary documentation and
asserts nothing measurable on purpose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import rate_engine  # noqa: F401,E402  (registers the rule types)
from _guarantees import GUARANTEES  # noqa: E402
from rate_engine.contract import SCHEMA_VERSION, breakdown_text, run_quote  # noqa: E402
from rate_engine.findings import CONFLICT_CODES, GAP_CODES  # noqa: E402
from rate_engine.plan import RESOLUTION_MODES  # noqa: E402
from rate_engine.rules import RULE_TYPES  # noqa: E402
from rate_engine.stages import STAGES  # noqa: E402

CONTRACT = ROOT / "docs" / "CONTRACT.md"
EXAMPLE_PLAN = ROOT / "tests" / "plans" / "downtown_v2.json"

EXAMPLE_REQUEST = {
    "plans": [json.loads(EXAMPLE_PLAN.read_text())],
    "entry_at": "2026-03-03T09:14:00-05:00",
    "exit_at": "2026-03-03T18:40:00-05:00",
    "space_class": "standard",
    "currency": "USD",
}


def block(name: str, body: str) -> str:
    return f"<!--gen:{name}-->\n{body}\n<!--/gen:{name}-->"


def gen_stages() -> str:
    return block("stages", " → ".join(f"**{s}**" for s in STAGES))


def gen_rule_types() -> str:
    rows = ["| rule type | stage |", "| --- | --- |"]
    rows += [f"| `{name}` | {stage} |" for name, (stage, _b) in sorted(RULE_TYPES.items())]
    empty = sorted({s for s in STAGES} - {stage for stage, _ in RULE_TYPES.values()})
    note = (
        f"\n\nStages with no rule type in this version: {', '.join(empty)}."
        if empty
        else "\n\nEvery stage has at least one rule type in this version."
    )
    return block("rule_types", "\n".join(rows) + note)


def gen_findings() -> str:
    rows = ["| code | kind |", "| --- | --- |"]
    rows += [f"| `{c}` | gap |" for c in GAP_CODES]
    rows += [f"| `{c}` | conflict |" for c in CONFLICT_CODES]
    return block("findings", "\n".join(rows))


def gen_resolution() -> str:
    return block("resolution", ", ".join(f"`{m}`" for m in RESOLUTION_MODES))


def gen_guarantees() -> str:
    rows = ["| id | what it proves |", "| --- | --- |"]
    rows += [f"| **{gid}** | {text} |" for gid, text in sorted(GUARANTEES.items())]
    return block("guarantees", "\n".join(rows))


def gen_example() -> str:
    """The worked example, PRICED. Not transcribed from anywhere."""
    status, body = run_quote(EXAMPLE_REQUEST)
    if status != 200:
        raise SystemExit(f"the contract's worked example did not price: {body}")

    from rate_engine.breakdown import Ledger, Line

    ledger = Ledger([Line(**line) for line in body["breakdown"]])
    total = sum(line.delta_minor for line in ledger.lines)
    parts = [
        "```",
        "POST /v1/quote",
        json.dumps(
            {
                k: (v if k != "plans" else ["<the plan document>"])
                for k, v in EXAMPLE_REQUEST.items()
            },
            indent=2,
        ),
        "```",
        "",
        "```",
        breakdown_text(ledger, body["currency"]),
        "",
        f"  FEE  {body['fee_minor']} minor units ({body['currency']})",
        "```",
        "",
        f"The lines above sum to {total}, which is the fee. That is not a coincidence "
        f"and not a check performed afterwards: the fee IS the running total of the "
        f"breakdown, and the engine asserts it on every quote.",
    ]
    return block("example", "\n".join(parts))


def gen_schema() -> str:
    return block("schema_version", f"`schema_version` **{SCHEMA_VERSION}**")


TEMPLATE = """# The rate engine contract

Version {schema}. One contract, three surfaces: `POST /v1/quote`, `POST
/v1/validate-plan`, and the `rate-engine` CLI. Our own platform is an ordinary
client of it — there is no private path and no in-process shortcut, so if this
interface is inadequate we find out before an integrator does.

**This module calculates. It takes no payment, holds no card, and stores
nothing.** A plan arrives on the call and is gone when the response is written.

{schema_block}

## Versioning, and the unknown key

This contract is versioned on the assumption that it will **gain fields**. A
commercial module's contract moves because businesses change, so consumers must
tolerate new fields appearing in a response.

The rule runs the other way for requests, and it is what makes the assumption
safe: **a key this engine does not understand is REJECTED and named, never
ignored.** An operator who adds `weekend_rate` to a plan running on a version
with no weekend rule would otherwise have a garage pricing weekends wrong and a
document saying it does not.

## Money

Money is an **integer of minor units** — 800 means 8.00. No float, no `Decimal`,
no string, at any depth of a plan, including in fields this version does not
read. A rate that cannot be expressed in minor units is a rate this module
refuses, and it refuses it at load rather than at the point the arithmetic goes
wrong. JSON exponent form (`8e2`) parses to a float and is refused with the rest.

## Time

Every plan names an **IANA timezone**, and entry and exit arrive as offset-aware
ISO 8601. A naive timestamp is refused: it would be read in whatever zone the
server happens to run in, which is a different fee on a different machine.

This is not incidental. `early_bird` speaks of "enter by 09:00" and `daily_max`
speaks of a day; both are wall-clock ideas, and a local day is 23 or 25 hours
across a daylight-saving transition. `daily_max` therefore requires the plan to
state whether a day means a local `calendar_day` or a `rolling_24h` window,
because those price a Friday-night-to-Saturday-morning stay differently and the
answer is the owner's to give.

## The pipeline

{stages}

The order is load-bearing: a cap that ran before the surcharge would cap a number
the customer is not being charged, and a surcharge applied after the cap is a
surcharge that survives it.

{rule_types}

## The plan document

Data, validated on load, never code. Every field is required and **there is no
default anywhere**, because a default is a pricing decision made by whoever wrote
the engine and applied to a garage whose owner never saw it. Where a plan is
silent, the engine refuses and names the field.

A plan states a resolution mode per stage, from: {resolution_inline}. This
version validates that field and does not act on it — see "What this version does
not do".

## Gaps, conflicts, and the refusal

A **gap** is a stay the plan cannot price. A **conflict** is two rules qualifying
at one stage whose resolution the plan does not settle. One mechanism serves both
places it is needed: `validate-plan` reports them all so an owner can decide, and
at quote time an unresolved gap is a **refusal that names what is missing**.

**The engine never returns a number it had to guess.** That is this project's
standing acceptance, and in this module it is also the entire commercial
argument: a system that refuses when it is unsure can be trusted by someone who
cannot check its work.

{findings}

## A worked example

{example}

## The guarantees

Each of these has a test proven able to fail, by planting the defect it guards
against and requiring red — `python scripts/fail_controls.py`. A test that has
never failed is a decoration.

{guarantees}

## What this version does not do

Named here so nobody adds them helpfully:

- **No resolution of conflicts.** The modes are recorded and not applied. Two
  rules qualifying at one stage is a refusal in this version, because resolving
  it honestly needs two rule types that can qualify at once, which is round A2.
- **No weekend, holiday, event, weekly-max or occupancy rules.** Round A2.
- **No plan storage, no draft/approve workflow, no change log.** Round B. A plan
  arrives on the call.
- **No forecast and no competitor comparison.** Round C.
- **No rate import from a photograph.** Round D, and it will only ever produce a
  draft.
- **No grace period.** Deliberately absent: inventing a free interval is
  inventing a pricing decision nobody made. An operator who wants the first
  fifteen minutes free writes a first period of 15 minutes priced at 0, visibly,
  in the plan.
- **No validations, no monthly parkers, no payments, no card, no tax.**

## The occupancy multiplier, and why money stays an integer

Round A2's occupancy rule is a multiplier, and a multiplier is fractional. It
will be expressed as a **rational** — a numerator and a denominator, both whole —
with the rounding direction stated in the plan, exactly as `increment.rounding`
already is. It will not introduce a float, and it will not change what any plan
written against this version answers.

---

Built by 72 Knots Method by 72Knots.ai
"""


def render() -> str:
    return TEMPLATE.format(
        schema=SCHEMA_VERSION,
        schema_block=gen_schema(),
        stages=gen_stages(),
        rule_types=gen_rule_types(),
        resolution_inline=gen_resolution(),
        findings=gen_findings(),
        example=gen_example(),
        guarantees=gen_guarantees(),
    )


def main(argv: list[str]) -> int:
    rendered = render()
    if "--check" in argv:
        current = CONTRACT.read_text() if CONTRACT.exists() else ""
        if current != rendered:
            print(
                "docs/CONTRACT.md is out of date with the code it describes.\n"
                "Run: python scripts/generate_contract.py"
            )
            return 1
        print("docs/CONTRACT.md matches the code.")
        return 0
    CONTRACT.parent.mkdir(exist_ok=True)
    CONTRACT.write_text(rendered)
    print(f"wrote {CONTRACT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
