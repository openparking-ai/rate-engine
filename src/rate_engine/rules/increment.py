"""`increment` -- a first period and a repeating period, each with its own length
and its own price.

ONE rule type, not two. "First 20 min then each additional 20 min" and "first
hour then each additional hour" differ only in their numbers, and §8 settled that
they are one rule with different period lengths. The receipt shows both priced
because both are lines.

Three fields here are required with no default, and each one is a pricing
decision somebody has to make rather than a parameter with an obvious value:

* **`rounding`** -- a 61-minute stay on an hourly rate is two hours under `ceil`.
  That is the ordinary garage convention and it is still a decision: it is the
  difference between charging a customer for 59 minutes they did not park. A1
  implements `ceil` only, and REQUIRES the field anyway, so that A2 adding
  `floor` or `nearest` changes no plan that already exists (F7).
* **`max_duration_minutes`** -- may be `null`, but `null` has to be typed. §8's
  own example of a gap is "nothing prices a stay past 24 hours", and that gap is
  only expressible if a rule can state a ceiling. Left implicit, every rule
  silently prices a 30-day stay and the module's headline promise -- it never
  guesses -- would have nothing to catch.
* **`first_period_minor` / `repeat_period_minor`** -- no free interval is implied
  anywhere. If an operator wants the first 15 minutes free they write a first
  period of 15 minutes at 0, visibly, in the plan. There is no grace period in
  this module: inventing a free interval is inventing a pricing decision.

NOTE what this rule does NOT do: it does not look at the clock, at the day of the
week, or at the plan's other rules. It converts a duration into lines.
"""

from __future__ import annotations

from ..breakdown import Line
from ..money import as_non_negative_minor, format_minor
from ..stages import ACCUMULATE
from . import Rule, common_fields, register

#: A1 implements exactly one. The field is still required -- see the docstring.
ROUNDING_MODES: tuple[str, ...] = ("ceil",)

EXTRA = {
    "first_period_minutes",
    "first_period_minor",
    "repeat_period_minutes",
    "repeat_period_minor",
    "rounding",
    "max_duration_minutes",
}


def _positive_int(raw: dict, key: str, where: str) -> int:
    from ..plan import InvalidPlan

    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidPlan(f"{where}.{key} must be a positive whole number of minutes.")
    return value


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan

    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)

    rounding = raw["rounding"]
    if rounding not in ROUNDING_MODES:
        raise InvalidPlan(
            f"{where}.rounding is {rounding!r}; this version implements "
            f"{', '.join(ROUNDING_MODES)}. The field is required even with one option so "
            "that adding another later cannot change what this plan already answers."
        )

    max_duration = raw["max_duration_minutes"]
    if max_duration is not None:
        if isinstance(max_duration, bool) or not isinstance(max_duration, int) or max_duration <= 0:
            raise InvalidPlan(
                f"{where}.max_duration_minutes must be a positive whole number of minutes, "
                "or null. Null has to be typed: a rule with no stated ceiling prices a "
                "thirty-day stay, and that is a decision, not an absence."
            )

    params = {
        "first_period_minutes": _positive_int(raw, "first_period_minutes", where),
        "first_period_minor": as_non_negative_minor(
            raw["first_period_minor"], f"{where}.first_period_minor"
        ),
        "repeat_period_minutes": _positive_int(raw, "repeat_period_minutes", where),
        "repeat_period_minor": as_non_negative_minor(
            raw["repeat_period_minor"], f"{where}.repeat_period_minor"
        ),
        "rounding": rounding,
        "max_duration_minutes": max_duration,
    }
    return Rule(
        id=rule_id, type="increment", stage=ACCUMULATE, space_classes=space_classes,
        params=params,
    )


def qualifies(rule: Rule, stay) -> bool:
    """A stay longer than the stated ceiling is NOT priced by this rule.

    It does not fall back to the ceiling and it does not pro-rate. Nothing else
    in an A1 plan accumulates time, so the stay reaches the engine with no
    ACCUMULATE line and becomes a GAP the owner is asked about -- which is the
    behaviour §8 asked for in as many words.
    """
    if not rule.covers(stay.space_class):
        return False
    ceiling = rule.params["max_duration_minutes"]
    return ceiling is None or stay.duration_minutes <= ceiling


def apply(rule: Rule, stay, plan) -> list[Line]:
    p = rule.params
    minutes = stay.duration_minutes
    currency = plan.currency

    first_len = p["first_period_minutes"]
    repeat_len = p["repeat_period_minutes"]

    # `ceil` on the first period too: any part of it is the whole of it. A stay
    # shorter than one first period is one first period, which is why a zero
    # first_period_minor is the only way to express a free interval.
    if minutes <= first_len:
        repeats = 0
    else:
        remainder = minutes - first_len
        repeats = -(-remainder // repeat_len)  # ceil, integer only

    lines = [
        Line(
            code="increment.first_period",
            rule_id=rule.id,
            text=(
                f"Time-based: first {_period(first_len)} "
                f"{format_minor(p['first_period_minor'], currency)}"
            ),
            delta_minor=p["first_period_minor"],
        )
    ]
    if repeats:
        lines.append(
            Line(
                code="increment.repeat_periods",
                rule_id=rule.id,
                text=(
                    f"Time-based: {repeats} additional "
                    f"{_period(repeat_len, plural=repeats != 1)} at "
                    f"{format_minor(p['repeat_period_minor'], currency)} = "
                    f"{format_minor(repeats * p['repeat_period_minor'], currency)}"
                ),
                delta_minor=repeats * p["repeat_period_minor"],
            )
        )
    return lines


def _period(minutes: int, plural: bool = False) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        if hours == 1:
            return "hours" if plural else "hour"
        return f"{hours} hours"
    return f"{minutes} min"


register("increment", ACCUMULATE, build, apply)
