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
    CONFLICT_NEGATIVE_TOTAL,
    CONFLICT_OVERLAPPING_FILL_RULES,
    CONFLICT_UNORDERED_ADJUSTMENTS,
    FAULT_RULE_RETURNED_NOT_LINES,
    GAP_NO_ACCUMULATE_RULE,
    GAP_NO_OCCUPANCY_AT_ENTRY,
    GAP_NO_PLAN_IN_FORCE_AT_ENTRY,
    GAP_STAY_EXCEEDS_MAX_DURATION,
    GAP_STAY_LONGER_THAN_MAX_STAY,
    GAP_UNDECLARED_SPACE_CLASS,
    Finding,
    Refused,
)
from .percent import percent_text
from .plan import InvalidPlan, Plan
from .rules import (
    NEEDS_OCCUPANCY,
    ON_THE_TIME_CHARGE,
    ONE_PER_STAY,
    RULE_ACCRUALS,
    RULE_APPLIERS,
    RULE_TRAITS,
    SPEAKS_UNQUALIFIED,
    TERMINAL,
    TOLD_THE_BASE,
    TOLD_THE_PASS,
)
from .rules import daily_max as daily_max_rule
from .rules import fill_level as fill_level_rule
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
    SURCHARGE,
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
    "fill_level": fill_level_rule.qualifies,
}


class _Qualified:
    """Which of the plan's rules qualify for this stay: asked ONCE a quote.

    Whether a rule qualifies is a matter of the rule, the stay and the plan, and
    never of which way the stay is being priced. So `quote` makes one of these
    and hands it to the gaps, the conflicts and every pass of `_the_cheapest_way`.
    Each stage is asked about when it is first needed, and then remembered: its
    rules in plan order, the ones that qualify, and their ids.

    **Why it exists.** Since the cheapest price always wins (F63), every way of
    pricing a stay is priced through the whole pipeline. Each of those passes
    asked every rule again whether it qualified, and found it in the answer with
    `rule in [...]`, which compares two rules field by field. The work of a quote
    then grew with the cube of the ways that qualified: 800 any-day specials took
    26.9 s a stay. Now a rule is asked once, and is found by its id, which
    `load_plan` holds unique across the plan.

    The same goes for the line a special that did NOT qualify gives on every pass
    ("Early bird NOT applied: ..."). Its applier is a pure function of the rule,
    the stay and the plan, so it is asked for that line once (`why_not`), and
    every pass carries the same line.
    """

    def __init__(self, plan: Plan, stay: Stay) -> None:
        self._plan = plan
        self._stay = stay
        self._rules: dict[str, tuple] = {}
        self._at: dict[str, tuple] = {}
        self._ids: dict[str, frozenset[str]] = {}
        self._why_not: dict[str, list[Line]] = {}

    def rules(self, stage: str) -> tuple:
        """The plan's rules at `stage`, in plan order, qualified or not."""
        if stage not in self._rules:
            self._rules[stage] = self._plan.rules_for_stage(stage)
        return self._rules[stage]

    def at(self, stage: str) -> tuple:
        """The rules at `stage` that qualify for the stay, in plan order."""
        if stage not in self._at:
            found = tuple(_qualifying(self._plan, self._stay, stage))
            self._at[stage] = found
            self._ids[stage] = frozenset(rule.id for rule in found)
        return self._at[stage]

    def has(self, rule) -> bool:
        """Whether `rule` qualifies for the stay. By its id: never by comparing
        whole rules."""
        ids = self._ids.get(rule.stage)
        if ids is None:
            self.at(rule.stage)
            ids = self._ids[rule.stage]
        return rule.id in ids

    def why_not(self, rule) -> list[Line]:
        """The lines of a special that did not qualify, asked of it once a quote."""
        if rule.id not in self._why_not:
            self._why_not[rule.id] = _lines_of(
                rule, RULE_APPLIERS[rule.type](rule, self._stay, self._plan)
            )
        return self._why_not[rule.id]


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


def _candidate_totals(rules, stay: Stay, plan: Plan) -> dict[str, int]:
    """What each competing rule ITSELF charges for this stay, by rule id.

    Asked of the RULES rather than computed from their fields: a rule's only
    channel to the fee is a list of Lines, so the honest way to find out what one
    costs is to add up the lines it returns. That is also the only way this can
    stay type-agnostic -- a flat price and a whole time-based rate are compared
    by the same code, and a rule type added later is comparable the day it exists.

    **This no longer decides which rule is charged (F63).** It used to: two
    specials, or two time-based rates, were compared on what the rules
    themselves charged, and a cap or an adjustment downstream could make the
    dearer rule the cheaper stay -- a 100.00 flat special and a 1.00-an-hour
    weekend rate over two days, at 30.00 a day, come to 30.00 and 48.00 once the
    cap has run. The car pays the cheapest (Gokhan, 2026-10-16), so every way is
    priced through the whole pipeline and the FEES are compared
    (`_the_cheapest_way`). What a rule itself charges is still what its line
    says it "qualified at", and it settles which of two ways that come to the
    same fee is named.
    """
    totals: dict[str, int] = {}
    for rule in rules:
        lines = _lines_of(rule, RULE_APPLIERS[rule.type](rule, stay, plan))
        totals[rule.id] = sum(line.delta_minor for line in lines)
    return totals


