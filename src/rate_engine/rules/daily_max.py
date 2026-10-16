"""`daily_max` -- a cap, and the rule that forced the timezone model to be real.

A cap is not additive: it replaces a bigger number with a smaller one. In the
ledger it is a NEGATIVE line saying how much it took off, which both keeps the
fee equal to the sum of its lines and shows the operator the size of the
discount -- the number a plain "daily max applied" would have hidden.

**`day_boundary` is required, with no default, and it is the interesting field.**
"Daily max 30" does not say what a day is, and the two honest answers price a
two-day stay differently:

* `calendar_day` -- a day is a local calendar date. A stay from Friday 22:00 to
  Saturday 02:00 is in two of them. Across a DST transition a calendar day is 23
  or 25 hours, and that is correct: a day is what the local clock says it is.
* `rolling_24h` -- a day is 24 hours from ENTRY. The same stay is four hours long
  and is in one. DST does not move it, because 24 hours is 24 hours whatever the
  clock did.

§8 raises exactly this ("what happens at midnight on a two-day stay") as one of
the things a rate sign does not tell you. So the engine does not decide it. A
plan that does not state `day_boundary` does not load.

**Each day is capped on its own (F59).** Gokhan, 2026-10-16: the daily max is
per calendar day -- split the stay at the garage's local midnight and cap each
day by itself. The stay is cut at the start of each of its days, the charge for
the time is split by the day it was charged in, and each day pays at most the
max. Monday 09:00 to Tuesday 00:15 at $8 the first hour and $4 an hour after,
$30 a day: Monday's fifteen hours are $64 and pay $30, Tuesday's fifteen minutes
are the stay's sixteenth hour and pay $4. $34, where a cap of $30 times the days
touched allowed $60. A rolling day is cut at each 24 hours from entry and capped
the same way.

How the charge is split is the base's to say, not this file's: the engine hands
a cap `charged_by` (the `told_the_base` trait), what the base charges for the
stay's first so many minutes. A time-based rate charges a period on the day the
period starts, and does not start again at midnight. A flat special is one
price for the whole stay with nothing to split, so it is capped as it always
was: at the max times the days the car is in.

**A day the car is in for no time is not a day it touched.** An exit at exactly
local midnight ends on the date before, so Monday 09:00 to Tuesday 00:00 is one
calendar day, not two. A rolling window already counted that way: a stay of
exactly 24 hours is one window.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

from ..breakdown import Line
from ..money import as_non_negative_minor, format_minor
from ..stages import CAP
from . import TOLD_THE_BASE, Rule, common_fields, register

DAY_BOUNDARIES: tuple[str, ...] = ("calendar_day", "rolling_24h")

EXTRA = {"max_minor", "day_boundary"}

ONE_DAY = timedelta(days=1)


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan

    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
    boundary = raw["day_boundary"]
    if boundary not in DAY_BOUNDARIES:
        raise InvalidPlan(
            f"{where}.day_boundary is {boundary!r}; expected one of "
            f"{', '.join(DAY_BOUNDARIES)}. There is no default: a cap of 30 a day "
            "prices a Friday-night-to-Saturday-morning stay at 30 or at 60 depending "
            "on the answer, and that is the owner's decision."
        )
    params = {
        "max_minor": as_non_negative_minor(raw["max_minor"], f"{where}.max_minor"),
        "day_boundary": boundary,
    }
    return Rule(
        id=rule_id, type="daily_max", stage=CAP, space_classes=space_classes, params=params
    )


def qualifies(rule: Rule, stay, plan) -> bool:
    return rule.covers(stay.space_class)


def _day_starts(rule: Rule, stay, plan):
    """The start of every day after the entry's own, in order, without end.

    A calendar day starts at local midnight: fold=0 is the first instant of the
    date, even when midnight itself falls in a transition, so a 23- or 25-hour
    day is one day rather than 0.96 or 1.04 of one. A rolling day starts every
    24 hours from entry.
    """
    if rule.params["day_boundary"] == "rolling_24h":
        start = stay.entry_at.astimezone(UTC)
        while True:
            start += ONE_DAY
            yield start
    day = stay.entry_at.astimezone(plan.timezone).date()
    while True:
        day += ONE_DAY
        yield datetime.combine(day, time(0), tzinfo=plan.timezone).astimezone(UTC)


def days_of(rule: Rule, stay, plan) -> list[tuple[datetime, datetime]]:
    """The stay cut at this cap's day boundaries: one (start, end) for each day
    the car is in for more than zero time, in order, as UTC instants. A stay of
    zero length is in one day.

    THE one place a day is found. The cap's own count, the days it caps one by
    one, and the days `weekly_max` reads inside each week all come from here, so
    they cannot disagree about where a day starts.
    """
    entry = stay.entry_at.astimezone(UTC)
    exit_at = stay.exit_at.astimezone(UTC)
    cuts = [entry]
    if exit_at > entry:
        for start in _day_starts(rule, stay, plan):
            if start >= exit_at:
                break
            cuts.append(start)
    cuts.append(exit_at)
    return list(zip(cuts, cuts[1:], strict=False))


def days_covered(rule: Rule, stay, plan) -> int:
    """How many days the stay is in. Never zero -- any stay touches one day."""
    return len(days_of(rule, stay, plan))


def pieces(rule: Rule, stay, plan, start: datetime, end: datetime, days=None):
    """This cap's days cut down to the part of the stay from `start` to `end`.

    One (start, end) for each day the car is in for more than zero time inside
    that part. `weekly_max` asks this of each week a stay is cut into: a
    calendar day sits inside a calendar week, and a rolling day that runs past a
    week's end is split there, so each week holds only its own part of it. A
    stay of zero length is one piece, as it is one day.

    `days` is `days_of` for this rule and stay, when the caller already has it.
    A caller asking week after week passes it, so a long stay is cut into days
    once rather than once a week, and each week finds its first day by halving.
    """
    if end <= start:
        return [(start, end)]
    days = days_of(rule, stay, plan) if days is None else days
    out = []
    index = bisect_right(days, start, key=lambda day: day[1])  # the first day ending after start
    while index < len(days):
        day_start, day_end = days[index]
        if not (day_start < end and day_end > start):
            break
        out.append((max(day_start, start), min(day_end, end)))
        index += 1
    return out


def _minutes_into(stay, instant: datetime) -> int:
    """How many minutes of the stay have passed at `instant`, counted the way the
    stay's own length is: a part-minute is a whole minute. The stay's own
    `duration_minutes`, asked of the stay as if it ended there."""
    return replace(stay, exit_at=instant).duration_minutes


def charge_in(stay, charged_by, start: datetime, end: datetime) -> int:
    """What the base charged for the part of the stay from `start` to `end`.

    What it charges for a stay ending at `end`, less what it charges for one
    ending at `start` -- nothing, when `start` is the entry: the first period is
    owed from the first instant, which is why a stay of zero length pays it (F24).
    The parts of a stay therefore add up to its charge exactly.
    """
    before = 0 if start == stay.entry_at else charged_by(_minutes_into(stay, start))
    return charged_by(_minutes_into(stay, end)) - before


def capped_days(
    rule: Rule, stay, plan, charged_by, start=None, end=None, days=None
) -> list[int]:
    """What each of this cap's days pays, from `start` to `end` (the whole stay
    by default): the charge in that day, or the max where the charge is more.
    `days` as for `pieces`."""
    start = stay.entry_at.astimezone(UTC) if start is None else start
    end = stay.exit_at.astimezone(UTC) if end is None else end
    most = rule.params["max_minor"]
    return [
        min(most, charge_in(stay, charged_by, day_start, day_end))
        for day_start, day_end in pieces(rule, stay, plan, start, end, days)
    ]


def amounts_text(amounts: list[int], currency: str) -> str:
    """'3 x 30.00 USD + 4.00 USD': the amounts in order, a run of equal ones said once."""
    runs: list[list[int]] = []
    for amount in amounts:
        if runs and runs[-1][0] == amount:
            runs[-1][1] += 1
        else:
            runs.append([amount, 1])
    return " + ".join(
        format_minor(amount, currency) if count == 1
        else f"{count} x {format_minor(amount, currency)}"
        for amount, count in runs
    )


def apply(rule: Rule, stay, plan, running_total_minor: int, *, charged_by) -> list[Line]:
    """Take the excess off, or say the cap was not reached.

    This is one of the rule types shown the running total, because a cap is
    defined in terms of it. It still cannot SET the total -- it returns a line
    like everything else, and the engine adds it. The read is one-way.

    The most the stay may cost is worked out from the BASE (`charged_by`), never
    from the running total, so a second cap that ran first cannot change it: the
    caps leave the lowest ceiling standing in either order (F33). `charged_by`
    has no default. A cap applied without being told how the time was charged is
    a wiring fault, and a default would hide it by capping the stay some other
    way.
    """
    days = days_of(rule, stay, plan)
    caps = len(days)
    most = rule.params["max_minor"]
    currency = plan.currency
    calendar = rule.params["day_boundary"] == "calendar_day"
    if charged_by is None:
        # One price for the whole stay: no day it can be split by.
        amounts = None
        ceiling = most * caps
    else:
        amounts = capped_days(rule, stay, plan, charged_by, days=days)
        ceiling = sum(amounts)
    span = f"{caps} days" if caps != 1 else ("the day" if calendar else "24 hours")

    if running_total_minor <= ceiling:
        return [
            Line(
                code="daily_max.not_reached",
                rule_id=rule.id,
                text=(
                    f"Daily max {format_minor(most, currency)} "
                    f"({rule.params['day_boundary']}, {span}) not reached: the charge so "
                    f"far is {format_minor(running_total_minor, currency)}"
                ),
                delta_minor=0,
            )
        ]
    by_day = ""
    if amounts is not None and caps > 1 and any(amount < most for amount in amounts):
        unit = "day" if calendar else "24-hour window"
        by_day = f" ({amounts_text(amounts, currency)}: each {unit} is capped on its own)"
    return [
        Line(
            code="daily_max.applied",
            rule_id=rule.id,
            text=(
                f"Daily max {format_minor(most, currency)} "
                f"({rule.params['day_boundary']}) applied over {span}: "
                f"{format_minor(running_total_minor, currency)} reduced to "
                f"{format_minor(ceiling, currency)}{by_day}"
            ),
            delta_minor=ceiling - running_total_minor,
        )
    ]


register("daily_max", CAP, build, apply, traits=(TOLD_THE_BASE,))
