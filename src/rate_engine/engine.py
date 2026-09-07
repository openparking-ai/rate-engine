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
    CONFLICT_NEGATIVE_TOTAL,
    CONFLICT_UNORDERED_ADJUSTMENTS,
    FAULT_RULE_RETURNED_NOT_LINES,
    GAP_NO_ACCUMULATE_RULE,
    GAP_NO_PLAN_IN_FORCE_AT_ENTRY,
    GAP_STAY_EXCEEDS_MAX_DURATION,
    GAP_UNDECLARED_SPACE_CLASS,
    Finding,
    Refused,
)
from .plan import InvalidPlan, Plan
from .rules import RULE_APPLIERS, RULE_TRAITS, SPEAKS_UNQUALIFIED, TERMINAL
from .rules import daily_max as daily_max_rule
from .rules import grace as grace_rule
from .rules import increment as increment_rule
from .rules import space_surcharge as space_surcharge_rule
from .rules import time_window as time_window_rule
from .rules import weekly_max as weekly_max_rule
from .stages import (
    ACCUMULATE,
    ADJUST,
    CAP,
    COMPOSING_ORDER_DEPENDENT,
    QUALIFY,
    RESOLVING,
    STAGES,
)

#: Which predicate decides whether a rule of each type qualifies for a stay.
#: Registered beside the appliers rather than inferred, so a rule type that
#: forgets to declare one is a KeyError at quote time instead of a rule that
#: silently qualifies for everything.
#: Stages whose rules are DEFINED in terms of the fee so far, and are therefore
#: handed it. A cap is a ceiling on the running total; an adjustment is a
#: percentage or an amount ON it. Neither can SET the total -- both return a Line
#: like every other rule, and the engine adds it. The read is one-way.
#:
#: ADJUST joined this list in A2, when `time_window`'s `adjust` effect became the
#: first rule type to run there. It is the LAST stage on purpose: an adjustment
#: applied before the cap and the surcharge would take a percentage of a number
#: the customer is not being charged.
STAGES_GIVEN_THE_RUNNING_TOTAL: frozenset[str] = frozenset({CAP, ADJUST})

QUALIFIERS = {
    "increment": lambda rule, stay, plan: increment_rule.qualifies(rule, stay),
    "time_window": time_window_rule.qualifies,
    "grace": grace_rule.qualifies,
    "daily_max": daily_max_rule.qualifies,
    "weekly_max": weekly_max_rule.qualifies,
    "space_surcharge": space_surcharge_rule.qualifies,
}


def _terminal_rule(qualified: list):
    """The rule that prices this stay ALONE, if one of them said so. Else None.

    A type declares `TERMINAL` at registration and the pipeline reads the
    declaration -- it does not know the type's NAME. `grace` is the first one:
    "if customer decides to laeve within that period it is free", and free means
    free, so a graced stay in a VIP space must not pick up the surcharge and must
    not pick up anything at CAP or ADJUST. An `if rule.type == "grace"` here
    would be the engine holding a pricing decision no plan can see or change,
    which is the defect `day_span` was created to undo.
    """
    for rule in qualified:
        if TERMINAL in RULE_TRAITS[rule.type]:
            return rule
    return None


def _speaks_anyway(rule, stay) -> bool:
    """Whether a rule that did NOT qualify still gets to explain itself.

    The framework contract's silence rule was keyed on the STAGE, because in A1
    the stage was a perfect proxy: the only rule type outside QUALIFY that could
    fail to apply failed by not covering the space, and "a VIP tier that was
    never about your space" is noise on a receipt. A `time_window` with an
    `adjust` effect broke the proxy -- it runs at ADJUST and can decline because
    it is a Tuesday and the rule says weekends, which is exactly the informative
    case, at a stage the old rule called silent. "Why didn't I get the weekend
    discount?" had no answer in the breakdown.

    So the TYPE declares it, and coverage still governs: a rule that was never
    about this space stays silent whatever it declared.
    """
    return SPEAKS_UNQUALIFIED in RULE_TRAITS[rule.type] and rule.covers(stay.space_class)


def _in_application_order(plan: Plan, stage: str, rules):
    """The sequence a COMPOSING stage's rules are applied in.

    **Never the caller's array position.** Deciding money by the order of a JSON
    list, silently, is a defect this module has already shipped once and refuses
    at `select_plan` -- so composing rules run in ascending rule id, which is
    stated by the operator and stable.

    ADJUST is the exception, and it is an exception about ARITHMETIC rather than
    about determinism: 20% off then 5.00 off is not 5.00 off then 20% off, so the
    plan states the sequence. Where it has not, `find_conflicts` has already
    refused the stay -- this never has to guess.
    """
    if stage in COMPOSING_ORDER_DEPENDENT and plan.adjust_order is not None:
        position = {rule_id: index for index, rule_id in enumerate(plan.adjust_order)}
        return sorted(rules, key=lambda rule: position[rule.id])
    return sorted(rules, key=lambda rule: rule.id)


