"""`weekly_max` -- a cap on the week, and `daily_max`'s shape one unit up.

§8 names it in Gokhan's own list of rate types, beside the daily maximum. It is
the same mechanism: a ceiling on the running total, expressed in the ledger as a
NEGATIVE line saying how much it took off, so the fee stays equal to the sum of
its lines and the operator sees the size of the reduction rather than a bare
"cap applied".

**`week_boundary` is required with no default, for exactly `daily_max`'s
reason.** "Weekly max 100" does not say what a week is, and the two honest
answers price a Saturday-to-Tuesday stay differently:

* `calendar_week` -- the cap is per local week the stay touches, and the week
  starts on the day the plan names. There is no universal answer to which day
  that is: it is Monday in most of Europe, Sunday in the United States, and
  Saturday in parts of the Middle East. The engine will not pick.
* `rolling_7d` -- the cap is per seven days from ENTRY. The starting day is
  irrelevant, so `week_starts_on` is `null` and the null has to be TYPED.

**`week_starts_on` is required in BOTH cases**, the way `max_duration_minutes`
is: null is a statement, and a field that may be absent is a field somebody can
forget while believing they set it.

**TWO caps on one plan are not a conflict.** They compose, and the lower ceiling
wins -- which falls out of applying them in sequence rather than being arranged,
and is why CAP is a composing stage rather than a resolving one. See stages.py:
`find_conflicts` used to refuse whenever more than one rule qualified anywhere,
so this rule type's arrival would have made every plan carrying a daily AND a
weekly cap refuse every stay in the garage.

**A week costs no more than the daily caps of the days in it.** The stay is cut
at its week boundaries, and each week is allowed the weekly max or, where the
plan also caps the day, the daily max times the days the car is in that week,
whichever is lower. Seven days and an hour at 30 a day and 100 a week is 100
for the first week and 30 for the hour, not 100 twice. This reads the daily
caps' terms from the plan, never their lines, so the two caps still compose in
either order. And like a day, a week the car is in for no time is not a week it
touched: an exit at exactly the start of a week adds no cap.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from ..breakdown import Line
from ..money import as_non_negative_minor, format_minor
from ..stages import CAP
from ..wallclock import DAYS_OF_WEEK
from . import Rule, common_fields, daily_max, register

WEEK_BOUNDARIES: tuple[str, ...] = ("calendar_week", "rolling_7d")

#: Which boundary requires a starting day, and which requires it to be null.
#: A table rather than two `if`s, so the refusal messages below cannot disagree
#: with what the builder actually accepts.
NEEDS_A_STARTING_DAY: dict[str, bool] = {"calendar_week": True, "rolling_7d": False}

DAYS_IN_A_WEEK = 7

EXTRA = {"max_minor", "week_boundary", "week_starts_on"}


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan

    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
    boundary = raw["week_boundary"]
    if boundary not in WEEK_BOUNDARIES:
        raise InvalidPlan(
            f"{where}.week_boundary is {boundary!r}; expected one of "
            f"{', '.join(WEEK_BOUNDARIES)}. There is no default: a cap of 100 a week "
            "prices a Saturday-to-Tuesday stay at 100 or at 200 depending on the "
            "answer, and that is the owner's decision."
        )

    starts_on = raw["week_starts_on"]
    if NEEDS_A_STARTING_DAY[boundary]:
        if starts_on not in DAYS_OF_WEEK:
            raise InvalidPlan(
                f"{where}.week_starts_on is {starts_on!r}; a 'calendar_week' cap needs "
                f"a day name from {', '.join(DAYS_OF_WEEK)}. There is no universal "
                "first day of the week -- it is Monday in most of Europe, Sunday in "
                "the United States, and Saturday in parts of the Middle East -- so the "
                "plan says which, and the engine does not pick."
            )
    elif starts_on is not None:
        raise InvalidPlan(
            f"{where}.week_starts_on is {starts_on!r}, but this rule states "
            "'rolling_7d', where a week runs from the stay's own entry and no starting "
            "day applies. Write null: a value that cannot affect the fee would read as "
            "a decision somebody made and the engine ignored."
        )

    return Rule(
        id=rule_id, type="weekly_max", stage=CAP, space_classes=space_classes,
        params={
            "max_minor": as_non_negative_minor(raw["max_minor"], f"{where}.max_minor"),
            "week_boundary": boundary,
            "week_starts_on": starts_on,
        },
    )


def qualifies(rule: Rule, stay, plan) -> bool:
    return rule.covers(stay.space_class)


def _week_start(day: date, starts_on: str) -> date:
    """The first day of the local week `day` falls in, for a plan's chosen start."""
    offset = (day.weekday() - DAYS_OF_WEEK.index(starts_on)) % DAYS_IN_A_WEEK
    return day - timedelta(days=offset)


