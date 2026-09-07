"""`space_surcharge` -- base plus a fixed amount for a space class.

§8's consequence, and it is the reason this rule type exists in A1 at all: **the
module prices a SPACE, not a garage.** A VIP area and a reserved spot are the
same mechanism -- a class of space that costs the base plus a stated amount --
and so is the nested-area pricing a later round will need. Getting the space
identifier onto the contract from day one is most of that work.

It runs AFTER the cap, deliberately. A surcharge applied before the cap would be
capped away, so the customer would pay the same for a VIP space as for a standard
one on any stay long enough to hit the maximum -- which is not what an operator
who charges extra for VIP means. See stages.py: the order is load-bearing.

A stay in a space class this rule does not cover produces NO line. That is the
one place in this module where a non-qualifying rule stays silent, and it is
deliberate: a standard-space receipt listing every VIP tier the garage does not
charge for is noise, not clarity. A rule that could have applied to THIS space
and did not is a different thing and does emit a line.
"""

from __future__ import annotations

from ..breakdown import Line
from ..money import as_non_negative_minor, format_minor
from ..stages import SURCHARGE
from . import Rule, common_fields, register

EXTRA = {"surcharge_minor"}


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
    params = {
        "surcharge_minor": as_non_negative_minor(
            raw["surcharge_minor"], f"{where}.surcharge_minor"
        )
    }
    return Rule(
        id=rule_id, type="space_surcharge", stage=SURCHARGE,
        space_classes=space_classes, params=params,
    )


def qualifies(rule: Rule, stay, plan) -> bool:
    return rule.covers(stay.space_class)


def apply(rule: Rule, stay, plan) -> list[Line]:
    amount = rule.params["surcharge_minor"]
    return [
        Line(
            code="space_surcharge.applied",
            rule_id=rule.id,
            text=(
                f"Space class {stay.space_class!r}: "
                f"{format_minor(amount, plan.currency)} on top of the base"
            ),
            delta_minor=amount,
        )
    ]


register("space_surcharge", SURCHARGE, build, apply)
