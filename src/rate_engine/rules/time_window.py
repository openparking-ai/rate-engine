"""`time_window` -- ONE special rate. The window says WHEN; the effect says WHAT.

**Weekday, weekend, evening, morning, holiday, event and early bird are the same
rule.** Gokhan, 2026-09-07: *"they are all the same method. enter by exit by.
what we need to do is to create a drop down button, week days, weekends,
evenings, mornings. what ever they select display the options and have them
enter the enter by exit by."* They differ in which days they apply on and what
hours are typed into them, and both are fields. So there is one rule type here
rather than seven, and `early_bird` was this rule with its days hardcoded to
every day and its effect hardcoded to flat.

**And the effect is not only a flat price.** *"it is not only %. or increase or
discount. it could be a complete different rate."* Three effects, one condition:

* `flat` -- one price for the whole stay. The early bird.
* `rate` -- a completely different time-based rate for this stay. It takes the
  fields `increment` takes and is priced by `increment`'s own code; see below.
* `adjust` -- a percentage or an amount, up or down, ON THE WHOLE FEE.

**The engine never stores the word "weekend".** A preset is a UI shortcut whose
meaning changes with the country: "weekend" is Friday-to-Monday to the operator
who asked for this and Saturday-to-Sunday elsewhere. Storing the word would put a
pricing decision inside the engine, which is the one thing §8 forbids. The
dropdown expands to actual days before the plan is written; what the rule carries
is `applies_on` and the operator's own `label`.

**The label is the operator's, and the engine never derives or checks it.** A
rule labelled "Weekend rate" that states `mon` is a garage that means it. It
renders in the breakdown because §8's first requirement is that a customer can
read why they were charged what they were charged.

ALL CONDITIONS OR NOTHING (§8): the stay must satisfy EVERY condition -- the day,
both ends of the entry range, the day span, the exit limit, and a `rate` effect's
own ceiling. Miss one by a minute and the window does not apply AT ALL. No
pro-rating, no partial credit, no cheaper-of-the-two.

**`applies_on` is matched against the ENTRY's local date.** That is §8's
entry-time rule and it is Gokhan's own event case: a car that entered before the
event pays the ordinary rate. Two kinds, and there will not be a third built in:

* `days_of_week` -- the recurring case. Weekday, weekend, evening and morning
  rates are all this, with different days and different hours.
* `dates` -- the garage types its own dates, and that is how holidays and events
  are stated. **There is no built-in holiday calendar and there will not be one:**
  it would be wrong for every country but the one it shipped for, and a wrong
  free day is a pricing decision nobody made.

**`enter_from` is why an evening rate is expressible at all.** A rule stating
only "enter by 23:59" catches the seven-a.m. car as well as the seven-p.m. one. A
garage that genuinely does not care about the lower bound writes `00:00`, where
its own document shows it. An `enter_from` later than `enter_by` would have to
wrap past midnight; that is REFUSED, and the refusal says to state it as two
rules. Recorded in docs/CONTRACT.md as a stated gap rather than left to surface
as a wrong fee.

**`day_span` has no default, and it exists because the engine used to decide it.**
The rule this replaces compared the exit's local DATE to the entry's and refused
any cross-midnight stay -- a condition the plan could not state and could not
remove. Asked directly, Gokhan said: *"I've never seen multiple day early bird
but this is parking. People get creative."*

* `"same_day"` -- entry and exit fall on the same local date.
* `"next_day"` -- exit falls on the entry's local date or the one after. This is
  the Friday-night pair; without it `any_span` prices a car that left on the
  MONDAY at 05:00 under the same overnight rate.
* `"any_span"` -- the wall-clock limits are the whole test.

**WHERE THIS RULE RUNS DEPENDS ON ITS EFFECT, and that is the one structural
change this round makes to the framework.** `flat` and `rate` are BASES: they
replace the time-based charge, so they run at QUALIFY exactly as `early_bird`
did. `adjust` is not a base -- it modifies the total -- so it runs at ADJUST,
the last stage, AFTER the caps and the surcharges. That is what "on all" means,
and applying it earlier would take a percentage of a number the customer is not
being charged. The stage is DERIVED from the effect and cross-checked against the
one the plan states; see `rules/__init__.py`.

**A `rate` effect is priced by `increment`, not by a copy of it.** It calls
`increment.build_params` and `increment.lines_for`, so a weekend rate and a
weekday rate cannot drift apart -- and when a period calculation drifts, the
difference is money on somebody's receipt.

Every condition is evaluated in the PLAN's timezone, on the local wall clock,
because "exit by 5 pm" is a wall-clock idea. See plan.py on why that zone is
required and why a naive timestamp is refused.

**One asymmetry, recorded rather than hidden.** `rounding` is required on every
`adjust` effect, and a `fixed` amount has nothing to round -- so on that shape
the field is stated and never read. The brief this was built from states
`rounding` at the effect level rather than inside the percent amount, and a
frozen brief's field layout is not this session's to redesign; it is written down
here, in docs/CONTRACT.md, and in the round's receipt instead.
"""

