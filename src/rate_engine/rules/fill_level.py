"""`fill_level` -- when the garage is at least X% full, the time costs Y% more.

His rule, 2026-10-13: occupancy-based pricing is wanted, and "all the cars inside
are old price". So the figure this rule reads is how full the garage was **at the
moment the car came in** -- `Stay.occupancy_at_entry_bp`, set by the caller when
the stay opened -- and nothing about a stay's price changes after entry. "Full"
is every car inside against every switched-on space (10-14: "all cars"); the
engine does not count anything, it reads the figure it is handed.

**It runs at ADJUST**, the stage stages.py has always described as the place for
occupancy-driven multipliers, and **it raises the charge for the TIME**: the
running total when SURCHARGE began, after whichever base priced the stay and after
the caps (`ON_THE_TIME_CHARGE`). Not the surcharge and not another adjustment --
"the time-based charge is Y% more" is the owner's sentence, and a VIP surcharge
is not time. When another ADJUST rule also qualifies the plan states the order in
`adjust_order`, as for any two adjustments: a discount taken after the increase
is a different fee from one taken before.

`threshold_bp` and the stay's figure are basis points of full: 80% is 8000. The
rule qualifies AT the threshold and above. A stay with no figure, in a class this
rule covers, never reaches the applier: `find_gaps` refuses it by name
(`NEEDS_OCCUPANCY`). Below the threshold the rule SPEAKS -- "why was I not
charged the busy rate" and "why was I" are the same question -- and a class the
rule does not cover stays silent, as every rule outside QUALIFY does.
"""

from __future__ import annotations

from ..breakdown import Line
from ..percent import percent_of_minor, percent_text, was_rounded, whole_bp
from ..stages import ADJUST
from . import (
    NEEDS_OCCUPANCY,
    ON_THE_TIME_CHARGE,
    ONE_PER_STAY,
    SPEAKS_UNQUALIFIED,
    Rule,
    common_fields,
    register,
)

EXTRA = {"threshold_bp", "percent_bp", "rounding"}

#: Which way a fraction of a minor unit goes -- the set an `adjust` effect may
#: state, for the same reason: this is an adjustment of the fee.
ROUNDINGS: tuple[str, ...] = ("up", "down")

#: 100% full. A figure or a threshold above it describes no garage.
FULL_BP = 10_000

#: The most the time may be raised by: 100%, double. The Lab offers 5% to 50%.
MAX_INCREASE_BP = 10_000

APPLIED = "fill_level.applied"
NOT_APPLIED = "fill_level.not_applied"


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan

    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
    rounding = raw["rounding"]
    if rounding not in ROUNDINGS:
        raise InvalidPlan(
            f"{where}.rounding is {rounding!r}; expected one of {', '.join(ROUNDINGS)}. "
            "There is no default: a percentage of a fee lands on a fraction of a cent, "
            "and who keeps it is the owner's to say."
        )
    params = {
        "threshold_bp": whole_bp(raw["threshold_bp"], f"{where}.threshold_bp", 0, FULL_BP),
        "percent_bp": whole_bp(raw["percent_bp"], f"{where}.percent_bp", 1, MAX_INCREASE_BP),
        "rounding": rounding,
    }
    return Rule(
        id=rule_id, type="fill_level", stage=ADJUST,
        space_classes=space_classes, params=params,
    )


def qualifies(rule: Rule, stay, plan) -> bool:
    figure = stay.occupancy_at_entry_bp
    return (
        rule.covers(stay.space_class)
        and figure is not None
        and figure >= rule.params["threshold_bp"]
    )


def apply(
    rule: Rule, stay, plan, running_total_minor: int | None = None,
    time_charge_minor: int | None = None,
) -> list[Line]:
    from ..money import format_minor
    from ..plan import InvalidPlan

    figure = stay.occupancy_at_entry_bp
    if figure is None or time_charge_minor is None:
        raise InvalidPlan(
            f"rule {rule.id!r} (fill_level) was applied without "
            + ("the stay's occupancy at entry" if figure is None else "the time-based charge")
            + ". The engine refuses such a stay before pricing it; reaching here is a "
            "wiring fault in the caller, not a plan that is wrong."
        )
    threshold = rule.params["threshold_bp"]
    full = f"Garage was {percent_text(figure)} full at entry"
    # `qualifies` is THE comparison. The applier asks it rather than comparing
    # again: a second copy of "at or above the threshold" is a second answer the
    # day one of them is edited, and the fail-controls found exactly that here.
    if not qualifies(rule, stay, plan):
        return [
            Line(
                code=NOT_APPLIED,
                rule_id=rule.id,
                text=(
                    f"{full} (below {percent_text(threshold)}): time-based charge not raised"
                ),
                delta_minor=0,
            )
        ]
    percent_bp = rule.params["percent_bp"]
    added = percent_of_minor(time_charge_minor, percent_bp, rule.params["rounding"])
    measure = (
        f"+{percent_text(percent_bp)} on {format_minor(time_charge_minor, plan.currency)}"
    )
    if was_rounded(time_charge_minor, percent_bp, added):
        measure += f" (rounded {rule.params['rounding']})"
    return [
        Line(
            code=APPLIED,
            rule_id=rule.id,
            text=(
                f"{full} (at or above {percent_text(threshold)}): time-based charge "
                f"{measure} -- {format_minor(added, plan.currency)} added"
            ),
            delta_minor=added,
        )
    ]


register(
    "fill_level", ADJUST, build, apply,
    traits=(SPEAKS_UNQUALIFIED, ON_THE_TIME_CHARGE, NEEDS_OCCUPANCY, ONE_PER_STAY),
)
