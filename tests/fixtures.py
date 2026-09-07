"""The fixture corpus, and the control that proves it exercises anything.

A FIXTURE IS PART OF THE MEASUREMENT. `vehicle-id`'s presence gate looked like it
worked partly because it was measured against a reference of flat grey with
nothing in it -- not a weak measurement, but not a measurement at all, producing
numbers that read as evidence. The equivalent failure here is a corpus of stays
that all sit on the same side of every threshold: the suite would go green,
`increment`'s repeat branch would never run, and nothing would say so.

So every axis below is READ OUT OF THE PLANS -- the actual constants the rules
branch on -- and `test_fixture_axes.py` asserts the corpus holds a case either
side of each. An axis that cannot reach its threshold is a broken axis, not a
safe threshold.
"""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from pathlib import Path

from rate_engine.engine import Stay, make_stay
from rate_engine.plan import load_plan, parse_instant

PLANS_DIR = Path(__file__).parent / "plans"

#: The plan the worked example in the brief and in docs/CONTRACT.md is priced on.
DOWNTOWN_V2 = json.loads((PLANS_DIR / "downtown_v2.json").read_text())


def downtown_v1() -> dict:
    """The SAME garage, priced cheaper, in force before v2.

    Exists for F3: with only one version the engine cannot demonstrate that it
    chose by entry rather than by exit, because there is nothing to choose.
    """
    plan = copy.deepcopy(DOWNTOWN_V2)
    plan["plan_version"] = "downtown-2026-01"
    plan["effective_from"] = "2026-01-01T00:00:00-05:00"
    for rule in plan["rules"]:
        if rule["id"] == "hourly":
            rule["first_period_minor"] = 500
            rule["repeat_period_minor"] = 250
        if rule["id"] == "cap":
            rule["max_minor"] = 2000
    return plan


def plan_with(**overrides) -> dict:
    """A copy of the reference plan with top-level fields replaced."""
    plan = copy.deepcopy(DOWNTOWN_V2)
    plan.update(overrides)
    return plan


def with_rule_field(rule_id: str, **fields) -> dict:
    plan = copy.deepcopy(DOWNTOWN_V2)
    for rule in plan["rules"]:
        if rule["id"] == rule_id:
            rule.update(fields)
            return plan
    raise KeyError(f"no rule {rule_id!r} in the reference plan")


def without_rule(rule_id: str) -> dict:
    plan = copy.deepcopy(DOWNTOWN_V2)
    plan["rules"] = [r for r in plan["rules"] if r["id"] != rule_id]
    return plan


def loaded(document: dict | None = None):
    return load_plan(document if document is not None else DOWNTOWN_V2)


def stay(entry: str, minutes: int, space_class: str = "standard") -> Stay:
    entry_at = parse_instant(entry, "entry")
    return make_stay(entry_at, entry_at + timedelta(minutes=minutes), space_class)


# --- the corpus ------------------------------------------------------------
#
# Every entry names the axis it exists to put a case on. Nothing here is a round
# number chosen because it looked plausible; each is a threshold the rules read,
# or one minute either side of one.

EARLY = "2026-03-03T08:30:00-05:00"  # Tue, before the 09:00 entry limit
LATE = "2026-03-03T09:14:00-05:00"  # Tue, after it -- the brief's worked example
FRI_NIGHT = "2026-03-06T22:00:00-05:00"  # crosses local midnight into Saturday
DST_SPRING = "2026-03-07T12:00:00-05:00"  # the US spring-forward is 2026-03-08

CORPUS: dict[str, Stay] = {
    # increment: first period, either side of 60 minutes
    "first_period_under": stay(LATE, 59),
    "first_period_exact": stay(LATE, 60),
    "first_period_over": stay(LATE, 61),
    # increment: a stay with many repeat periods (the brief's example)
    "worked_example": stay(LATE, 566),
    # increment: either side of the 1440-minute stated ceiling
    "ceiling_under": stay(LATE, 1439),
    "ceiling_exact": stay(LATE, 1440),
    "ceiling_over": stay(LATE, 1441),
    # early_bird: qualifies, and each condition missed by one minute
    "early_bird_qualifies": stay(EARLY, 240),
    "early_bird_entry_late": stay(LATE, 60),
    "early_bird_exit_late": stay(EARLY, 511),  # 08:30 + 8h31m = 17:01
    "early_bird_exit_on_limit": stay(EARLY, 510),  # 08:30 + 8h30m = 17:00 exactly
    # daily_max: either side of the cap, and across a local midnight
    "cap_not_reached": stay(LATE, 120),
    "cap_reached": stay(LATE, 566),
    "cap_across_midnight": stay(FRI_NIGHT, 300),
    # daily_max: a DST day, which is 23 hours on the local clock
    "dst_day": stay(DST_SPRING, 1440),
    # space_surcharge: both sides of the space-class axis
    "vip_space": stay(LATE, 120, "vip"),
    "standard_space": stay(LATE, 120, "standard"),
    # zero and one minute: a stay is never negative, and a part-minute is a minute
    "zero_length": stay(LATE, 0),
    "one_minute": stay(LATE, 1),
}

#: (axis, threshold, the corpus keys strictly below / at-or-above it). Read by
#: test_fixture_axes.py, which requires both sides of every row to be non-empty.
AXES: tuple[tuple[str, str], ...] = (
    ("increment.first_period_minutes = 60", "first_period"),
    ("increment.max_duration_minutes = 1440", "ceiling"),
    ("early_bird enter_by 09:00 / exit_by 17:00", "early_bird"),
    ("daily_max.max_minor = 3000", "cap"),
    ("space_class in {standard, vip}", "space"),
)
