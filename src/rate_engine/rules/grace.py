"""`grace` -- the free interval, and FREE MEANS FREE.

§8b, Gokhan's own words: *"some garages uses grace period. usually 10 mins but
changes everywhere"* and, on what it means, *"if customer decides to laeve within
that period it is free."*

One field. `minutes`, a positive whole number, stated by the plan with no
default -- **there is no grace unless a plan says there is.** Inventing a free
interval is inventing a pricing decision, and "usually 10" is not a default, it
is an observation about other people's garages.

**ALL-OR-NOTHING, like every other special here.** A stay at or under `minutes`
costs zero. One minute over and the stay prices from ENTRY on the ordinary rate
-- not from minute ten, and not pro-rated. That is the ordinary garage
convention and it is what §8's all-conditions rule says everywhere else.

**AND IT IS TERMINAL, which is the part that needed care.** Free means free: a
graced stay in a VIP space must not pick up the surcharge, and must not pick up
anything at CAP or ADJUST. So this type declares `TERMINAL` at registration and
the ENGINE stops the pipeline after QUALIFY when a terminal rule qualified. The
engine does not know this type's name and must not: an `if rule.type == "grace"`
in the pipeline is the engine holding a pricing decision no plan can see, which
is the defect `day_span` was created to undo.

**Grace beats every other special**, and that too follows from terminality
rather than from a precedence list: a window that also qualified is not applied,
and the breakdown says it was superseded rather than dropping it silently.

**`stay.duration_minutes` rounds UP**, module-wide, so a ten-minute grace covers
600.000 seconds and not 600.001. That is coherent with every other duration
comparison here -- the stated ceiling on an `increment` rule reads the same
rounded value -- and it is stated in docs/CONTRACT.md rather than changed.

**One consequence worth naming**, because it changes a decision published in the
contract: a zero-length stay falls inside any grace window and is free. The
contract's "a stay of zero length pays the first period" now describes a garage
that declares NO grace, and says so.
"""

from __future__ import annotations

from ..breakdown import Line
from ..money import format_minor
from ..stages import QUALIFY
from . import TERMINAL, Rule, common_fields, register

EXTRA = {"minutes"}

APPLIED = "grace.applied"
NOT_APPLIED = "grace.not_applied"


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan

    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
    minutes = raw["minutes"]
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise InvalidPlan(
            f"{where}.minutes must be a positive whole number of minutes. A grace of "
            "zero is not a grace period, it is the absence of one -- which a plan "
            "states by carrying no grace rule at all."
        )
    return Rule(
        id=rule_id, type="grace", stage=QUALIFY, space_classes=space_classes,
        params={"minutes": minutes},
    )


def qualifies(rule: Rule, stay, plan) -> bool:
    return rule.covers(stay.space_class) and stay.duration_minutes <= rule.params["minutes"]


def apply(rule: Rule, stay, plan) -> list[Line]:
    """Free, or one line at zero saying by how much the stay missed it.

    The not-applied line matters more here than almost anywhere: "I was only
    gone a moment" is the counter argument, and a breakdown that says the stay
    was fourteen minutes against a ten-minute grace settles it in one sentence.
    """
    minutes = stay.duration_minutes
    allowed = rule.params["minutes"]
    if minutes > allowed:
        return [
            Line(
                code=NOT_APPLIED,
                rule_id=rule.id,
                text=(
                    f"Grace period {allowed} min NOT applied: the stay was {minutes} "
                    f"min, which is {minutes - allowed} over. Grace is all-or-nothing, "
                    "so the stay prices from entry on the ordinary rate"
                ),
                delta_minor=0,
            )
        ]
    return [
        Line(
            code=APPLIED,
            rule_id=rule.id,
            text=(
                f"Grace period {allowed} min: the stay was {minutes} min, so there is "
                f"no charge -- {format_minor(0, plan.currency)}, and nothing further "
                "is added"
            ),
            delta_minor=0,
        )
    ]


register("grace", QUALIFY, build, apply, traits=(TERMINAL,))