from __future__ import annotations

from datetime import date

from ..breakdown import Line
from ..money import as_non_negative_minor, format_minor
from ..stages import ADJUST, QUALIFY
from ..wallclock import DAYS_OF_WEEK, local_minute, parse_limit
from . import (
    SPEAKS_UNQUALIFIED,
    Rule,
    check_stated_stage,
    common_fields,
    increment,
    register,
)

#: The two ways a plan may state WHEN a window applies.
APPLIES_ON_KINDS: tuple[str, ...] = ("days_of_week", "dates")

#: What a PLAN may state. NO DEFAULT, like every other field in this module.
DAY_SPANS: tuple[str, ...] = ("same_day", "next_day", "any_span")

#: How many whole local days the exit may fall after the entry. `None` is
#: unbounded. Data rather than a chain of `if`s, so adding a span is a row here
#: and `_span_failure` fails loudly if one arrives with no sentence to explain it.
DAY_SPAN_LIMITS: dict[str, int | None] = {"same_day": 0, "next_day": 1, "any_span": None}

#: The three effects, and WHERE each one runs. A base replaces the time-based
#: charge and runs at QUALIFY; an adjustment modifies the total and runs at
#: ADJUST, after the caps and the surcharges.
EFFECT_STAGES: dict[str, str] = {"flat": QUALIFY, "rate": QUALIFY, "adjust": ADJUST}

#: Every stage this type may run at, for the registry. Derived from the table
#: above rather than written twice.
STAGES_RUN_AT: tuple[str, ...] = (QUALIFY, ADJUST)

DIRECTIONS: tuple[str, ...] = ("discount", "increase")
AMOUNT_KINDS: tuple[str, ...] = ("percent", "fixed")

#: Which way a fractional minor unit goes. Stated per rule, no default: a
#: percentage lands on a fraction of a cent and somebody has to say who keeps it.
ADJUST_ROUNDINGS: tuple[str, ...] = ("up", "down")

#: 20% is 2000. **Basis points, because a percent field that could be `20.5`
#: would either be refused by `money.refuse_non_integer_money` -- which rejects a
#: float anywhere in a plan -- or put a float into the pricing path. Integers end
#: to end.**
BASIS_POINTS_PER_WHOLE: int = 10_000

APPLIED = "time_window.applied"
NOT_APPLIED = "time_window.not_applied"

EXTRA = {"label", "applies_on", "enter_from", "enter_by", "exit_by", "day_span", "effect"}


# --- the condition: WHEN --------------------------------------------------


def _days(value: dict, where: str) -> tuple[str, ...]:
    from ..plan import InvalidPlan

    unknown_keys = sorted(set(value) - {"kind", "days"})
    if unknown_keys:
        raise InvalidPlan(
            f"{where} carries key(s) this version does not understand: "
            f"{', '.join(unknown_keys)}. Rejected, not ignored."
        )
    days = value.get("days")
    if not isinstance(days, list) or not days or not all(isinstance(d, str) for d in days):
        raise InvalidPlan(
            f"{where}.days must be a non-empty list of day names, from "
            f"{', '.join(DAYS_OF_WEEK)}."
        )
    unknown = sorted(set(days) - set(DAYS_OF_WEEK))
    if unknown:
        raise InvalidPlan(
            f"{where}.days names {', '.join(unknown)}, which this version does not "
            f"know. Expected one or more of {', '.join(DAYS_OF_WEEK)}. A preset such "
            "as 'weekend' is refused here on purpose -- it means Friday to Monday in "
            "one country and Saturday to Sunday in another, so the days are stated."
        )
    if len(set(days)) != len(days):
        raise InvalidPlan(f"{where}.days contains a duplicate.")
    return tuple(days)


