"""F68 -- a daily max counts the local calendar day, and only that.

Gokhan, 2026-11-07: **"calendar day not 24 hrs."** A daily max used to say, in the
plan, whether a day was the local calendar day or 24 hours counted from entry. The
second is gone. So a stay from 18:00 to 18:00 the next day, which is exactly 24
hours, is in TWO calendar days and each is capped on its own; and a day the clock
stretches to 25 hours is still one day with one cap.

A plan that states the removed choice does not load, and the refusal names the
field and says what to write. The field `day_boundary` is still stated, with no
default, so a plan says in its own words what a day is.

`scripts/fail_controls.py` lets the removed choice load again, and cuts the day
every 24 hours from entry, and requires this file to go red each time.
"""

from __future__ import annotations

import copy

import pytest

from _real_options import HOURLY, plan, quote
from rate_engine.plan import InvalidPlan, load_plan

DAILY = {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 3000,
         "day_boundary": "calendar_day"}
PLAN = plan(HOURLY, DAILY)

MONDAY_6PM = "2026-04-06T18:00:00-04:00"


def _fee(entry: str, minutes: int) -> int:
    status, body = quote(PLAN, entry, minutes)
    assert status == 200, body
    return body["fee_minor"]


@pytest.mark.guarantee("F68")
def test_24_hours_from_6pm_is_two_calendar_days_each_capped_on_its_own():
    """Monday 18:00 to Tuesday 18:00 by the hour is 8.00 + 23 x 4.00 = 100.00. Monday
    holds the first 6 hours, 28.00; Tuesday holds the other 18, 72.00 -> 30.00. The
    two days pay 28.00 + 30.00 = 58.00. Counted from entry as one 24-hour day it
    was 30.00."""
    assert _fee(MONDAY_6PM, 24 * 60) == 5800


@pytest.mark.guarantee("F68")
def test_a_stay_inside_one_calendar_day_is_capped_once():
    assert _fee("2026-04-06T00:00:00-04:00", 24 * 60) == 3000   # midnight to midnight


@pytest.mark.guarantee("F68")
def test_the_line_says_calendar_day_and_how_many_days():
    status, body = quote(PLAN, MONDAY_6PM, 24 * 60)
    text = next(line["text"] for line in body["breakdown"] if line["rule_id"] == "cap-daily")
    assert "(calendar_day) applied over 2 days" in text
    assert "each day is capped on its own" in text


@pytest.mark.guarantee("F68")
def test_a_day_the_clock_stretches_to_25_hours_is_one_day():
    """2026-11-01 is 25 hours long. 25 hours from its midnight end at 23:59:59 the same
    date, and pay one cap."""
    assert _fee("2026-11-01T00:00:00-04:00", 25 * 60 - 1) == 3000


@pytest.mark.guarantee("F68")
def test_a_rolling_24_hour_day_does_not_load_and_the_refusal_says_what_to_write():
    document = copy.deepcopy(PLAN)
    document["rules"][1]["day_boundary"] = "rolling_24h"
    with pytest.raises(InvalidPlan) as caught:
        load_plan(document)
    message = str(caught.value)
    assert "rules[1].day_boundary" in message
    assert "rolling_24h" in message and "does not have" in message
    assert 'Write "calendar_day"' in message


@pytest.mark.guarantee("F68")
@pytest.mark.parametrize("value", ["weekday", "", None, "calendar_week"])
def test_any_other_day_boundary_does_not_load_either(value):
    document = copy.deepcopy(PLAN)
    document["rules"][1]["day_boundary"] = value
    with pytest.raises(InvalidPlan, match="expected 'calendar_day'"):
        load_plan(document)