#: The line a rule that qualified and lost is given, naming the rule charged.
RESOLVED = "resolved"


@dataclass(frozen=True)
class _Compared:
    """What each way of pricing the stay came to, by the rule that priced the time.

    `fees`: the whole stay priced through every stage with that rule as its base
    -- caps, surcharges and adjustments included. `own`: what the rule itself
    charged (`_candidate_totals`). Both keyed by rule id.
    """

    fees: dict[str, int]
    own: dict[str, int]


def _rank(plan: Plan, rule, compared: _Compared):
    """Where one way of pricing the stay stands against the others at its stage.

    **The lowest fee first, under either mode** (F63). Gokhan, 2026-10-16: when
    more than one price could apply to the same time, the car pays the
    cheapest. Between two ways that come to the same fee, the one whose own
    charge is lower is named; and between two that charge the same in both, the
    plan's mode names one -- the lowest rule id under `cheapest_wins`, the first
    in the order under `stated_order`. The mode decides a NAME, never the money.
    `stated_order` used to choose the rule outright, the dearer one included,
    and a plan could make a driver pay more than another rule it qualified for.
    """
    stage = rule.stage
    settings = plan.resolution[stage]
    if settings["mode"] == "stated_order":
        named = settings["order"].index(rule.id)
    else:
        named = rule.id
    return (compared.fees[rule.id], compared.own[rule.id], named)


def _cheapest(plan: Plan, rules, compared: _Compared):
    """The way of pricing the stay, of `rules` (all at one stage), that charges
    the driver least, by `_rank`. None when there are none."""
    if not rules:
        return None
    return min(rules, key=lambda rule: _rank(plan, rule, compared))


def _mode_clause(plan: Plan, stage: str) -> str:
    """The parenthesis a resolution line ends with: how the plan resolves `stage`.

    Under `cheapest_wins` it is the sentence it always was. Under `stated_order`
    it says what the order does now, because it no longer chooses the price.
    """
    mode = plan.resolution[stage]["mode"]
    if mode == "stated_order":
        return (
            f"(plan resolves {stage} by stated_order: the cheapest is charged, and the "
            "order names one of two that charge the same)"
        )
    return f"(plan resolves {stage} by {mode})"


def _resolved_line(
    rule, winner, stage: str, plan: Plan, compared: _Compared, by_time: bool = False
) -> Line:
    """A rule that qualified and lost, said out loud, with the reason.

    §8's first requirement is that a customer can read WHY. "Weekend rate
    qualified at 15.00 USD -- Early bird 12.00 USD applied instead" is the whole
    answer to the question an attendant is asked, and dropping the loser would
    leave a breakdown in which a rate the customer was entitled to is simply
    absent.

    A loser that charged the SAME as the winner -- itself, and for the whole
    stay -- says so: "charged the same" is the true reason it was not named, and
    "applied instead" alone would read as if one of them had been cheaper.

    **Where the rules' own charges do not say why, the whole stay does** (F63).
    The ways are compared on the fee, caps and all, so the winner's own charge
    can be the higher one: "Event rate 100.00 USD applied instead" beside a 48.00
    weekend rate is true only because, at 30.00 a day, the event rate's stay
    comes to 30.00 and the weekend rate's to 48.00 -- so the line says both.

    `by_time`: the stay was charged by the time-based rate, which was less than
    the cheapest special too (`_the_cheapest_way`). The winner was then NOT
    applied, so the line says it was the cheaper special, never "applied instead".
    """
    from .money import format_minor

    own, fees = compared.own, compared.fees
    mode = _mode_clause(plan, stage)
    if own[rule.id] == own[winner.id] and fees[rule.id] == fees[winner.id]:
        because = (
            "the plan's stated order puts it first"
            if plan.resolution[stage]["mode"] == "stated_order"
            else "its rule id comes first"
        )
        return Line(
            code=RESOLVED,
            rule_id=rule.id,
            text=(
                f"{rule.display_name} qualified at "
                f"{format_minor(own[rule.id], plan.currency)} and charged the same as "
                f"{winner.display_name}, which is named because {because} {mode}"
            ),
            delta_minor=0,
        )
    text = (
        f"{rule.display_name} qualified at {format_minor(own[rule.id], plan.currency)} -- "
        f"{winner.display_name} {format_minor(own[winner.id], plan.currency)} "
        + ("was the cheaper special" if by_time else "applied instead")
    )
    if own[winner.id] >= own[rule.id]:
        text += (
            ": with the rest of the plan this stay comes to "
            f"{format_minor(fees[winner.id], plan.currency)} by {winner.display_name} and "
            f"{format_minor(fees[rule.id], plan.currency)} by {rule.display_name}"
        )
    return Line(code=RESOLVED, rule_id=rule.id, text=f"{text} {mode}", delta_minor=0)


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
            f"{rule.display_name} also qualified and was NOT applied: "
            f"{terminal.display_name} prices this stay by itself, so nothing further "
            "is charged"
        ),
        delta_minor=0,
    )