def _dates(value: dict, where: str) -> tuple[date, ...]:
    from ..plan import InvalidPlan

    unknown_keys = sorted(set(value) - {"kind", "dates"})
    if unknown_keys:
        raise InvalidPlan(
            f"{where} carries key(s) this version does not understand: "
            f"{', '.join(unknown_keys)}. Rejected, not ignored."
        )
    raw_dates = value.get("dates")
    if (
        not isinstance(raw_dates, list)
        or not raw_dates
        or not all(isinstance(d, str) for d in raw_dates)
    ):
        raise InvalidPlan(f"{where}.dates must be a non-empty list of 'YYYY-MM-DD' strings.")
    parsed: list[date] = []
    for item in raw_dates:
        try:
            day = date.fromisoformat(item)
        except ValueError as exc:
            raise InvalidPlan(
                f"{where}.dates carries {item!r}, which is not a 'YYYY-MM-DD' date ({exc})."
            ) from exc
        if day.isoformat() != item:
            raise InvalidPlan(
                f"{where}.dates carries {item!r}. A date here is written 'YYYY-MM-DD'; "
                "the compact and week-date spellings ISO 8601 also allows are refused, "
                "because a date the breakdown renders differently from the way the plan "
                "states it is a decision an operator cannot check."
            )
        parsed.append(day)
    if len(set(parsed)) != len(parsed):
        raise InvalidPlan(f"{where}.dates contains a duplicate.")
    return tuple(parsed)


def _applies_on(raw: dict, where: str) -> dict:
    """The days this window applies on, as data. Refused by name if it is neither kind."""
    from ..plan import InvalidPlan

    field = f"{where}.applies_on"
    value = raw["applies_on"]
    if not isinstance(value, dict) or "kind" not in value:
        raise InvalidPlan(
            f"{field} must be an object carrying a `kind` of {' or '.join(APPLIES_ON_KINDS)}."
        )
    kind = value["kind"]
    if kind == "days_of_week":
        return {"kind": kind, "days": _days(value, field)}
    if kind == "dates":
        return {"kind": kind, "dates": _dates(value, field)}
    raise InvalidPlan(
        f"{field}.kind is {kind!r}; expected one of {', '.join(APPLIES_ON_KINDS)}. "
        "A recurring rate states its days; a holiday or an event states its dates. "
        "There is no built-in calendar and no preset: both would be right for one "
        "country and wrong for every other."
    )


# --- the effect: WHAT ------------------------------------------------------


def _positive_whole(value: object, label: str) -> int:
    from ..plan import InvalidPlan

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidPlan(
            f"{label} must be a positive whole number. An adjustment of nothing is a "
            "rule that does nothing, and the direction carries the sign."
        )
    return value


def _amount(value: object, where: str) -> dict:
    from ..plan import InvalidPlan

    if not isinstance(value, dict) or "kind" not in value:
        raise InvalidPlan(
            f"{where} must be an object carrying a `kind` of {' or '.join(AMOUNT_KINDS)}."
        )
    kind = value["kind"]
    if kind == "percent":
        unknown = sorted(set(value) - {"kind", "percent_bp"})
        if unknown:
            raise InvalidPlan(
                f"{where} carries key(s) this version does not understand: "
                f"{', '.join(unknown)}. Rejected, not ignored."
            )
        if "percent_bp" not in value:
            raise InvalidPlan(
                f"{where} is missing required field(s): percent_bp. It is INTEGER BASIS "
                "POINTS -- 20% is 2000 and 12.5% is 1250 -- because a percentage written "
                "as a decimal would be a float, and a float anywhere in a plan is refused."
            )
        return {
            "kind": kind,
            "percent_bp": _positive_whole(value["percent_bp"], f"{where}.percent_bp"),
        }
    if kind == "fixed":
        unknown = sorted(set(value) - {"kind", "minor"})
        if unknown:
            raise InvalidPlan(
                f"{where} carries key(s) this version does not understand: "
                f"{', '.join(unknown)}. Rejected, not ignored."
            )
        if "minor" not in value:
            raise InvalidPlan(f"{where} is missing required field(s): minor.")
        as_non_negative_minor(value["minor"], f"{where}.minor")
        return {"kind": kind, "minor": _positive_whole(value["minor"], f"{where}.minor")}
    raise InvalidPlan(
        f"{where}.kind is {kind!r}; expected one of {', '.join(AMOUNT_KINDS)}."
    )


