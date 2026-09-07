"""The pipeline. One code path, and every surface in this module goes through it.

`/v1/quote`, `/v1/validate-plan` and the CLI are three doors onto the functions
below. There is no simulation mode and no second implementation: the "test
function" an owner types entry and exit into IS the production pricing path,
which is F6 and is the control that stops the test function from lying to an
operator about what their garage will charge.

Two properties are asserted here on EVERY quote rather than only in tests:

* **The fee is the sum of the breakdown's deltas.** Not compared against a
  separately-computed fee -- there is no separately-computed fee. The assertion
  catches a rule or a future edit that reaches the total by some other route, and
  ``tests/test_f8_breakdown_adds_up.py`` plants exactly that and requires red.
* **Nothing was guessed.** Any gap reaches the caller as a Refused carrying the
  findings, never as a number.

Purity, for F5: quote() reads its clock from nowhere. Entry and exit come in on
the call, the plan comes in on the call, and the only zone consulted is the
plan's own. Two runs a year apart produce the same fee and the same breakdown,
byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .breakdown import Ledger, Line
from .findings import (
    CONFLICT_AMBIGUOUS_PLAN_SELECTION,
    CONFLICT_MULTIPLE_RULES_AT_STAGE,
    GAP_NO_ACCUMULATE_RULE,
    GAP_NO_PLAN_IN_FORCE_AT_ENTRY,
    GAP_STAY_EXCEEDS_MAX_DURATION,
    GAP_UNDECLARED_SPACE_CLASS,
    Finding,
    Refused,
)
from .plan import InvalidPlan, Plan
from .rules import RULE_APPLIERS
from .rules import daily_max as daily_max_rule
from .rules import early_bird as early_bird_rule
from .rules import increment as increment_rule
from .rules import space_surcharge as space_surcharge_rule
from .stages import ACCUMULATE, ADJUST, CAP, QUALIFY, STAGES

#: Which predicate decides whether a rule of each type qualifies for a stay.
#: Registered beside the appliers rather than inferred, so a rule type that
#: forgets to declare one is a KeyError at quote time instead of a rule that
#: silently qualifies for everything.
QUALIFIERS = {
    "increment": lambda rule, stay, plan: increment_rule.qualifies(rule, stay),
    "early_bird": early_bird_rule.qualifies,
    "daily_max": daily_max_rule.qualifies,
    "space_surcharge": space_surcharge_rule.qualifies,
}


@dataclass(frozen=True)
class Stay:
    entry_at: datetime
    exit_at: datetime
    space_class: str

    @property
    def duration_minutes(self) -> int:
        """Whole minutes, rounded UP, so a part-minute is a minute.

        Integer arithmetic on a timedelta, never a float division: this number
        feeds the period counts, and a float here would put a float into the
        pricing path through the back door.
        """
        delta = self.exit_at - self.entry_at
        seconds = delta.days * 86400 + delta.seconds
        micro = delta.microseconds
        return -(-(seconds * 1_000_000 + micro) // 60_000_000)


@dataclass(frozen=True)
class Quote:
    fee_minor: int
    currency: str
    plan_version: str
    breakdown: Ledger

    def to_json(self) -> dict[str, object]:
        return {
            "fee_minor": self.fee_minor,
            "currency": self.currency,
            "plan_version": self.plan_version,
            "breakdown": self.breakdown.to_json(),
        }


def make_stay(entry_at: datetime, exit_at: datetime, space_class: str) -> Stay:
    if entry_at.tzinfo is None or exit_at.tzinfo is None:
        raise InvalidPlan(
            "entry_at and exit_at must carry a UTC offset. A naive timestamp is read in "
            "whatever zone the server runs in, which is a different fee on a different "
            "machine."
        )
    if exit_at < entry_at:
        raise InvalidPlan(
            f"exit_at ({exit_at.isoformat()}) is before entry_at ({entry_at.isoformat()}). "
            "This is refused rather than treated as a zero-length stay: a negative "
            "duration is a caller bug, and pricing it at zero would hide it."
        )
    if not isinstance(space_class, str) or not space_class:
        raise InvalidPlan("space_class must be a non-empty string.")
    return Stay(entry_at=entry_at, exit_at=exit_at, space_class=space_class)


def select_plan(plans: list[Plan], stay: Stay) -> Plan:
    """THE ENTRY-TIME RULE. His words: "the price is calculated always with the
    entry time fee."

    The plan in force at ENTRY prices the whole stay. A rate change mid-stay never
    splits it, so a stay entering Friday and leaving Sunday prices on Friday's
    structure throughout -- and a garage that put its prices up on Saturday
    morning does not reach back into a car that was already parked.

    Selection is by entry and nothing else. Switch this to `stay.exit_at` and
    tests/test_f3_entry_time_governs.py goes red, which is the whole point of it.
    """
    in_force = [p for p in plans if p.effective_from <= stay.entry_at]
    if not in_force:
        earliest = min(p.effective_from for p in plans)
        raise Refused(
            [
                Finding(
                    code=GAP_NO_PLAN_IN_FORCE_AT_ENTRY,
                    text=(
                        f"no plan version was in force at entry "
                        f"({stay.entry_at.isoformat()}); the earliest supplied takes "
                        f"effect {earliest.isoformat()}"
                    ),
                )
            ]
        )

    # AND THE SELECTION MUST NOT BE AMBIGUOUS.
    #
    # This was `max(in_force, key=...effective_from)`, and `max` returns the
    # FIRST maximal element. Two versions carrying the same `effective_from`
    # therefore priced the same car at 300 or at 2700 minor units depending only
    # on the order of the caller's array -- measured, not imagined. A rate engine
    # that decides money by list order and says nothing is exactly the failure
    # this module refuses everywhere else, so it refuses here too.
    latest = max(p.effective_from for p in in_force)
    tied = [p for p in in_force if p.effective_from == latest]
    if len(tied) > 1:
        # Sorted, so the refusal reads the same whichever order it arrived in.
        # A message that still depended on the array order would have fixed the
        # fee and left the explanation carrying the same defect.
        names = sorted(p.plan_version for p in tied)
        raise Refused(
            [
                Finding(
                    code=CONFLICT_AMBIGUOUS_PLAN_SELECTION,
                    text=(
                        f"{len(tied)} plan versions take effect at "
                        f"{latest.isoformat()} and none is later, so the version in "
                        f"force at entry is ambiguous: {', '.join(names)}. Supply one "
                        "of them, or give them distinct effective dates -- the engine "
                        "will not price on whichever arrived first in the list"
                    ),
                )
            ]
        )
    return tied[0]


def _qualifying(plan: Plan, stay: Stay, stage: str):
    out = []
    for rule in plan.rules_for_stage(stage):
        if QUALIFIERS[rule.type](rule, stay, plan):
            out.append(rule)
    return out


def find_gaps(plan: Plan, stay: Stay) -> list[Finding]:
    """Every reason this plan cannot price this stay, keyed by identifier.

    Called by the engine before it prices anything and by the validator over a
    matrix of stays. ONE function, so the sentence an owner reads in
    `validate-plan` and the sentence in a refusal cannot drift.
    """
    findings: list[Finding] = []

    if stay.space_class not in plan.space_classes:
        findings.append(
            Finding(
                code=GAP_UNDECLARED_SPACE_CLASS,
                text=(
                    f"the plan does not declare a space class {stay.space_class!r} "
                    f"(it declares: {', '.join(plan.space_classes)})"
                ),
            )
        )
        # Everything below asks which rules cover a class the plan has never
        # heard of. Answering that would be guessing.
        return findings

    if _qualifying(plan, stay, QUALIFY):
        return findings  # a special takes over the base; ACCUMULATE is not consulted

    accumulate = plan.rules_for_stage(ACCUMULATE)
    covering = [r for r in accumulate if r.covers(stay.space_class)]
    qualifying = _qualifying(plan, stay, ACCUMULATE)

    if not covering:
        findings.append(
            Finding(
                code=GAP_NO_ACCUMULATE_RULE,
                text=(
                    f"nothing prices the time for a {stay.space_class!r} space: no "
                    "time-based rule covers that class and no special rate qualified"
                ),
            )
        )
    elif not qualifying:
        ceilings = sorted(
            r.params["max_duration_minutes"]
            for r in covering
            if r.params.get("max_duration_minutes") is not None
        )
        limit = ceilings[-1] if ceilings else None
        findings.append(
            Finding(
                code=GAP_STAY_EXCEEDS_MAX_DURATION,
                text=(
                    f"nothing prices a stay of {stay.duration_minutes} minutes for a "
                    f"{stay.space_class!r} space: the longest time-based rule covering "
                    f"it stops at {limit} minutes"
                ),
                rule_ids=tuple(r.id for r in covering),
            )
        )
    return findings


def find_conflicts(plan: Plan, stay: Stay) -> list[Finding]:
    """Two rules qualifying at one stage, which A1 refuses rather than resolves.

    The plan states a resolution mode per stage and this version does not act on
    it -- see plan.RESOLUTION_MODES. Resolving honestly needs two rule types that
    can qualify at one stage, which is round A2. Until then the module does the
    thing it promises everywhere else: it says what is ambiguous and does not
    pick.
    """
    findings: list[Finding] = []
    for stage in STAGES:
        qualifying = _qualifying(plan, stay, stage)
        if len(qualifying) > 1:
            findings.append(
                Finding(
                    code=CONFLICT_MULTIPLE_RULES_AT_STAGE,
                    text=(
                        f"{len(qualifying)} rules qualify at {stage} "
                        f"({', '.join(r.id for r in qualifying)}); the plan states "
                        f"resolution {plan.resolution[stage]!r} for that stage, which "
                        "this version records but does not apply"
                    ),
                    rule_ids=tuple(r.id for r in qualifying),
                )
            )
    return findings


def quote(plans: list[Plan], stay: Stay) -> Quote:
    """Price a stay, or refuse and name what is missing. The only pricing path."""
    plan = select_plan(plans, stay)

    blocking = find_gaps(plan, stay) + find_conflicts(plan, stay)
    if blocking:
        raise Refused(blocking)

    ledger = Ledger()
    entry_local = stay.entry_at.astimezone(plan.timezone)
    ledger.add(
        Line(
            code="stay",
            rule_id=None,
            text=(
                f"Entered {entry_local:%H:%M %a %d %b}, "
                f"{stay.duration_minutes} minutes, space class {stay.space_class!r}, "
                f"plan {plan.plan_version}"
            ),
            delta_minor=0,
        )
    )

    qualified_at_qualify = _qualifying(plan, stay, QUALIFY)

    for stage in STAGES:
        if stage == ADJUST:
            continue  # no rule type ships at ADJUST in A1
        if stage == ACCUMULATE and qualified_at_qualify:
            # A special that qualified IS the base. Not a discount on the
            # time-based charge and not the cheaper of the two -- it replaces it.
            continue
        for rule in plan.rules_for_stage(stage):
            applier = RULE_APPLIERS[rule.type]
            if stage == QUALIFY:
                # Emits its line either way: a special that did not apply is the
                # line an operator most wants to read.
                for line in applier(rule, stay, plan):
                    ledger.add(line)
                continue
            if not QUALIFIERS[rule.type](rule, stay, plan):
                continue
            if stage == CAP:
                lines = applier(rule, stay, plan, ledger.total_minor)
            else:
                lines = applier(rule, stay, plan)
            for line in lines:
                ledger.add(line)

    fee = ledger.total_minor
    _assert_ledger_is_the_fee(fee, ledger)
    if fee < 0:
        raise Refused(
            [
                Finding(
                    code=CONFLICT_MULTIPLE_RULES_AT_STAGE,
                    text=(
                        f"the rules produced a negative fee ({fee}); refusing rather than "
                        "charging a customer a negative amount"
                    ),
                )
            ]
        )
    return Quote(
        fee_minor=fee, currency=plan.currency, plan_version=plan.plan_version, breakdown=ledger
    )


def _assert_ledger_is_the_fee(fee: int, ledger: Ledger) -> None:
    """The invariant that makes the breakdown the product rather than a report.

    This is not a comparison between two copies of the same claim -- there is
    only one claim, and this checks that nothing has grown a second route to it.
    It is in the production path on purpose: an invariant that only tests check
    is an invariant that holds only where tests look.
    """
    summed = sum(line.delta_minor for line in ledger.lines)
    if fee != summed:
        raise AssertionError(
            f"the fee ({fee}) is not the sum of the breakdown ({summed}). Something "
            "reached the total by a route other than adding a Line, which is exactly "
            "the defect the ledger exists to make impossible."
        )
    for line in ledger.lines:
        if isinstance(line.delta_minor, bool) or not isinstance(line.delta_minor, int):
            raise AssertionError(f"line {line.code} carries non-integer money.")
