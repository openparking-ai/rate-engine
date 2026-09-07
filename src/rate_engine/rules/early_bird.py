"""`early_bird` -- a special rate, and the one that carries the all-or-nothing rule.

§8, from Gokhan: "Early bird: they need to have entry by and exit by hours. Early
bird will apply only if it meets that criteria."

**ALL CONDITIONS OR NOTHING.** The stay must satisfy EVERY condition -- entry at
or before `enter_by`, exit at or before `exit_by`, both in the plan's local time.
Miss one by a minute and the rate does not apply AT ALL: no pro-rating, no
partial credit, no cheaper-of-the-two. The stay prices on the time-based rate as
though the special did not exist. An early bird missed by an hour is a full
time-based day, and that is the intended commercial behaviour, not a rough edge.

This is a QUALIFY rule: when it qualifies it REPLACES the ACCUMULATE stage rather
than adding to it, because it is a base, not a discount. When it does not
qualify it still emits a line -- delta zero -- naming which condition failed and
by how much. That line is the most valuable one in the breakdown: it is the
answer to the question an operator gets asked at the counter.

Both conditions are evaluated in the PLAN's timezone, on the local wall clock,
because "exit by 5 pm" is a wall-clock idea. See plan.py on why that zone is
required and why a naive timestamp is refused.
"""

from __future__ import annotations

from ..breakdown import Line
from ..money import as_non_negative_minor, format_minor
from ..stages import QUALIFY
from ..wallclock import local_minute, parse_limit
from . import Rule, common_fields, register

EXTRA = {"enter_by", "exit_by", "price_minor"}


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
    params = {
        "enter_by": parse_limit(raw, "enter_by", where),
        "exit_by": parse_limit(raw, "exit_by", where),
        "price_minor": as_non_negative_minor(raw["price_minor"], f"{where}.price_minor"),
    }
    return Rule(
        id=rule_id, type="early_bird", stage=QUALIFY, space_classes=space_classes,
        params=params,
    )


def _failures(rule: Rule, stay, plan) -> list[str]:
    """Every condition this stay fails, in plain English. Empty means it qualifies."""
    # TRUNCATED TO THE MINUTE, and the limit is refused if it is finer -- see
    # wallclock.py. Compared at full precision, an entry at 09:00:00.001 failed a
    # 09:00 limit and the line below rendered "entry 09:00 is after the 09:00
    # entry limit": a sentence contradicting itself, deciding $18 on a microsecond.
    entry_local = local_minute(stay.entry_at, plan.timezone)
    exit_local = local_minute(stay.exit_at, plan.timezone)
    failed: list[str] = []
    if entry_local.time() > rule.params["enter_by"]:
        failed.append(
            f"entry {entry_local:%H:%M} is after the "
            f"{rule.params['enter_by']:%H:%M} entry limit"
        )
    if exit_local.date() != entry_local.date():
        failed.append(
            f"exit {exit_local:%H:%M} on {exit_local:%a %d %b} is not the same local day "
            f"as entry ({entry_local:%a %d %b})"
        )
    elif exit_local.time() > rule.params["exit_by"]:
        failed.append(
            f"exit {exit_local:%H:%M} is after the {rule.params['exit_by']:%H:%M} limit"
        )
    return failed


def qualifies(rule: Rule, stay, plan) -> bool:
    return rule.covers(stay.space_class) and not _failures(rule, stay, plan)


def apply(rule: Rule, stay, plan) -> list[Line]:
    """Qualified: one line at the flat price. Not qualified: one line at zero, saying why.

    Note that the not-qualified branch is not an error path and not an omission.
    A breakdown that mentions a special only when it applies cannot answer "why
    am I not getting the early bird rate", which is the question this module was
    asked to make answerable.
    """
    failed = _failures(rule, stay, plan)
    if failed:
        return [
            Line(
                code="early_bird.not_applied",
                rule_id=rule.id,
                text=(
                    f"Early bird NOT applied: {'; '.join(failed)}. All of its conditions "
                    "must hold, so the stay prices on the time-based rate"
                ),
                delta_minor=0,
            )
        ]
    return [
        Line(
            code="early_bird.applied",
            rule_id=rule.id,
            text=(
                f"Early bird {format_minor(rule.params['price_minor'], plan.currency)} "
                f"(entered by {rule.params['enter_by']:%H:%M}, exited by "
                f"{rule.params['exit_by']:%H:%M}) -- replaces the time-based charge"
            ),
            delta_minor=rule.params["price_minor"],
        )
    ]


register("early_bird", QUALIFY, build, apply)