def _effect(value: object, where: str) -> dict:
    """WHAT this window does when it applies, validated. One of exactly three kinds."""
    from ..plan import InvalidPlan

    if not isinstance(value, dict) or "kind" not in value:
        raise InvalidPlan(
            f"{where} must be an object carrying a `kind` of "
            f"{', '.join(sorted(EFFECT_STAGES))}."
        )
    kind = value["kind"]

    if kind == "flat":
        unknown = sorted(set(value) - {"kind", "price_minor"})
        if unknown:
            raise InvalidPlan(
                f"{where} carries key(s) this version does not understand: "
                f"{', '.join(unknown)}. Rejected, not ignored."
            )
        if "price_minor" not in value:
            raise InvalidPlan(f"{where} is missing required field(s): price_minor.")
        return {
            "kind": kind,
            "price_minor": as_non_negative_minor(value["price_minor"], f"{where}.price_minor"),
        }

    if kind == "rate":
        unknown = sorted(set(value) - ({"kind"} | increment.EXTRA))
        if unknown:
            raise InvalidPlan(
                f"{where} carries key(s) this version does not understand: "
                f"{', '.join(unknown)}. Rejected, not ignored."
            )
        # THE SAME BUILDER `increment` uses, not a second copy of it.
        return {"kind": kind, "rate": increment.build_params(value, where)}

    if kind == "adjust":
        unknown = sorted(set(value) - {"kind", "direction", "amount", "rounding"})
        if unknown:
            raise InvalidPlan(
                f"{where} carries key(s) this version does not understand: "
                f"{', '.join(unknown)}. Rejected, not ignored."
            )
        missing = sorted({"direction", "amount", "rounding"} - set(value))
        if missing:
            raise InvalidPlan(
                f"{where} is missing required field(s): {', '.join(missing)}. "
                "This module has no defaults; a field it cannot read is a pricing "
                "decision nobody made."
            )
        direction = value["direction"]
        if direction not in DIRECTIONS:
            raise InvalidPlan(
                f"{where}.direction is {direction!r}; expected one of "
                f"{', '.join(DIRECTIONS)}. The amount is a positive magnitude and this "
                "is what gives it a sign, so that a plan cannot express a discount by "
                "writing a negative number somebody later reads as an increase."
            )
        rounding = value["rounding"]
        if rounding not in ADJUST_ROUNDINGS:
            raise InvalidPlan(
                f"{where}.rounding is {rounding!r}; expected one of "
                f"{', '.join(ADJUST_ROUNDINGS)}. There is no default: a percentage of a "
                "fee lands on a fraction of a minor unit, and who keeps that fraction is "
                "the owner's decision rather than the engine's."
            )
        return {
            "kind": kind,
            "direction": direction,
            "amount": _amount(value["amount"], f"{where}.amount"),
            "rounding": rounding,
        }

    raise InvalidPlan(
        f"{where}.kind is {kind!r}; expected one of {', '.join(sorted(EFFECT_STAGES))}. "
        "A window is a flat price, a completely different time-based rate, or an "
        "adjustment up or down on the whole fee."
    )