def _superseded_line(rule, terminal) -> Line:
    """A rule that qualified and was beaten outright, said out loud.

    Dropping it silently would leave a breakdown in which a special the customer
    was entitled to simply is not mentioned -- and "why is the early bird not on
    here?" is the question §8 exists to make answerable. The engine writes this
    one because no rule can know it was superseded; the code is engine-level,
    like `stay`, rather than borrowed from the rule's own namespace.
    """
    return Line(
        code="superseded",
        rule_id=rule.id,
        text=(
            f"{rule.id!r} also qualified and was NOT applied: {terminal.id!r} is "
            "terminal, so it prices this stay by itself and nothing further is charged"
        ),
        delta_minor=0,
    )


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

        **THIS ROUNDING IS ASSUMED, NOT STATED PER RULE, and that is a decision.**
        No plan field reaches it: `increment.rounding` governs minutes into
        PERIODS, downstream of this. money.py used to say the only rounding in the
        engine was "TIME into periods, stated per rule rather than assumed", which
        was false about this one -- it is time into MINUTES, and the plan has no
        say. It is kept because it is the ordinary garage convention and because
        every consumer of a duration here wants the same answer, but it has a
        price: a stay one millisecond past a stated ceiling is 1441 minutes
        against a 1440 limit, and is refused rather than priced.

        Every comparison against a duration reads THIS property -- the rules and
        the ceiling check alike -- so the edge is coherent rather than one
        comparison against raw microseconds and another against minutes.
        `tests/test_f20_time_rounding_is_declared.py` holds that.
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
    """More than one rule qualifying at one stage -- and it means three things.

    **This function used to report a conflict whenever more than one rule
    qualified at ANY stage, and that was a live defect waiting for a rule type.**
    It is right at QUALIFY, where two specials are competing bases and only one
    can be the price. It is wrong at CAP, where two ceilings simply both apply --
    and the moment `weekly_max` existed, every plan carrying a daily AND a weekly
    cap would have refused every stay in the garage.

    So the answer is per CATEGORY, and stages.py holds which is which:

    * RESOLVING -- a genuine either/or. Reported, unless a TERMINAL rule
      qualified: terminality is an outright win declared by the rule type, not an
      ambiguity for the plan to settle, so grace beating a weekend rate is not a
      conflict.
    * COMPOSING, ORDER-INDEPENDENT -- both apply and the total is the same
      either way. Nothing to report and nothing to decide.
    * COMPOSING, ORDER-DEPENDENT -- both apply and the order changes the money,
      so the PLAN must state the order and a plan that has not is refused.
    """
    findings: list[Finding] = []
    for stage in STAGES:
        qualifying = _qualifying(plan, stay, stage)
        if len(qualifying) > 1:
            finding = _conflict_at(plan, stage, qualifying)
            if finding is not None:
                findings.append(finding)
    return findings