@dataclass(frozen=True)
class Stay:
    entry_at: datetime
    exit_at: datetime
    space_class: str
    #: How full the garage was when this car came in, in basis points of full:
    #: 8400 is 84%. Every car inside against every switched-on space, counted by
    #: the CALLER when the stay opened -- the engine counts nothing. None when the
    #: caller has no figure; a plan with a fill rule covering this stay's class
    #: then refuses it (GAP_NO_OCCUPANCY_AT_ENTRY), and a plan without one never
    #: reads it. It is read at ENTRY and only at entry: the cars that came in
    #: before the garage filled keep the price they came in on.
    occupancy_at_entry_bp: int | None = None

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
        return self.minutes_until(self.exit_at)

    def minutes_until(self, instant: datetime) -> int:
        """Whole minutes from entry to `instant`, rounded UP: `duration_minutes`
        of this stay as if it ended there, by the same arithmetic. The caps ask
        it of every day boundary in a stay (F59), so it is the one rounding
        `duration_minutes` describes, without a copy of the stay per question.
        """
        delta = instant - self.entry_at
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


#: 100% full, in basis points. A figure above it describes no garage.
FULL_BP = 10_000

#: **The longest stay this engine prices: 90 days, entry to exit** (Gokhan,
#: 2026-10-16). Days of 24 hours of elapsed time, so a clock change does not
#: move it: a stay of 90 days to the second is priced, and one second more is
#: refused with GAP_STAY_LONGER_THAN_MAX_STAY -- a car that has been in that long
#: needs an operator, not a number. THE one place the limit is stated.
#: `validate-plan` publishes it as `max_stay_minutes` (`max_stay_minutes()`), so
#: a rate setup can show the owner what the engine will and will not price.
#:
#: It also bounds the days a quote walks. Capping each day on its own (F59)
#: walks the stay a day at a time, so a quote's time grew with the days in the
#: stay -- a stay running to the year 9999 took fifteen seconds of CPU -- and
#: the limit is checked before the plan is even read (F62). It does not bound
#: the rest: a quote prices the stay once for each way of pricing it, so its
#: work also grows with the ways the plan offers (F64).
MAX_STAY_DAYS = 90

#: Minutes in a day of 24 hours.
MINUTES_IN_A_DAY = 24 * 60


def max_stay_minutes() -> int:
    """The longest stay priced, in the whole minutes `Stay.duration_minutes`
    counts: `MAX_STAY_DAYS` of 24 hours. Read from the constant at every call,
    never copied, so there is one number to change."""
    return MAX_STAY_DAYS * MINUTES_IN_A_DAY


def _longer_than_priced(stay: Stay) -> Finding | None:
    """The refusal for a stay longer than this engine prices, or None.

    Read from the two instants and nothing else -- no plan, no zone, no rule --
    so `quote` asks it FIRST, and ten thousand years are refused as quickly as
    ninety days and a second: no day of the stay is walked, no base is asked
    what it charged, and no plan is selected (F62). The comparison reads
    `duration_minutes`, as every duration comparison does (F20); a part-minute
    is a minute, so 90 days and one second is over the limit and 90 days is not.

    **A gap no rule can close, and `validate-plan` does not report it.** It is
    not a property of the plan: every plan stops at the same 90 days. It is a
    refusal of the ordinary kind -- 422, the code, nothing guessed -- so a door
    that closes a stay unpriced on a refusal closes this one unpriced too, and
    an operator prices it.
    """
    limit = max_stay_minutes()
    if stay.duration_minutes <= limit:
        return None
    return Finding(
        code=GAP_STAY_LONGER_THAN_MAX_STAY,
        text=(
            f"this engine prices a stay of at most {MAX_STAY_DAYS} days ({limit} minutes) "
            f"from entry to exit, and this one is {stay.duration_minutes} minutes: it was "
            "not priced and nothing was guessed -- an operator prices it"
        ),
    )


