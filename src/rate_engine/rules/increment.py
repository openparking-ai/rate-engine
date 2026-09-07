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

#: What a PLAN may state. The loader checks against this.
#: A1 implements exactly one. The field is still required -- see the docstring.
ROUNDING_MODES: tuple[str, ...] = ("ceil",)


def _ceil_periods(remainder: int, period_minutes: int) -> int:
    """Any part of a period is the whole of it. Integer arithmetic only."""
    return -(-remainder // period_minutes)


#: What `apply()` IMPLEMENTS, mode -> the function that counts repeat periods.
#:
#: **This is deliberately a SECOND list, and checking against `ROUNDING_MODES`
#: instead would rebuild the defect it exists to stop.** `apply()` used to
#: hardcode ceil and never read the field at all: setting `rounding` to anything
#: -- `floor`, `nearest`, `banana`, `null` -- produced the identical fee, which
#: nothing noticed because the loader only ever let `ceil` through.
#:
#: That is harmless today and is a wrong fee tomorrow. A2 adds `floor` to
#: `ROUNDING_MODES`; if the applier validated against that same list it would
#: accept `floor` and go on pricing as ceil, silently, on a plan whose document
#: says floor and whose owner believes it. An operator cannot catch that by
#: reading their plan, because their plan is right.
#:
#: So the applier asks what it can actually DO. A mode the loader accepts and
#: this table does not implement is refused, loudly, instead of mispriced.
PERIOD_COUNTERS = {"ceil": _ceil_periods}

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
    from ..plan import InvalidPlan

    p = rule.params
    minutes = stay.duration_minutes
    currency = plan.currency

    # THE FIELD IS CONSULTED, NOT ASSUMED. Unreachable through `load_plan` today
    # -- the loader accepts only `ceil` and `ceil` is implemented -- and that is
    # the point: it is the guard on the round that changes one of those two
    # without the other. It fails loudly rather than returning a fee, because a
    # plan priced under a rule it did not ask for is the failure this module
    # exists to prevent, and a plan that cannot be priced is a refusal here as
    # it is everywhere else.
    rounding = p["rounding"]
    count_periods = PERIOD_COUNTERS.get(rounding)
    if count_periods is None:
        raise InvalidPlan(
            f"rule {rule.id!r} states rounding {rounding!r}, which this version "
            f"does not implement (it implements: {', '.join(sorted(PERIOD_COUNTERS))}). "
            "Refused rather than priced under a different rule: the fee would have "
            "been right for `ceil` and wrong for the plan, on a document that reads "
            "correctly to whoever wrote it."
        )

    first_len = p["first_period_minutes"]
    repeat_len = p["repeat_period_minutes"]

    # The rounding mode governs the REPEAT periods. The first period is not a
    # rounding decision: a stay shorter than one first period is one first
    # period under every mode, which is why a zero `first_period_minor` is the
    # only way to express a free interval.
    #
    # AND THAT INCLUDES A STAY OF ZERO MINUTES, which is a DECISION rather than a
    # consequence nobody looked at. The first period covers [0, first_len], so a
    # car that enters and leaves at the same instant pays first_period_minor --
    # the same as one that stayed a minute. It diverges from the platform's older
    # fee code, which returns zero for that stay, and the divergence is a later
    # round's to reconcile. Published in docs/CONTRACT.md because an integrator
    # cannot learn it from the arithmetic, and pinned by
    # tests/test_f24_a_zero_length_stay_is_priced.py so it cannot change silently.
    # (A negative stay is refused in make_stay -- a different case, and a caller
    # bug rather than a price.)
    if minutes <= first_len:
        repeats = 0
    else:
        repeats = count_periods(minutes - first_len, repeat_len)

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