# --- building --------------------------------------------------------------


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan

    if not isinstance(raw, dict) or "effect" not in raw:
        raise InvalidPlan(
            f"{where} is missing required field(s): effect. A window says WHEN it "
            "applies and its effect says WHAT it does; without one there is no rate."
        )
    effect = _effect(raw["effect"], f"{where}.effect")
    stage = EFFECT_STAGES[effect["kind"]]

    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
    # DERIVED from the effect, then checked against what the document claims.
    # This type runs at two stages, so the framework cannot do it for us.
    check_stated_stage(raw, where, stage)

    label = raw["label"]
    if not isinstance(label, str) or not label.strip():
        raise InvalidPlan(
            f"{where}.label must be a non-empty string. It is what the operator calls "
            "this rate -- 'Weekend rate', 'Early bird', 'Evening rate' -- and it is the "
            "name the customer reads in the breakdown, so the engine will not invent one."
        )

    day_span = raw["day_span"]
    if day_span not in DAY_SPANS:
        raise InvalidPlan(
            f"{where}.day_span is {day_span!r}; expected one of {', '.join(DAY_SPANS)}. "
            "There is no default: whether this window may run past midnight, and how "
            "far, is a pricing decision, and the engine used to make it for you."
        )

    enter_from = parse_limit(raw, "enter_from", where)
    enter_by = parse_limit(raw, "enter_by", where)
    if enter_from > enter_by:
        raise InvalidPlan(
            f"{where}.enter_from is {enter_from:%H:%M}, which is after "
            f"{where}.enter_by ({enter_by:%H:%M}), so the entry window would have to "
            "wrap past midnight. That is refused rather than assumed: state it as TWO "
            "rules -- one running to 23:59 and one starting at 00:00 -- so the document "
            "says which days each half applies on, which is a decision this engine "
            "cannot make for you."
        )

    params = {
        "applies_on": _applies_on(raw, where),
        "enter_from": enter_from,
        "enter_by": enter_by,
        "exit_by": parse_limit(raw, "exit_by", where),
        "day_span": day_span,
        "effect": effect,
    }
    return Rule(
        id=rule_id, type="time_window", stage=stage, space_classes=space_classes,
        params=params, label=label,
    )


# --- qualifying ------------------------------------------------------------


def _applies_on_the_entry_date(applies_on: dict, entry_local) -> bool:
    """Does this window cover the day the car ARRIVED on?

    Entry, never exit -- §8's entry-time rule, and the reason an event never
    reaches back into a car that was already parked.
    """
    if applies_on["kind"] == "days_of_week":
        return DAYS_OF_WEEK[entry_local.weekday()] in applies_on["days"]
    return entry_local.date() in applies_on["dates"]


def _day_failure(applies_on: dict, entry_local) -> str:
    if applies_on["kind"] == "days_of_week":
        return f"{entry_local:%A} is not one of {', '.join(applies_on['days'])}"
    stated = ", ".join(day.isoformat() for day in applies_on["dates"])
    return f"{entry_local.date().isoformat()} is not one of {stated}"


def _span_failure(day_span: str, limit: int, entry_local, exit_local) -> str:
    # A row per BOUNDED span, so a span added to DAY_SPAN_LIMITS with no sentence
    # to explain it dies here loudly rather than printing a blank.
    relation = {
        0: "is not the same local day as entry",
        1: "is more than one local day after entry",
    }[limit]
    return (
        f"exit {exit_local:%H:%M} on {exit_local:%a %d %b} {relation} "
        f"({entry_local:%a %d %b}), and this rule states day_span {day_span!r}"
    )