def make_stay(
    entry_at: datetime,
    exit_at: datetime,
    space_class: str,
    occupancy_at_entry_bp: int | None = None,
) -> Stay:
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
    figure = occupancy_at_entry_bp
    if figure is not None and (
        isinstance(figure, bool) or not isinstance(figure, int) or not 0 <= figure <= FULL_BP
    ):
        raise InvalidPlan(
            f"occupancy_at_entry_bp must be a whole number of basis points from 0 to "
            f"{FULL_BP} (0% to 100% full), or absent; got {figure!r}. A garage with more "
            "cars inside than spaces is sent as 10000."
        )
    return Stay(
        entry_at=entry_at, exit_at=exit_at, space_class=space_class,
        occupancy_at_entry_bp=figure,
    )


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


def find_gaps(plan: Plan, stay: Stay, qualified: _Qualified | None = None) -> list[Finding]:
    """Every reason this plan cannot price this stay, keyed by identifier.

    Called by the engine before it prices anything and by the validator over a
    matrix of stays. ONE function, so the sentence an owner reads in
    `validate-plan` and the sentence in a refusal cannot drift. `qualified` is
    the quote's own answer to which rules qualify (`_Qualified`); the validator
    passes none and one is made here.
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
    if qualified is None:
        qualified = _Qualified(plan, stay)

    if stay.occupancy_at_entry_bp is None:
        # Asked before anything can return early: a special qualifying does not
        # make the figure unnecessary, because the fill rule raises whichever
        # charge priced the time.
        needing = tuple(
            rule.id
            for stage in STAGES
            for rule in plan.rules_for_stage(stage)
            if NEEDS_OCCUPANCY in RULE_TRAITS[rule.type] and rule.covers(stay.space_class)
        )
        if needing:
            findings.append(
                Finding(
                    code=GAP_NO_OCCUPANCY_AT_ENTRY,
                    text=(
                        f"the plan prices a {stay.space_class!r} space on how full the "
                        f"garage was when the car came in ({', '.join(needing)}), and "
                        "this stay carries no occupancy_at_entry_bp -- nothing was "
                        "assumed"
                    ),
                    rule_ids=needing,
                )
            )

    if qualified.at(QUALIFY):
        # A special can price the stay. Whether the time-based rate could too is
        # asked by `_the_cheapest_way`, which uses it only when it can.
        return findings

    return findings + _time_based_gaps(plan, stay, qualified)


def _time_based_gaps(plan: Plan, stay: Stay, qualified: _Qualified) -> list[Finding]:
    """Why the time-based rate ALONE cannot price this stay. Empty when it can."""
    findings: list[Finding] = []
    accumulate = qualified.rules(ACCUMULATE)
    covering = [r for r in accumulate if r.covers(stay.space_class)]
    qualifying = qualified.at(ACCUMULATE)

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


def find_conflicts(plan: Plan, stay: Stay, qualified: _Qualified | None = None) -> list[Finding]:
    """More than one rule qualifying at one stage -- and it means three things.

    **This function used to report a conflict whenever more than one rule
    qualified at ANY stage, and that was a live defect waiting for a rule type.**
    It is right at QUALIFY, where two specials are competing bases and only one
    can be the price. It is wrong at CAP, where two ceilings simply both apply --
    and the moment `weekly_max` existed, every plan carrying a daily AND a weekly
    cap would have refused every stay in the garage.

    So the answer is per CATEGORY, and stages.py holds which is which:

    * RESOLVING -- a genuine either/or, and it is always settled: a TERMINAL
      rule wins outright, and otherwise the cheapest way is charged under either
      mode (F63) -- a tie there is the same money whichever rule is named, so
      since U7g it is priced, not refused, and the plan's mode names the rule.
    * COMPOSING, ORDER-INDEPENDENT -- both apply and the total is the same
      either way. Nothing to report and nothing to decide.
    * COMPOSING, ORDER-DEPENDENT -- both apply and the order changes the money,
      so the PLAN must state the order and a plan that has not is refused.

    `qualified` is the quote's own answer to which rules qualify, as for
    `find_gaps`; the validator passes none.
    """
    if qualified is None:
        qualified = _Qualified(plan, stay)
    findings: list[Finding] = []
    for stage in STAGES:
        qualifying = qualified.at(stage)
        one_per_stay = [r for r in qualifying if ONE_PER_STAY in RULE_TRAITS[r.type]]
        if len(one_per_stay) > 1:
            # Not an order the plan forgot to state: two fill rules raising one
            # charge are two answers to the same question, and an order would
            # charge both. Reported whatever `adjust_order` says.
            ids = tuple(r.id for r in one_per_stay)
            findings.append(
                Finding(
                    code=CONFLICT_OVERLAPPING_FILL_RULES,
                    text=(
                        f"{len(ids)} fill rules ({', '.join(ids)}) all apply to a "
                        f"{stay.space_class!r} space at "
                        f"{percent_text(stay.occupancy_at_entry_bp)} full; the plan "
                        "states "
                        "one fill rule per space class"
                    ),
                    rule_ids=ids,
                )
            )
        if len(qualifying) > 1:
            finding = _conflict_at(plan, stay, stage, qualifying)
            if finding is not None:
                findings.append(finding)
    return findings


def _conflict_at(plan: Plan, stay: Stay, stage: str, qualifying: list) -> Finding | None:
    """What more than one qualifying rule MEANS at this stage. None means nothing."""
    ids = tuple(r.id for r in qualifying)
    if stage in RESOLVING:
        # Never a conflict. A TERMINAL rule wins outright by what its type is; else
        # the cheapest way is charged, under either mode (F63), and a tie at that
        # fee is the same money whichever rule is named -- the plan's mode names
        # it (see `_rank`). W4, U7g and F63 between them: the engine has nothing
        # left to refuse here.
        return None
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
    too_long = _longer_than_priced(stay)
    if too_long is not None:
        # First of all, before a plan is read or a day walked (F62).
        raise Refused([too_long])
    plan = select_plan(plans, stay)
    # Which rules qualify, asked once for the whole quote (`_Qualified`).
    qualified = _Qualified(plan, stay)

    blocking = find_gaps(plan, stay, qualified) + find_conflicts(plan, stay, qualified)
    if blocking:
        raise Refused(blocking)

    ledger = _the_cheapest_way(plan, stay, qualified)

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


def _priced(
    plan: Plan, stay: Stay, base, qualified: _Qualified, compared: _Compared | None = None
) -> Ledger:
    """The stay through every stage, once, with `base` pricing the time.

    `base` is one way the stay can be priced: a special that qualified, a
    time-based rate that qualified, or a TERMINAL rule that prices the stay
    alone. `_the_cheapest_way` is the only caller. It prices each way once to
    learn its fee, with `compared` None -- the rules that lost get no line yet,
    and a line at zero moves no fee -- and then the cheapest way again with
    `compared`, so every rule that qualified and lost says what it charged, and
    why it was not used, on the receipt that is frozen on the stay.

    Which rules qualify is `qualified`, the quote's own, asked once for every
    pass: a pass asks no rule whether it qualifies, and finds a rule by its id.
    """
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

    qualified_at_qualify = qualified.at(QUALIFY)
    terminal = _terminal_rule([base])
    #: Whether a special prices the time on this pass, or the time-based rate.
    by_a_special = base.stage == QUALIFY
    #: The charge for the TIME: the running total when SURCHARGE begins, after
    #: the base (time-based rate or special) and the caps. A percent surcharge
    #: and the fill rule are taken of this, never of the running total, so they
    #: see the same number whatever else runs beside them. Set below.
    time_charge = None
    #: The special that priced the time on this pass, if one did, and what
    #: SURCHARGE added. Told to a rule that declares `TOLD_THE_PASS`.
    priced_by_special = base if by_a_special else None
    extras = 0
    #: How the charge for the time built up over the stay on this pass, told to
    #: a rule that declares `TOLD_THE_BASE` (the caps). Set when CAP begins.
    charged_by = None

    for stage in STAGES:
        if stage == CAP and terminal is None:
            charged_by = _charged_by(plan, stay, base, ledger.total_minor)
        if stage == SURCHARGE:
            time_charge = ledger.total_minor
        if stage == ADJUST:
            extras = ledger.total_minor - time_charge
        if terminal is not None and stage != QUALIFY:
            # A TERMINAL rule prices the stay by itself. Free means free: no
            # time-based charge, no cap, no surcharge, no adjustment. QUALIFY has
            # already run, so its lines -- including every `superseded` one -- are
            # in the ledger. See rules/grace.py.
            break
        if stage == ACCUMULATE and by_a_special:
            # A special prices the time on this pass, so no time-based rate does.
            # The comparison line says what the time-based rate would have
            # charged (`_the_cheapest_way`).
            continue

        if stage == QUALIFY and not by_a_special:
            # The time-based way. Every special still says why it was not used,
            # as on the special's way: one that did not qualify gives its own
            # reason, one that qualified and lost to a cheaper special says so.
            # The cheapest special's own line is the comparison line
            # `_the_cheapest_way` adds. These are frozen on every closed stay
            # and read in a dispute.
            cheapest = (
                _cheapest(plan, qualified_at_qualify, compared) if compared is not None else None
            )
            for rule in qualified.rules(QUALIFY):
                if qualified.has(rule):
                    if compared is not None and rule is not cheapest:
                        lost = _resolved_line(
                            rule, cheapest, QUALIFY, plan, compared, by_time=True
                        )
                        ledger.add(lost)
                    continue
                for line in qualified.why_not(rule):
                    ledger.add(line)
            continue

        if stage == QUALIFY:
            # A special's way, or a TERMINAL rule's. The base's own lines; each
            # other special that qualified says it lost, naming the base, the
            # prices and the mode -- the answer to the question an attendant is
            # asked at the counter -- or that a terminal rule priced the stay
            # alone; one that did not qualify gives its own reason.
            for rule in qualified.rules(QUALIFY):
                if rule is base:
                    for line in _lines_of(rule, RULE_APPLIERS[rule.type](rule, stay, plan)):
                        ledger.add(line)
                elif qualified.has(rule):
                    if terminal is not None:
                        ledger.add(_superseded_line(rule, terminal))
                    elif compared is not None:
                        ledger.add(_resolved_line(rule, base, QUALIFY, plan, compared))
                else:
                    for line in qualified.why_not(rule):
                        ledger.add(line)
            continue

        if stage == ACCUMULATE:
            # The time-based rate that is the base on this pass, and each other
            # one that qualified, saying it lost. One that did not qualify is
            # silent: outside QUALIFY, a rule that did not apply says nothing.
            for rule in qualified.rules(ACCUMULATE):
                if rule is base:
                    for line in _lines_of(rule, RULE_APPLIERS[rule.type](rule, stay, plan)):
                        ledger.add(line)
                elif compared is not None and qualified.has(rule):
                    ledger.add(_resolved_line(rule, base, ACCUMULATE, plan, compared))
            continue

        if stage == ADJUST:
            # Every ADJUST rule, the fill rule among them, in the cheapest order
            # (`_adjusted`): with a discount and a fill rule both applying, the
            # plan's order no longer decides the price.
            for line in _adjusted(
                plan, stay, ledger.total_minor, qualified.rules(stage),
                time_charge=time_charge, extras=extras, priced_by_special=priced_by_special,
                qualified=qualified,
            ):
                ledger.add(line)
            continue

        for rule in _in_application_order(plan, stage, qualified.rules(stage)):
            applier = RULE_APPLIERS[rule.type]
            if not qualified.has(rule) and not _speaks_anyway(rule, stay):
                continue
            given = (
                {"time_charge_minor": time_charge}
                if ON_THE_TIME_CHARGE in RULE_TRAITS[rule.type]
                else {}
            )
            if TOLD_THE_PASS in RULE_TRAITS[rule.type]:
                given.update(priced_by_special=priced_by_special, extras_minor=extras)
            if TOLD_THE_BASE in RULE_TRAITS[rule.type]:
                given["charged_by"] = charged_by
            if stage in STAGES_GIVEN_THE_RUNNING_TOTAL:
                lines = applier(rule, stay, plan, ledger.total_minor, **given)
            else:
                lines = applier(rule, stay, plan, **given)
            for line in _lines_of(rule, lines):
                ledger.add(line)

    return ledger


def _charged_by(plan: Plan, stay: Stay, base, base_minor: int):
    """How the charge for the time built up over the stay on this pass, or None.

    The caps cap each day and each week on its own (F59), so they need more than
    the running total: they need to know which day each part of it was charged
    in. The rule that priced the time on this pass -- `base`, the special or the
    time-based rate -- says, through the accrual its type registered: a function
    of minutes into the stay, or None when its type does not say. The engine
    does not know any type's arithmetic; it asks.

    **And it is checked against the ledger, on every quote.** What the base
    charges for the whole stay must be exactly what its lines added to the
    total. A type whose accrual said one thing and whose lines another would have
    the caps split a charge that is not the one on the receipt -- so a mismatch
    stops the quote, as `_assert_ledger_is_the_fee` does, rather than capping it.
    """
    accrual = RULE_ACCRUALS[base.type]
    charged_by = accrual(base, stay, plan) if accrual is not None else None
    if charged_by is not None and charged_by(stay.duration_minutes) != base_minor:
        raise AssertionError(
            f"rule {base.id!r} says it charges {charged_by(stay.duration_minutes)} for "
            f"this stay and its lines charged {base_minor}. The caps split the charge by "
            "the day from the first figure, so they would be capping a charge that is "
            "not the one on the receipt."
        )
    return charged_by


#: The line that says in which order the discounts and the fill rule were taken.
FILL_ORDER = "fill_level.order"

#: How a discount taken before the fill rule is set against the stay's two parts.
#: TIME_FIRST: the time charge, then the space-class extra. PER_PART: each part
#: carries its share of the discount, in proportion to what it charged, and a
#: part the fill rule raises takes the cent a share rounds to.
TIME_FIRST = "time_first"
PER_PART = "per_part"


def _adjusted(
    plan, stay, total_minor, rules, *, time_charge, extras, priced_by_special, qualified
):
    """The ADJUST stage's lines, in the order that charges the driver LEAST.

    His rule, 10-14 20:25, on a discount meeting the fill rule: "always the
    cheaper" -- never a cent more than the cheapest order, rounding included.
    The order changes the money in three ways: the fill rule raises what is left
    after the discounts before it, a discount after it takes its share of the
    increase too, and a discount taken before it can come off the part it raises
    or the part it does not. Which is cheapest depends on the stay -- a special
    that is not raised, a VIP extra that is, a rounding that lands a cent either
    way -- so it is not argued, it is priced: every order is priced, whole, and
    the cheapest charged, with one line saying which.

    The candidates, in the order a tie is settled (the first wins): the
    discounts first and the fill rule on what is left (set against the time
    charge first); the fill rule first; the discounts first, each part carrying
    its share and the fill rule raising what is left of the parts it raises;
    then the fill rule between the discounts, at each place, both ways. The
    discounts keep the plan's stated order among themselves. With no fill rule
    applying, or nothing beside it, the plan's order is the only one.

    Which rules qualify is the quote's own answer (`_Qualified`), so pricing an
    order asks no rule again whether it qualifies.
    """
    from .money import format_minor

    ordered = _in_application_order(plan, ADJUST, rules)
    fills = [r for r in ordered if r.type == "fill_level" and qualified.has(r)]
    fill_ids = {r.id for r in fills}
    others = [r for r in ordered if r.id not in fill_ids]
    beside = [r for r in others if qualified.has(r)]

    def run(order, split):
        lines: list[Line] = []
        running = total_minor
        taken = 0
        for rule in order:
            if not qualified.has(rule) and not _speaks_anyway(rule, stay):
                continue
            given: dict = {}
            if ON_THE_TIME_CHARGE in RULE_TRAITS[rule.type]:
                given["time_charge_minor"] = time_charge
            if TOLD_THE_PASS in RULE_TRAITS[rule.type]:
                time_left, extra_left = _left_after(
                    rule, taken, time_charge, extras, priced_by_special, split
                )
                given.update(
                    priced_by_special=priced_by_special, time_charge_minor=time_left,
                    extras_minor=extra_left, discounted_minor=taken,
                )
            applied = RULE_APPLIERS[rule.type](rule, stay, plan, running, **given)
            for line in _lines_of(rule, applied):
                lines.append(line)
                running += line.delta_minor
                if line.delta_minor < 0:
                    taken += -line.delta_minor
        return lines, running

    if len(fills) != 1 or not beside:
        return run(ordered, TIME_FIRST)[0]

    fill = fills[0]
    k = len(others)
    places = [(k, TIME_FIRST), (0, TIME_FIRST), (k, PER_PART)] + [
        (at, split) for at in range(1, k) for split in (TIME_FIRST, PER_PART)
    ]
    priced = []
    for at, split in places:
        order = others[:at] + [fill] + others[at:]
        lines, total = run(order, split)
        priced.append((total, at, split, lines))
    cheapest = min(priced, key=lambda p: p[0])  # min() keeps the first of a tie
    total, at, split, lines = cheapest
    if at == 0:
        how = "the fill rule first, then the discounts"
    elif at == k:
        how = (
            "the discounts first, then the fill rule on what is left"
            if split == TIME_FIRST
            else "the discounts first, each part its share, then the fill rule on what is left"
        )
    else:
        how = (
            f"the fill rule after {', '.join(r.id for r in others[:at])} and before "
            f"{', '.join(r.id for r in others[at:])}"
        )
    dearer = sorted({p[0] for p in priced if p[0] != total})
    other = (
        f"; another order would charge {', '.join(format_minor(t, plan.currency) for t in dearer)}"
        if dearer
        else "; every order charges the same"
    )
    return lines + [
        Line(
            code=FILL_ORDER,
            rule_id=fill.id,
            text=f"Discounts and the fill rule taken in the cheapest order: {how}{other}",
            delta_minor=0,
        )
    ]


def _left_after(fill, taken, time_charge, extras, priced_by_special, split):
    """What is left of the time charge and of the extra after `taken` came off.

    TIME_FIRST sets the discount against the time charge, then the extra.
    PER_PART gives each part its share, in proportion to what it charged; when
    only one of the two is raised by this fill rule on this pass -- the time
    unless a special priced it and specials are not raised; the extra when it
    is raised -- the raised part's share is rounded UP and the other part takes
    the rest, so a cent of rounding never lands on the driver.
    """
    if split == TIME_FIRST or not time_charge or not extras:
        time_off = min(time_charge, taken)
        return time_charge - time_off, max(0, extras - (taken - time_off))
    raises_time = priced_by_special is None or fill.params["raises_specials"]
    raises_extra = fill.params["raises_vip_extra"]
    whole = time_charge + extras
    taken = min(taken, whole)
    if raises_extra and not raises_time:
        extra_off = min(extras, -(-taken * extras // whole))
        time_off = taken - extra_off
    else:
        share = -(-taken * time_charge // whole) if raises_time else taken * time_charge // whole
        time_off = min(time_charge, share)
        extra_off = taken - time_off
    return time_charge - time_off, extras - extra_off


#: The line that says which way a stay was priced when a special qualified, and
#: what the other way would have charged (`compared_minor`).
SPECIAL_USED = "special_used"
TIME_BASED_USED = "time_based_used"


def _the_cheapest_way(plan: Plan, stay: Stay, qualified: _Qualified) -> Ledger:
    """The stay priced the way that charges the driver LEAST, and said so.

    His rule, 2026-10-11: "always cheaper goes first"; 2026-10-12, asked about
    an early bird at 9.00 against 7.00 by the hour: the driver always pays the
    cheapest way the stay can be priced; and 2026-10-16, for every case: **when
    more than one price could apply to the same time, the car pays the
    cheapest** (F50, F63).

    The ways a stay can be priced: each special that qualified, and each
    time-based rate that qualified -- those only where the time-based rate alone
    can price the stay. Each way is priced through the WHOLE pipeline, caps,
    surcharges and adjustments included, and the lowest fee is charged. A
    special keeps a tie with the time-based rate, as before; between two
    specials, or two time-based rates, see `_rank`.

    **What this replaced.** Two specials, or two time-based rates, were chosen
    between on what the RULES charged, and only the special that won was
    compared with the time-based rate on the fee; a cap can make the rule that
    charges more the cheaper stay. And under `stated_order` the plan's order
    chose outright, so a special replaced the time-based charge, and a dearer
    special a cheaper one, whatever the driver then paid. Both modes now charge
    the cheapest; the mode names one of two ways that charge the same.

    Unchanged: a TERMINAL rule (grace prices the stay alone, and free beats
    everything) and a stay no special qualified for that one time-based rate
    prices. Where the time-based rate alone cannot price the stay, the specials
    are the only ways, and the line says so.

    **The work.** With N ways, the stay is priced N + 1 times, and that is the
    rule itself: no way's fee is known until it has been through every stage.
    Nothing else is done per way. Which rules qualify is asked once for the
    quote (`qualified`), a rule is found by its id, a special that did not
    qualify is asked for its line once, and each way's own charge once. So the
    work grows with the ways times the plan's rules, and does not repeat a
    question per pair of them. F64 holds this with a budget.
    """
    from .money import format_minor

    specials = qualified.at(QUALIFY)
    terminal = _terminal_rule(specials)
    if terminal is not None:
        return _priced(plan, stay, terminal, qualified)
    times = () if _time_based_gaps(plan, stay, qualified) else qualified.at(ACCUMULATE)
    ways = specials + times
    if len(ways) == 1:
        # One way: nothing to choose between, so it is priced once.
        ledger = _priced(plan, stay, ways[0], qualified)
        if specials:
            ledger.add(_special_alone_line(plan, ways[0], ledger.total_minor))
        return ledger

    compared = _Compared(
        fees={rule.id: _priced(plan, stay, rule, qualified).total_minor for rule in ways},
        own=_candidate_totals(ways, stay, plan),
    )
    special = _cheapest(plan, specials, compared)
    time_based = _cheapest(plan, times, compared)
    if special is None:
        return _priced(plan, stay, time_based, qualified, compared)
    if time_based is None:
        with_special = _priced(plan, stay, special, qualified, compared)
        with_special.add(_special_alone_line(plan, special, compared.fees[special.id]))
        return with_special

    special_fee = compared.fees[special.id]
    named = f"{special.display_name} {format_minor(special_fee, plan.currency)}"
    mode = _mode_clause(plan, QUALIFY)
    time_fee = compared.fees[time_based.id]
    by_time = format_minor(time_fee, plan.currency)
    if time_fee < special_fee:
        time_way = _priced(plan, stay, time_based, qualified, compared)
        time_way.add(
            Line(
                code=TIME_BASED_USED,
                rule_id=special.id,
                text=f"{named} not used: by the time-based rate {by_time} is less {mode}",
                delta_minor=0,
                compared_minor=special_fee,
            )
        )
        return time_way
    with_special = _priced(plan, stay, special, qualified, compared)
    with_special.add(
        Line(
            code=SPECIAL_USED,
            rule_id=special.id,
            text=(
                f"{named} used: by the time-based rate this stay would be {by_time}"
                + (" too" if time_fee == special_fee else "")
                + f" {mode}"
            ),
            delta_minor=0,
            compared_minor=time_fee,
        )
    )
    return with_special


def _special_alone_line(plan: Plan, special, fee: int) -> Line:
    """The special charged where the time-based rate alone cannot price the stay
    (it stops before the stay ends, or no rule of it covers the class): there is
    no other way to compare it with, and the line says so rather than naming a
    number."""
    from .money import format_minor

    return Line(
        code=SPECIAL_USED,
        rule_id=special.id,
        text=(
            f"{special.display_name} {format_minor(fee, plan.currency)} used: the "
            f"time-based rate alone cannot price this stay {_mode_clause(plan, QUALIFY)}"
        ),
        delta_minor=0,
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
