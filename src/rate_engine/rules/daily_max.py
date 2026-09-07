"""`daily_max` -- a cap, and the rule that forced the timezone model to be real.

A cap is not additive: it replaces a bigger number with a smaller one. In the
ledger it is a NEGATIVE line saying how much it took off, which both keeps the
fee equal to the sum of its lines and shows the operator the size of the
discount -- the number a plain "daily max applied" would have hidden.

**`day_boundary` is required, with no default, and it is the interesting field.**
"Daily max 30" does not say what a day is, and the two honest answers price a
two-day stay differently:

* `calendar_day` -- the cap is per local calendar date the stay touches. A stay
  from Friday 22:00 to Saturday 02:00 touches two dates and is allowed two caps.
  Across a DST transition a calendar day is 23 or 25 hours, and that is correct:
  a day is what the local clock says it is.
* `rolling_24h` -- the cap is per 24 hours from ENTRY. The same stay is four
  hours long and gets one cap. DST does not move it, because 24 hours is 24
  hours whatever the clock did.

§8 raises exactly this ("what happens at midnight on a two-day stay") as one of
the things a rate sign does not tell you. So the engine does not decide it. A
plan that does not state `day_boundary` does not load.
"""

from __future__ import annotations

from ..breakdown import Line
from ..money import as_non_negative_minor, format_minor
from ..stages import CAP
from . import Rule, common_fields, register

DAY_BOUNDARIES: tuple[str, ...] = ("calendar_day", "rolling_24h")

EXTRA = {"max_minor", "day_boundary"}


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


def days_covered(rule: Rule, stay, plan) -> int:
    """How many caps this stay is allowed. Never zero -- any stay touches one day."""
    if rule.params["day_boundary"] == "rolling_24h":
        minutes = stay.duration_minutes
        if minutes == 0:
            return 1
        return -(-minutes // (24 * 60))  # ceil, integer only

    entry_local = stay.entry_at.astimezone(plan.timezone)
    exit_local = stay.exit_at.astimezone(plan.timezone)
    # Distinct local dates touched. Counted on dates rather than by dividing an
    # elapsed time, which is what makes a 23- or 25-hour DST day come out as one
    # day rather than as 0.96 or 1.04 of one.
    return (exit_local.date() - entry_local.date()).days + 1


def apply(rule: Rule, stay, plan, running_total_minor: int) -> list[Line]:
    """Take the excess off, or say the cap was not reached.

    This is the one rule type that is shown the running total, because a cap is
    defined in terms of it. It still cannot SET the total -- it returns a line
    like everything else, and the engine adds it. The read is one-way.
    """
    caps = days_covered(rule, stay, plan)
    ceiling = rule.params["max_minor"] * caps
    currency = plan.currency
    span = (
        f"{caps} days"
        if caps != 1
        else ("the day" if rule.params["day_boundary"] == "calendar_day" else "24 hours")
    )

    if running_total_minor <= ceiling:
        return [
            Line(
                code="daily_max.not_reached",
                rule_id=rule.id,
                text=(
                    f"Daily max {format_minor(rule.params['max_minor'], currency)} "
                    f"({rule.params['day_boundary']}, {span}) not reached: the charge so "
                    f"far is {format_minor(running_total_minor, currency)}"
                ),
                delta_minor=0,
            )
        ]
    reduction = ceiling - running_total_minor
    return [
        Line(
            code="daily_max.applied",
            rule_id=rule.id,
            text=(
                f"Daily max {format_minor(rule.params['max_minor'], currency)} "
                f"({rule.params['day_boundary']}) applied over {span}: "
                f"{format_minor(running_total_minor, currency)} reduced to "
                f"{format_minor(ceiling, currency)}"
            ),
            delta_minor=reduction,
        )
    ]


register("daily_max", CAP, build, apply)