def _failures(rule: Rule, stay, plan) -> list[str]:
    """Why this stay fails the rule, in plain English. Empty means it qualifies.

    NOT every failed condition, and the difference is two `elif`s. The DAY is
    tested on its own and always reports -- it is the first thing an operator is
    asked about ("why is Saturday not the weekend rate?"). The entry pair is one
    test: `enter_from` is never later than `enter_by`, so a stay cannot be both
    too early and too late, and reporting one of them is reporting all that
    happened. The exit side is the day-span check OR the wall-clock limit, never
    both: a `same_day` stay that crossed midnight reports the day span alone,
    even when it also left after `exit_by`.

    Said here because the docstring this inherited used to promise every
    condition and the code has never done that. Which line comes back changes
    nothing about WHETHER the rate applies -- it is all-conditions-or-nothing
    either way -- so the wording was what was wrong, not the structure.
    """
    # TRUNCATED TO THE MINUTE, and the limit is refused if it is finer -- see
    # wallclock.py. Compared at full precision, an entry at 09:00:00.001 failed a
    # 09:00 limit and the line below rendered "entry 09:00 is after the 09:00
    # entry limit": a sentence contradicting itself, deciding $18 on a microsecond.
    entry_local = local_minute(stay.entry_at, plan.timezone)
    exit_local = local_minute(stay.exit_at, plan.timezone)
    failed: list[str] = []

    if not _applies_on_the_entry_date(rule.params["applies_on"], entry_local):
        failed.append(_day_failure(rule.params["applies_on"], entry_local))

    if entry_local.time() < rule.params["enter_from"]:
        failed.append(
            f"entry {entry_local:%H:%M} is before the "
            f"{rule.params['enter_from']:%H:%M} entry window opens"
        )
    elif entry_local.time() > rule.params["enter_by"]:
        failed.append(
            f"entry {entry_local:%H:%M} is after the "
            f"{rule.params['enter_by']:%H:%M} entry limit"
        )

    days_after = (exit_local.date() - entry_local.date()).days
    span_limit = DAY_SPAN_LIMITS[rule.params["day_span"]]
    if span_limit is not None and days_after > span_limit:
        failed.append(_span_failure(rule.params["day_span"], span_limit, entry_local, exit_local))
    elif exit_local.time() > rule.params["exit_by"]:
        # Under 'any_span' the wall-clock limit is the whole exit test, so an
        # overnight stay leaving before the limit qualifies. Under a bounded span
        # a stay that ran past it has already failed above and never reaches here.
        failed.append(
            f"exit {exit_local:%H:%M} is after the {rule.params['exit_by']:%H:%M} limit"
        )

    # A `rate` effect carries its own ceiling, and it is a condition like any
    # other: a stay past it is not priced at the ceiling and not pro-rated -- the
    # window does not apply, and the stay falls to the plan's ordinary rate or
    # becomes a gap the owner is asked about. Without this the window would price
    # a stay its own stated rate says it cannot, which is F1.
    effect = rule.params["effect"]
    if effect["kind"] == "rate":
        ceiling = effect["rate"]["max_duration_minutes"]
        if ceiling is not None and stay.duration_minutes > ceiling:
            failed.append(
                f"the stay is {stay.duration_minutes} minutes and this rate stops at "
                f"{ceiling}"
            )
    return failed


def qualifies(rule: Rule, stay, plan) -> bool:
    return rule.covers(stay.space_class) and not _failures(rule, stay, plan)


# --- applying --------------------------------------------------------------


def _window_clause(rule: Rule, entry_local) -> str:
    return (
        f"entered {entry_local:%a %d %b} between {rule.params['enter_from']:%H:%M} and "
        f"{rule.params['enter_by']:%H:%M}, exited by {rule.params['exit_by']:%H:%M}, "
        f"day span {rule.params['day_span']}"
    )


def _percent(basis_points: int) -> str:
    """2000 -> '20%', 1250 -> '12.5%'. Integer arithmetic; no float is created."""
    whole, fraction = divmod(basis_points, 100)
    if fraction == 0:
        return f"{whole}%"
    return f"{whole}.{fraction:02d}".rstrip("0") + "%"


