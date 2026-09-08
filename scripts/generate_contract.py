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
from rate_engine.rules.time_window import DAY_SPAN_LIMITS  # noqa: E402
from rate_engine.stages import STAGES  # noqa: E402
from rate_engine.wallclock import DAYS_OF_WEEK  # noqa: E402

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
    rows += [
        f"| `{name}` | {' or '.join(stages)} |"
        for name, (stages, _b) in sorted(RULE_TYPES.items())
    ]
    empty = sorted({s for s in STAGES} - {s for stages, _ in RULE_TYPES.values() for s in stages})
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


#: The illustrative times for the PARTIAL dead window the block below publishes
#: as a limit. Only the times are written here; which `day_span` can carry the
#: shape is derived from DAY_SPAN_LIMITS, and whether the window is really dead
#: is MEASURED by pricing two stays.
PARTIAL_DEAD_ENTER_FROM = "06:00"
PARTIAL_DEAD_ENTER_BY = "23:00"
PARTIAL_DEAD_EXIT_BY = "20:00"


def _partial_dead_plan(day_span: str) -> dict:
    """A window that LOADS and is nonetheless dead for a late entry."""
    return {
        "plan_version": "contract-partial-dead",
        "effective_from": "2026-01-01T00:00:00-04:00",
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {
            "QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"},
        },
        "adjust_order": None,
        "rules": [
            {"id": "day-rate", "type": "time_window", "stage": "QUALIFY",
             "space_classes": ["standard"], "label": "Day rate",
             "applies_on": {"kind": "days_of_week",
                            "days": list(DAYS_OF_WEEK)},
             "enter_from": PARTIAL_DEAD_ENTER_FROM, "enter_by": PARTIAL_DEAD_ENTER_BY,
             "exit_by": PARTIAL_DEAD_EXIT_BY, "day_span": day_span,
             "effect": {"kind": "flat", "price_minor": 4000}},
            {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
             "space_classes": ["standard"], "first_period_minutes": 60,
             "first_period_minor": 300, "repeat_period_minutes": 60,
             "repeat_period_minor": 300, "rounding": "ceil", "max_duration_minutes": None},
        ],
        "decisions": [],
    }


def _window_applied(day_span: str, entry_at: str, exit_at: str) -> bool:
    """Did the window fire for this stay? Asked of the engine, not assumed."""
    status, body = run_quote(
        {
            "plans": [_partial_dead_plan(day_span)],
            "entry_at": entry_at,
            "exit_at": exit_at,
            "space_class": "standard",
            "currency": "USD",
        }
    )
    if status != 200:
        raise SystemExit(
            f"the contract's partial-dead-window example did not price under "
            f"{day_span!r}: {body}"
        )
    return any(line["code"] == "time_window.applied" for line in body["breakdown"])