def _conflict_at(plan: Plan, stage: str, qualifying: list) -> Finding | None:
    """What more than one qualifying rule MEANS at this stage. None means nothing."""
    ids = tuple(r.id for r in qualifying)
    if stage in RESOLVING:
        terminal = [r for r in qualifying if TERMINAL in RULE_TRAITS[r.type]]
        if len(terminal) == 1:
            # Not an ambiguity: one of them wins outright by what its type is,
            # and the others get a `superseded` line saying so.
            return None
        return Finding(
            code=CONFLICT_MULTIPLE_RULES_AT_STAGE,
            text=(
                f"{len(qualifying)} rules qualify at {stage} ({', '.join(ids)}); the "
                f"plan states resolution {plan.resolution[stage]!r} for that stage, "
                "which this version records but does not apply"
            ),
            rule_ids=ids,
        )
    if stage in COMPOSING_ORDER_DEPENDENT and plan.adjust_order is None:
        return Finding(
            code=CONFLICT_UNORDERED_ADJUSTMENTS,
            text=(
                f"{len(qualifying)} adjustments qualify ({', '.join(ids)}) and the plan "
                "does not state `adjust_order`. Both apply -- this is not a choice "
                "between them -- but a percentage taken before a fixed amount is a "
                "different fee from one taken after, so the order is a pricing "
                "decision and the engine will not pick"
            ),
            rule_ids=ids,
        )
    # COMPOSING and order-independent: both apply, the total is the same either
    # way, and there is nothing for an owner to decide.
    return None


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
    terminal = _terminal_rule(qualified_at_qualify)

    for stage in STAGES:
        if terminal is not None and stage != QUALIFY:
            # A TERMINAL rule prices the stay by itself. Free means free: no
            # time-based charge, no cap, no surcharge, no adjustment. QUALIFY has
            # already run, so its lines -- including every `superseded` one -- are
            # in the ledger. See rules/grace.py.
            break
        if stage == ACCUMULATE and qualified_at_qualify:
            # A special that qualified IS the base. Not a discount on the
            # time-based charge and not the cheaper of the two -- it replaces it.
            continue
        rules = plan.rules_for_stage(stage)
        if stage not in RESOLVING:
            rules = _in_application_order(plan, stage, rules)
        for rule in rules:
            applier = RULE_APPLIERS[rule.type]
            if stage == QUALIFY:
                # Emits its line either way: a special that did not apply is the
                # line an operator most wants to read. A special that DID qualify
                # and was beaten by a terminal rule says that instead -- calling
                # its applier here would add its price to the ledger.
                beaten = terminal is not None and rule is not terminal
                lines = (
                    [_superseded_line(rule, terminal)]
                    if beaten and rule in qualified_at_qualify
                    else applier(rule, stay, plan)
                )
                for line in _lines_of(rule, lines):
                    ledger.add(line)
                continue
            if not QUALIFIERS[rule.type](rule, stay, plan) and not _speaks_anyway(rule, stay):
                continue
            if stage in STAGES_GIVEN_THE_RUNNING_TOTAL:
                lines = applier(rule, stay, plan, ledger.total_minor)
            else:
                lines = applier(rule, stay, plan)
            for line in _lines_of(rule, lines):
                ledger.add(line)

    fee = ledger.total_minor
    _assert_ledger_is_the_fee(fee, ledger)
    if fee < 0:
        raise Refused(
            [
                Finding(
                    code=CONFLICT_NEGATIVE_TOTAL,
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


def _lines_of(rule, returned: object) -> list[Line]:
    """A rule's ONLY channel to the fee is a list of Lines, and this enforces it.

    Established by probing the branch rather than assumed: a rule CANNOT produce
    an effect with no ledger entry, because the applier is handed
    ``(rule, stay, plan)`` and nothing else -- there is no ledger to reach, no
    running total to mutate, and no return channel but this one. That half of the
    guarantee holds by construction and needs no check.

    What was NOT handled is a malformed return. A rule returning dicts used to
    reach `Ledger.add` and die there with
    ``AttributeError: 'dict' object has no attribute 'delta_minor'`` -- a
    stack trace from two files away that names neither the rule nor the rule
    type. It failed, so nothing was mispriced; but "it crashes eventually" is not
    the same promise as "it is refused, and the message says which rule type is
    wrong", and only the second is any use to somebody writing a rule type.

    **It raised a `TypeError`, and that was still not a refusal.** `run_quote`
    catches `Refused`; a `TypeError` went straight past it and out of the quote
    contract, so the promise in docs/CONTRACT.md -- "REFUSED by name, not left to
    crash inside the ledger" -- was false at the boundary that matters, and a test
    asserting `pytest.raises(TypeError)` blessed it. It is now a `Refused`
    carrying its own code, so it reaches a caller the way every other refusal
    does. See findings.FAULT_RULE_RETURNED_NOT_LINES for why that code is a third
    KIND rather than a conflict.

    Note what is deliberately NOT checked: a Line whose delta is zero. Those are
    required by the design -- every "Early bird NOT applied" line is one -- so a
    ledger entry with no monetary effect is correct behaviour here, not a defect.
    Whether a line's ENGLISH matches its delta is not mechanically decidable, and
    inventing a check that appears to decide it would be worse than saying so.
    """
    if not isinstance(returned, list):
        raise Refused(
            [
                Finding(
                    code=FAULT_RULE_RETURNED_NOT_LINES,
                    text=(
                        f"rule type {rule.type!r} (rule {rule.id!r}) returned "
                        f"{type(returned).__name__}, not a list of Line. A rule's only way "
                        "to change the fee is to return Lines; there is no other channel, "
                        "and there is not going to be one."
                    ),
                    rule_ids=(rule.id,),
                )
            ]
        )
    for item in returned:
        if not isinstance(item, Line):
            raise Refused(
                [
                    Finding(
                        code=FAULT_RULE_RETURNED_NOT_LINES,
                        text=(
                            f"rule type {rule.type!r} (rule {rule.id!r}) returned a "
                            f"{type(item).__name__} where a Line was required. Every entry "
                            "in the breakdown carries its own signed delta, and the fee is "
                            "their running total -- an entry that is not a Line has no "
                            "delta to add."
                        ),
                        rule_ids=(rule.id,),
                    )
                ]
            )
    return returned


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