def _magnitude(effect: dict, running_total_minor: int) -> int:
    """How much this adjustment moves the fee, as a positive number of minor units.

    Integer end to end. A percentage is basis points times the total divided by
    10,000, and the division is the only place a fraction of a minor unit can
    appear -- so it is the only place `rounding` is read.
    """
    amount = effect["amount"]
    if amount["kind"] == "fixed":
        return amount["minor"]
    product = running_total_minor * amount["percent_bp"]
    if effect["rounding"] == "down":
        return product // BASIS_POINTS_PER_WHOLE
    return -(-product // BASIS_POINTS_PER_WHOLE)  # ceil, integer only


def _adjust_line(rule: Rule, plan, running_total_minor: int) -> Line:
    effect = rule.params["effect"]
    currency = plan.currency
    magnitude = _magnitude(effect, running_total_minor)
    discount = effect["direction"] == "discount"
    amount = effect["amount"]

    if amount["kind"] == "percent":
        measure = (
            f"{_percent(amount['percent_bp'])} {effect['direction']} on "
            f"{format_minor(running_total_minor, currency)} "
            f"(rounded {effect['rounding']})"
        )
    else:
        measure = (
            f"{format_minor(amount['minor'], currency)} {effect['direction']} on "
            f"{format_minor(running_total_minor, currency)}"
        )
    return Line(
        code=APPLIED,
        rule_id=rule.id,
        text=(
            f"{rule.display_name}: {measure} -- "
            f"{format_minor(magnitude, currency)} {'off' if discount else 'added'}"
        ),
        delta_minor=-magnitude if discount else magnitude,
    )


def apply(rule: Rule, stay, plan, running_total_minor: int | None = None) -> list[Line]:
    """Qualified: the effect's lines. Not qualified: one line at zero, saying why.

    The not-qualified branch is not an error path and not an omission. A
    breakdown that mentions a special only when it applies cannot answer "why am
    I not getting the weekend rate", which is the question this module was asked
    to make answerable.

    `running_total_minor` is passed by the engine at ADJUST, the way it is at
    CAP, and is required there: an adjustment is defined in terms of the total.
    It still cannot SET the total -- it returns a Line like everything else.

    ONE applier for both kinds of `applies_on` and all three effects. A holiday
    and a Saturday produce the same sentence, naming the day the car actually
    arrived on rather than reciting the rule's whole list -- a garage with thirty
    stated holidays would otherwise put all thirty on one customer's receipt.
    """
    from ..plan import InvalidPlan

    failed = _failures(rule, stay, plan)
    if failed:
        # The consequence differs by effect, and saying the wrong one would be a
        # sentence that is false on a receipt. A base that did not apply means the
        # stay prices on the time-based rate; an adjustment that did not apply
        # means the fee stands as it is. "The stay prices on the time-based rate"
        # under a declined weekend discount would tell a customer their whole
        # basis had changed, which is not what happened.
        consequence = (
            "so the fee is not adjusted"
            if rule.params["effect"]["kind"] == "adjust"
            else "so the stay prices on the time-based rate"
        )
        return [
            Line(
                code=NOT_APPLIED,
                rule_id=rule.id,
                text=(
                    f"{rule.display_name} NOT applied: {'; '.join(failed)}. All of "
                    f"its conditions must hold, {consequence}"
                ),
                delta_minor=0,
            )
        ]

    effect = rule.params["effect"]
    entry_local = local_minute(stay.entry_at, plan.timezone)

    if effect["kind"] == "flat":
        return [
            Line(
                code=APPLIED,
                rule_id=rule.id,
                text=(
                    f"{rule.display_name} "
                    f"{format_minor(effect['price_minor'], plan.currency)} "
                    f"({_window_clause(rule, entry_local)}) -- replaces the time-based charge"
                ),
                delta_minor=effect["price_minor"],
            )
        ]

    if effect["kind"] == "rate":
        # The header carries no money: the lines below it do, and they are
        # `increment`'s own, produced by `increment`'s own code.
        header = Line(
            code=APPLIED,
            rule_id=rule.id,
            text=(
                f"{rule.display_name} ({_window_clause(rule, entry_local)}) -- "
                "this time-based rate replaces the standard one"
            ),
            delta_minor=0,
        )
        return [header] + increment.lines_for(
            effect["rate"], rule.id, stay.duration_minutes, plan.currency
        )

    if running_total_minor is None:
        raise InvalidPlan(
            f"rule {rule.id!r} has an `adjust` effect and was applied without a running "
            "total. An adjustment is a percentage or an amount ON the fee, so it runs at "
            "ADJUST and is shown the total the way a cap is. This is a wiring fault in "
            "the caller, not a plan that is wrong."
        )
    return [_adjust_line(rule, plan, running_total_minor)]


# SPEAKS_UNQUALIFIED, and it is the reason the trait exists.
#
# A window at QUALIFY already speaks either way -- the engine asks every QUALIFY
# rule for lines. One at ADJUST did not, because the framework's silence rule was
# keyed on the STAGE: outside QUALIFY, a rule that did not apply was assumed to
# have not applied because it was never about this space, and a receipt listing
# every VIP tier a standard bay is not charged for is noise.
#
# That assumption held until this type existed. A weekend discount declining
# because it is a Tuesday is not noise -- it is the answer to "why didn't I get
# the weekend discount?", which is precisely the question §8 exists to make
# answerable, and it was missing from the breakdown. The type says so about
# itself rather than the engine knowing its name; coverage still governs, so a
# window scoped to VIP stays silent on a standard receipt.
register("time_window", STAGES_RUN_AT, build, apply, traits=(SPEAKS_UNQUALIFIED,))