def gen_window_limits() -> str:
    """A window's exit limit, and the limits ON it. DERIVED, and the second one MEASURED.

    Which spans can carry a WRAPPING `exit_by` -- one earlier in the day than
    `enter_from` -- is a property of DAY_SPAN_LIMITS rather than a sentence
    somebody has to keep in step with it: a span whose limit falls on the entry
    date itself (0), or which names no last day at all (None), has nowhere for a
    wrapped limit to fall, and the loader refuses it. A span added to that table
    appears here without this function being touched.

    And the limit the refusal does NOT close is PRICED rather than described.
    A sentence in a published contract saying "this window is dead for a late
    entry" is worth nothing unless something asked the engine, so this builds
    that window and prices two stays through it. If the dead one ever fires, or
    the live one ever stops, generation fails here rather than publishing a
    limit that is no longer true.
    """
    def where(limit: int | None) -> str:
        if limit is None:
            return "nowhere -- it names no last day, so the limit stays a bare clock reading"
        if limit == 0:
            return "`exit_by` on the ENTRY date"
        days = "day" if limit == 1 else "days"
        return f"`exit_by` {limit} local {days} after the entry date"

    ordered = sorted(
        DAY_SPAN_LIMITS.items(), key=lambda kv: (kv[1] is None, kv[1] if kv[1] else 0, kv[0])
    )
    rows = [
        "| `day_span` | where the exit limit falls | an `exit_by` BEFORE `enter_from` |",
        "| --- | --- | --- |",
    ]
    for span, limit in ordered:
        wrapping = (
            "**refused at load**" if limit is None or limit == 0
            else "carried -- this is the ordinary evening window"
        )
        rows.append(f"| `{span}` | {where(limit)} | {wrapping} |")

    refused = [s for s, lim in ordered if lim is None or lim == 0]
    carried = [s for s, lim in ordered if lim is not None and lim > 0]
    def fmt(names: list[str]) -> str:
        """`a`, `b` and `c` -- built from the list so a span added to the table
        joins the sentence rather than making it wrong."""
        quoted = [f"`{n}`" for n in names]
        if not quoted:
            return "no span"
        if len(quoted) == 1:
            return quoted[0]
        return f"{', '.join(quoted[:-1])} and {quoted[-1]}"

    # The span whose limit falls on the entry date is the one that can carry the
    # PARTIAL shape: the limit is on the same day as the entry, so an entry after
    # it can never be followed by an exit before it.
    on_entry_date = [s for s, lim in ordered if lim == 0]
    if not on_entry_date:
        raise SystemExit(
            "no day_span puts the exit limit on the entry date, so the partial "
            "dead window this block publishes as a limit cannot be built"
        )
    partial_span = on_entry_date[0]

    # MEASURED, both directions. The late entry must never fire and the early one
    # must fire, or the published sentence is wrong in one of the two ways it can be.
    dead = _window_applied(partial_span, "2026-06-10T20:30:00-04:00", "2026-06-10T20:45:00-04:00")
    alive = _window_applied(partial_span, "2026-06-10T08:00:00-04:00", "2026-06-10T09:00:00-04:00")
    if dead:
        raise SystemExit(
            f"the {partial_span!r} window with enter_by {PARTIAL_DEAD_ENTER_BY} and "
            f"exit_by {PARTIAL_DEAD_EXIT_BY} FIRED for an entry after "
            f"{PARTIAL_DEAD_EXIT_BY}; the limit this block publishes is no longer true"
        )
    if not alive:
        raise SystemExit(
            f"the {partial_span!r} window never fires at all, so calling it PARTIALLY "
            "dead overstates what it does; the published limit is wrong"
        )

    note = (
        f"\n\nA wrapping `exit_by` is refused at load under {fmt(refused)}, neither of "
        f"which can say what day the limit falls on, and carried under {fmt(carried)}. "
        "Stating a bounded span gives the limit a date; writing it as two rules is the "
        "other way to say it."
        "\n\n**The limit this does NOT close, stated because it is a limit.** Only the "
        "window that NO stay could ever satisfy is refused. One that can fire for some "
        f"entries and never for others still loads, and `validate-plan` reports it clean: "
        f"`{partial_span}` with `enter_from` {PARTIAL_DEAD_ENTER_FROM}, `enter_by` "
        f"{PARTIAL_DEAD_ENTER_BY} and `exit_by` {PARTIAL_DEAD_EXIT_BY} is dead for every "
        f"entry after {PARTIAL_DEAD_EXIT_BY} and alive for every entry before it. Both "
        "halves of that sentence were priced to write it. The engine refuses what is "
        "unsatisfiable, not what is partly unsatisfiable, because the second is a shape "
        "an operator may well mean -- and a refusal there would reject a plan that works."
    )
    return block("window_limits", "\n".join(rows) + note, ASSERTION)


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
ignored.** An operator who adds a key to a plan running on a version that has no
rule for it would otherwise have a garage pricing something wrong and a document
saying it does not.

### What changed in version 2

**A rule type was REMOVED, and that is why the number moved.** `early_bird` is
gone. It was a time window with its days hardcoded to every day and its effect
hardcoded to a flat price, and it is now expressible — with the days and the
effect stated — as a `time_window`. A plan written for version 1 does not load on
version 2: an unknown rule type is rejected rather than skipped, which is the
same rule that protects an unknown key.

No operator plans exist in the wild today, so removing a rule type costs nothing
now and could not be done quietly later. It is recorded here rather than left for
somebody to discover from a refusal.

**The other changes are additions.** `time_window` carries an `effect` that is a
flat price, a completely different time-based rate, or an adjustment up or down
on the whole fee — and the third of those brought the ADJUST stage live, so a
rule type now runs at a stage that depends on the rule rather than only on its
type. The stage is still stated in every plan, and the engine refuses a plan
whose stated stage disagrees with the one the rule's own shape implies.

Two rule types arrived with it: `grace`, and `weekly_max`. And two plan fields:
every plan now states `adjust_order`, null included, and `resolution` changed
shape.