def weeks_of(rule: Rule, stay, plan) -> list[tuple[datetime, datetime]]:
    """The stay cut at this cap's week boundaries: one (start, end) for each week
    the car is in for more than zero time, in order. A stay of zero length is in
    one week, as it is in one day.

    The calendar boundaries are local midnights at the start of each week, so a
    week containing a daylight-saving transition is one week rather than 0.99 of
    one -- `daily_max.days_covered`'s reasoning one unit up.
    """
    entry = stay.entry_at.astimezone(UTC)
    exit_at = stay.exit_at.astimezone(UTC)
    if stay.duration_minutes == 0:
        return [(entry, exit_at)]

    cuts = [entry]
    if rule.params["week_boundary"] == "rolling_7d":
        weeks = -(-stay.duration_minutes // (DAYS_IN_A_WEEK * 24 * 60))  # ceil, integer only
        cuts += [entry + timedelta(days=DAYS_IN_A_WEEK * k) for k in range(1, weeks)]
    else:
        local_entry = stay.entry_at.astimezone(plan.timezone).date()
        week = _week_start(local_entry, rule.params["week_starts_on"])
        while True:
            week += timedelta(days=DAYS_IN_A_WEEK)
            # fold=0 is the first instant of the date, even when midnight itself
            # falls in a transition.
            boundary = datetime.combine(week, time(0), tzinfo=plan.timezone)
            boundary = boundary.astimezone(UTC)
            if boundary >= exit_at:
                break
            cuts.append(boundary)
    cuts.append(exit_at)
    return list(zip(cuts, cuts[1:], strict=False))


def weeks_covered(rule: Rule, stay, plan) -> int:
    """How many caps this stay is allowed. Never zero -- any stay touches one week."""
    return len(weeks_of(rule, stay, plan))


def week_ceilings(rule: Rule, stay, plan) -> list[int]:
    """The most each week of the stay may cost: the weekly max, or the daily max
    times the days the car is in that week where the plan caps the day too and
    that is lower."""
    days = [
        r for r in plan.rules_for_stage(CAP)
        if r.type == "daily_max" and daily_max.qualifies(r, stay, plan)
    ]
    ceilings = []
    for start, end in weeks_of(rule, stay, plan):
        ceiling = rule.params["max_minor"]
        for day_rule in days:
            count = daily_max.days_between(day_rule, stay, plan, start, end) if end > start else 1
            ceiling = min(ceiling, day_rule.params["max_minor"] * count)
        ceilings.append(ceiling)
    return ceilings


def apply(rule: Rule, stay, plan, running_total_minor: int) -> list[Line]:
    """Take the excess off, or say the cap was not reached.

    Shown the running total, like every CAP rule, and like every rule it can only
    return a Line -- it cannot set the total. When a daily cap has already run,
    the number this sees is the daily-capped one, and taking the excess off that
    is what leaves the LOWER of the two ceilings standing whichever order they
    ran in.
    """
    weeks = week_ceilings(rule, stay, plan)
    caps = len(weeks)
    ceiling = sum(weeks)
    currency = plan.currency
    span = f"{caps} weeks" if caps != 1 else "the week"
    by_days = ""
    if any(week < rule.params["max_minor"] for week in weeks):
        by_days = (
            f" ({' + '.join(format_minor(week, currency) for week in weeks)}: a week "
            "costs no more than the daily max for the days the car is in it)"
        )

    if running_total_minor <= ceiling:
        return [
            Line(
                code="weekly_max.not_reached",
                rule_id=rule.id,
                text=(
                    f"Weekly max {format_minor(rule.params['max_minor'], currency)} "
                    f"({rule.params['week_boundary']}, {span}) not reached: the charge "
                    f"so far is {format_minor(running_total_minor, currency)}"
                ),
                delta_minor=0,
            )
        ]
    return [
        Line(
            code="weekly_max.applied",
            rule_id=rule.id,
            text=(
                f"Weekly max {format_minor(rule.params['max_minor'], currency)} "
                f"({rule.params['week_boundary']}) applied over {span}: "
                f"{format_minor(running_total_minor, currency)} reduced to "
                f"{format_minor(ceiling, currency)}{by_days}"
            ),
            delta_minor=ceiling - running_total_minor,
        )
    ]


register("weekly_max", CAP, build, apply)
