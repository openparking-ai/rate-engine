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
from rate_engine.findings import CONFLICT_CODES, FAULT_CODES, GAP_CODES  # noqa: E402
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


#: What a generated block IS, and it is marked in the document so a reader can
#: tell without reading this file.
#:
#: KIND 1 -- INTERPOLATION. Exactly one possible wording; only values move. A
#:           number or a list dropped into fixed words. There is nothing to
#:           falsify beyond "the value is the one the code holds", so a
#:           contradicting-prose test cannot be written for it and inventing one
#:           would be theatre.
#: KIND 2 -- ASSERTION. Two or more reachable renderings whose NON-NUMERIC text
#:           differs, because the block says something ABOUT its values. These
#:           need a control that reaches both renderings and requires the PROSE
#:           to change -- a moving number is not a changed assertion.
#:
#: `tests/test_contract_is_generated.py` derives the kind-2 set from the
#: published document and requires every member to be controlled, so a new
#: asserting block cannot arrive without one.
INTERPOLATION = 1
ASSERTION = 2


def block(name: str, body: str, kind: int = INTERPOLATION) -> str:
    return f"<!--gen:{name} kind={kind}-->\n{body}\n<!--/gen:{name}-->"


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
    return block("rule_types", "\n".join(rows) + note, ASSERTION)


def gen_findings() -> str:
    # Derived from the registry's own three tuples. A fourth kind added to
    # findings.py appears here without this function being touched; a kind added
    # here without a tuple behind it cannot be written at all.
    rows = ["| code | kind |", "| --- | --- |"]
    for codes, kind in ((GAP_CODES, "gap"), (CONFLICT_CODES, "conflict"), (FAULT_CODES, "fault")):
        rows += [f"| `{c}` | {kind} |" for c in codes]
    return block("findings", "\n".join(rows), ASSERTION)


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
    return block("example", "\n".join(parts), ASSERTION)


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

Money is an **integer of minor units** — 800 means 8.00. A float, a bool or a
`Decimal` is refused at **any depth of a plan**, including in fields this version
does not read; and a string where money is expected is refused with them. A rate
that cannot be expressed in minor units is a rate this module refuses, and it
refuses it at load rather than at the point the arithmetic goes wrong. JSON
exponent form (`8e2`) parses to a float and is refused with the rest.

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
places it is needed: `validate-plan` reports them so an owner can decide, and at
quote time a gap is a **refusal that names what is missing**.

`validate-plan` probes every boundary the plan DECLARES -- each entry limit, each
exit limit, each period length and stated ceiling, either side of each, across
every space class -- rather than a written list of scenarios or a search over all
stays. That is exhaustive over what a rule can express today and is not a claim
about every possible stay; the probe axes are derived from the rules, so a rule
type qualifying on something new brings its own axis.

**Deciding a finding does not resolve it.** `decisions[]` records that an owner
has seen a gap — `validate-plan` reports it as SETTLED rather than OUTSTANDING,
so a list can be worked through — and that is all it does. A decision carries a
code and a free-text note, and a note cannot price a stay; a stay hitting a
settled gap is refused exactly as one hitting an outstanding gap is. The way to
make a gap priceable is to add a **rule** that covers it, which is a visible plan
change. See F12 and F12b.

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

## A stay of zero length pays the first period

**Entry and exit at the same instant is priced, not free, and not refused.** The
first period covers `[0, first_period_minutes]`, so a car that enters and leaves
without stopping pays `first_period_minor` -- the same as a car that stayed one
minute or fifty-nine.

It is a DECISION, and it is published here because an integrator cannot otherwise
learn it: the number is correct under the rule as written, and it is the kind of
edge a garage owner will be asked about at the counter.

**It diverges from the platform's own older fee code, which returns zero for the
same stay.** That divergence is known and is a later round's to reconcile; it is
recorded rather than left for whoever notices the two answering differently.

A negative stay -- exit before entry -- is a different thing and is REFUSED as a
caller bug rather than priced at zero, because pricing it would hide it.

**What would change this, and has not yet:** a grace period. A garage that
declares one would make a zero-length stay free by the grace rule, and this
paragraph would then describe only a plan that declares no grace. Grace is not in
this version -- see the item above.
- **No validations, no monthly parkers, no payments, no card, no tax.**

## The occupancy multiplier, and why money stays an integer

Round A2's occupancy rule is a multiplier, and a multiplier is fractional. It
will be expressed as a **rational** — an integer numerator over an integer
denominator, applied as `value * numerator // denominator` — and the plan will
state the rounding direction explicitly, with no default.

**That rounding is not the rounding this version already has.**
`increment.rounding` rounds TIME into whole periods: it decides that a 61-minute
stay is two hours. **The applier reads that field and refuses a mode it does not
implement** — so A2 adding `floor` to the modes a plan may state is a real
change, not a plan that quietly keeps pricing as `ceil` (F15).

A multiplier's rounding direction decides fractions of a
**cent**. The two share a word and nothing else, and **this module does not round
money anywhere today** — `money.py` says so in as many words, and the arithmetic
matches it: every A1 rule is an integer add or an integer replace. A2 introduces
the first money rounding this contract has ever carried, and it arrives with a
version bump, which is what §2 says a commercial contract does.

Money stays an integer of minor units at every depth. The multiplier will not
introduce a float, and it will not change what any plan written against this
version answers.

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