**`resolution` is keyed by the RESOLVING stages only, and its values are
objects.** It used to require an entry for all five stages, as a bare mode
string, and to be acted on by nothing. It now decides which of several qualifying
rules applies — and the three stages it could never act on are refused as keys
this version does not understand, because a mode stated for CAP cannot choose
between two caps when both of them apply.

**Two classes of plan that used to be REFUSED now price, and that is a behaviour
change rather than a bug fix nobody notices.**

More than one rule qualifying at one stage was treated as a conflict at EVERY
stage. That is right where rules compete and wrong where they compose, and it was
harmless only while no second rule type existed at a composing stage.
`weekly_max` is that second type: without the fix, every plan carrying a daily
AND a weekly cap would have refused every stay in the garage.

And at a resolving stage, two rules at different prices are now settled by the
plan's mode instead of refused. `CONFLICT_MULTIPLE_RULES_AT_STAGE` therefore
means something narrower than it did: a TIE, which no mode can settle. The code
is unchanged and still reachable; what changed is how much it covers.

**A window that would have to wrap past midnight is REFUSED, and that is a stated
gap.** `enter_from` later than `enter_by` — "enter between 22:00 and 02:00" — is
not expressible as one rule. It is refused at load, naming the field, and the
message says to write it as two rules: one running to 23:59 and one starting at
00:00, each stating its own days. The engine will not split it, because which
days each half applies on is a pricing decision.

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

This is not incidental. `time_window` speaks of "enter by 09:00" and `daily_max`
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

{window_limits}

## The plan document

Data, validated on load, never code. Every field is required and **there is no
default anywhere**, because a default is a pricing decision made by whoever wrote
the engine and applied to a garage whose owner never saw it. Where a plan is
silent, the engine refuses and names the field.

A plan states a resolution mode for each stage that can RESOLVE — QUALIFY and
ACCUMULATE — from: {resolution_inline}. A mode stated for any other stage is
refused by name: CAP, SURCHARGE and ADJUST compose, so a mode there could never
choose anything, and a field that cannot change an answer is a decision the owner
made and the software ignored.

- `{{"mode": "cheapest_wins"}}` — the **lowest fee for the customer** wins.
- `{{"mode": "stated_order", "order": [...]}}` — the plan names the rule ids and
  the first that qualifies wins. It must name every rule at that stage **exactly
  once**; a rule left out would take a silent position in the order.

**What `cheapest_wins` compares, stated because it is a limit.** It compares what
the competing rules themselves charge for the stay — not the final fee. A cap or
an adjustment downstream applies to whichever rule wins and could in principle
bring two different bases to the same number; comparing final fees would mean
running the whole pipeline once per candidate, and would still not be "the
customer's fee" for the rules that lost. Two rules charging the SAME amount
cannot be separated by it and are refused, naming both.

`adjust_order` is a different thing and is stated separately: a list of rule ids,
or null, giving the sequence the ADJUST rules run in. **An order is not a
choice**, which is why it does not live in `resolution`. It is
required-and-nullable like `max_duration_minutes` and `week_starts_on` — a field
that may simply be absent is one somebody forgets while believing they set it —
and when it is stated it must name every ADJUST rule exactly once, because a rule
left out would take a silent position in the sequence.

## Gaps, conflicts, and the refusal

A **gap** is a stay the plan cannot price. A **conflict** is two rules qualifying
at one stage whose resolution the plan does not settle. One mechanism serves both
places it is needed: `validate-plan` reports them so an owner can decide, and at
quote time a gap is a **refusal that names what is missing**.

**More than one rule qualifying at one stage means three different things, and
the stage decides which.** This used to be one answer for all five stages, and it
was wrong in a way that only a second rule type could expose:

- **QUALIFY and ACCUMULATE resolve.** Two rules are a genuine either/or -- only
  one of them can be the price -- so it is a conflict and the plan settles it.
- **CAP and SURCHARGE compose, in any order.** Two caps are not a contradiction;
  they are two ceilings, and the lower one wins whichever ran first. Nothing is
  reported, because there is nothing for an owner to decide. Their lines are
  emitted in ascending rule id, never in the order the caller's array happened to
  carry them.
- **ADJUST composes, and the order changes the money.** Twenty per cent off then
  five dollars off is not five dollars off then twenty per cent off, so two
  qualifying adjustments with no stated `adjust_order` are REFUSED under their
  own code -- a different question from "which of these is the price", and a
  consumer routing on codes can tell them apart.

**A TERMINAL rule is not a conflict either.** It wins outright by what its type
is, rather than by anything the plan says, so a grace period beating a weekend
rate is settled and the beaten rule gets a line saying so.

