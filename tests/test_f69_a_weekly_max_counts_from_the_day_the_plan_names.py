"""F69 -- a weekly max counts a week from a day the plan names, and only that.

Gokhan, 2026-11-07: **"day: wednesday . e.g. sunday to sunday."** A week is a
calendar week that starts on the day the garage picks. A week counted as seven days
from entry is gone: a plan that states it does not load, and the refusal says to
write `calendar_week` and a starting day. `week_starts_on` is therefore always a day
name, where it used to be null for a rolling week.

Seven days and an hour from a Wednesday noon is two weeks if the garage's week
starts on Sunday or on Monday, and the same stay moved to span a Wednesday boundary is
one. So the day the plan names decides the fee, which is the point.

`scripts/fail_controls.py` lets the removed choice load again, ignores the starting
day, and requires this file to go red each time.
"""

from __future__ import annotations

import copy

import pytest

from _real_options import HOURLY, plan, quote
from rate_engine.plan import InvalidPlan, load_plan

#: A cap of 100.00 a week and nothing else, so the week is the only thing counted.
WEEKLY = {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
          "space_classes": ["standard"], "max_minor": 10000,
          "week_boundary": "calendar_week", "week_starts_on": "wed"}

#: Wednesday 2026-04-08 at noon, for six days: it ends Tuesday 2026-04-14 at noon.
WEDNESDAY_NOON = "2026-04-08T12:00:00-04:00"
SIX_DAYS = 6 * 24 * 60
EIGHT_DAYS = 8 * 24 * 60


def _fee(starts_on: str, entry: str, minutes: int) -> int:
    document = plan(HOURLY, {**WEEKLY, "week_starts_on": starts_on})
    status, body = quote(document, entry, minutes)
    assert status == 200, body
    return body["fee_minor"]


@pytest.mark.guarantee("F69")
def test_the_day_the_plan_names_decides_how_many_weeks_a_stay_is_in():
    """Six days from Wednesday noon: 8.00 + 143 x 4.00 = 580.00 by the hour.

    A week starting Wednesday holds all six days: one cap, 100.00.
    A week starting Monday splits at Monday 00:00 (Mon 2026-04-13): Wed noon to
    Monday is 4.5 days, 108 hours = 436.00 -> 100.00, and Monday 00:00 to Tuesday noon
    is 36 hours = 144.00 -> 100.00. Two weeks: 200.00.
    """
    assert _fee("wed", WEDNESDAY_NOON, SIX_DAYS) == 10000
    assert _fee("mon", WEDNESDAY_NOON, SIX_DAYS) == 20000


@pytest.mark.guarantee("F69")
def test_sunday_to_sunday_and_wednesday_to_wednesday_are_both_stated_the_same_way():
    # 8 days from Wednesday noon ends Thursday noon: Wednesday weeks cut at the
    # next Wednesday 00:00, so two weeks; Sunday weeks cut at Sunday and Sunday.
    assert _fee("wed", WEDNESDAY_NOON, EIGHT_DAYS) == 20000
    assert _fee("sun", WEDNESDAY_NOON, EIGHT_DAYS) == 20000
    # And a stay of exactly the week from a Wednesday midnight is one week for a
    # Wednesday garage, and two for a Sunday one.
    midnight = "2026-04-08T00:00:00-04:00"
    assert _fee("wed", midnight, 7 * 24 * 60) == 10000
    assert _fee("sun", midnight, 7 * 24 * 60) == 20000


@pytest.mark.guarantee("F69")
def test_the_line_says_which_weeks():
    document = plan(HOURLY, WEEKLY)
    status, body = quote(document, WEDNESDAY_NOON, EIGHT_DAYS)
    text = next(line["text"] for line in body["breakdown"] if line["rule_id"] == "cap-weekly")
    assert "(calendar_week) applied over 2 weeks" in text


@pytest.mark.guarantee("F69")
def test_a_rolling_seven_day_week_does_not_load_and_the_refusal_says_what_to_write():
    document = plan(HOURLY, {**WEEKLY, "week_boundary": "rolling_7d", "week_starts_on": None})
    with pytest.raises(InvalidPlan) as caught:
        load_plan(document)
    message = str(caught.value)
    assert "rules[1].week_boundary" in message
    assert "rolling_7d" in message and "does not have" in message
    assert '"calendar_week"' in message and "week_starts_on" in message


@pytest.mark.guarantee("F69")
@pytest.mark.parametrize("starts_on", [None, "monday", "", "everyday"])
def test_a_week_with_no_day_the_plan_names_does_not_load(starts_on):
    document = plan(HOURLY, {**WEEKLY, "week_starts_on": starts_on})
    with pytest.raises(InvalidPlan, match="needs the day the garage's week starts on"):
        load_plan(document)


@pytest.mark.guarantee("F69")
def test_any_other_week_boundary_does_not_load_either():
    document = plan(HOURLY, copy.deepcopy({**WEEKLY, "week_boundary": "fortnight"}))
    with pytest.raises(InvalidPlan, match="expected 'calendar_week'"):
        load_plan(document)