**And at a resolving stage the plan's MODE settles it**, so two windows at
different prices are priced rather than refused. What is left is the case no mode
can settle: two rules that qualify and charge the SAME amount under
`cheapest_wins`. There is nothing to be cheapest about, the engine will not pick,
and the refusal names both and says that stating an order would settle it.

**Every rule that lost is still on the receipt**, naming the winner, both prices
and the mode that chose — a breakdown that silently omitted a rate the customer
nearly got could not answer the question an attendant is actually asked.

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

- **No occupancy-driven rule.** Not in this version.
- **No plan storage, no draft/approve workflow, no change log.** Round B. A plan
  arrives on the call.
- **No forecast and no competitor comparison.** Round C.
- **No rate import from a photograph.** Round D, and it will only ever produce a
  draft.

## Grace, and what "free" means

A plan may declare a grace period: `minutes`, a positive whole number, with **no
default and no grace unless the plan states the rule.** "Usually ten minutes" is
an observation about other people's garages, not a value to assume.

**A stay at or under that many minutes costs nothing, and nothing means nothing.**
Grace is TERMINAL: the pipeline stops after QUALIFY, so a graced stay in a VIP
space does not pick up the surcharge, does not reach a cap, and is not adjusted.
A receipt for a graced stay carries the grace line and nothing else. It also
beats any other special that qualified — and that special is not dropped
silently; it gets a line naming the rule that superseded it.

**All-or-nothing.** One minute over a ten-minute grace and the stay prices from
ENTRY on the ordinary rate, not from minute ten. That is the ordinary garage
convention and it is the same all-conditions rule every special here keeps.

**A grace of ten minutes covers 600.000 seconds and not 600.001.** Durations are
whole minutes rounded UP, module-wide, before any rule sees a stay — so a stay of
ten minutes and one millisecond is eleven minutes and misses a ten-minute grace.
That is coherent with every other duration comparison here, including the stated
ceiling on a time-based rule, and it is recorded rather than adjusted.

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

**And this paragraph now describes only a plan that declares NO grace.** A garage
that declares one makes a zero-length stay free by the grace rule, because zero
is at or under any positive number of minutes. Both behaviours are deliberate,
both are tested, and which one a garage gets is stated in its own plan rather
than assumed here.
- **No validations, no monthly parkers, no payments, no card, no tax.**

## The first money rounding, and why money stays an integer

**A percentage adjustment is the first thing in this module that rounds MONEY,
and it arrives with the version bump §2 says a commercial contract makes.** Every
rule before it was an integer add or an integer replace, and `money.py` said in
as many words that this module rounds no money anywhere. That sentence is now
qualified rather than deleted: it rounds money in exactly one place, the place is
named, and the direction is the plan's to state.

**A percentage is INTEGER BASIS POINTS.** 20% is `2000`; 12.5% is `1250`. Not a
decimal, because a float anywhere in a plan is refused at load — so a percent
field that could hold `20.5` would either be rejected or would put a float into
the pricing path through a field nobody was watching. The arithmetic is
`total * percent_bp // 10000` with the division rounded the way the rule says,
and no float is constructed at any point.

**`rounding` is stated per rule with no default**, because a percentage of a fee
lands on a fraction of a minor unit and who keeps that fraction is the owner's
decision. The breakdown line says which way it went and by how much, so a
customer disputing a cent can be shown the answer rather than told it.

**That rounding is not the rounding this module already had.**
`increment.rounding` rounds TIME into whole periods: it decides that a 61-minute
stay is two hours. **The applier reads that field and refuses a mode it does not
implement**, so adding a mode to the ones a plan may state is a real change
rather than a plan that quietly keeps pricing as `ceil` (F15). The two roundings
share a word and nothing else.

**One wart, recorded rather than hidden:** `rounding` is required on every
`adjust` effect, and a `fixed` amount has nothing to round — on that shape the
field is stated and never read. It is written down here rather than left for a
reader to notice.

Money stays an integer of minor units at every depth. Nothing here introduces a
float, and nothing here changes what a plan written against the previous version
answers, because such a plan no longer loads at all — see "What changed in
version 2".

---

Built by 72 Knots Method by 72Knots.ai
"""


def render() -> str:
    return TEMPLATE.format(
        schema=SCHEMA_VERSION,
        schema_block=gen_schema(),
        stages=gen_stages(),
        rule_types=gen_rule_types(),
        window_limits=gen_window_limits(),
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
