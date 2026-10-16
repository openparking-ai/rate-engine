"""F56 -- a cap counts only the days and weeks the car is in, and a week costs no
more than the daily caps of the days in it.

Two defects, one plan. $8 the first hour, $4 an hour after, $30 a day, $100 a
week, New York:

* **A period the car is in for zero minutes added a cap.** `days_covered`
  counted the exit's own local date, so Monday 09:00 to Tuesday 00:00 was
  allowed two daily caps for no time at all on Tuesday: 60.00 instead of 30.00.
  A calendar week did the same at its start: Monday 00:00 to the next Monday
  00:00 was two weeks. A rolling window already counted this way -- exactly 24
  hours is one window -- and that is pinned here so it stays.
* **A week was capped at the weekly max times the weeks touched.** Seven days
  and an hour paid the weekly max twice, 200.00, although the hour's week
  holds one hour, which the daily cap limits to 30.00. Each week now costs at
  most the daily max times the days the car is in it: 100.00 + 30.00.

Both are wrong whatever a daily max is taken to mean -- each day capped on its
own, or the max times the days and part-days of the stay. Which of those the
plan means is not settled here, and these figures are the ones that hold under
either.

`scripts/fail_controls.py` puts back the exit's own date, the week start at the
exit, a rolling day counted past the exit, and the week capped by the weekly max
alone, and requires this file to go red each time.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.contract import run_quote
from rate_engine.engine import make_stay
from rate_engine.plan import load_plan, parse_instant
from rate_engine.rules import RULE_APPLIERS
from rate_engine.rules.daily_max import days_covered
from rate_engine.rules.weekly_max import weeks_covered
from rate_engine.stages import CAP

HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 60,
    "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}


def _plan(day_boundary: str | None, week_boundary: str | None) -> dict:
    rules = [copy.deepcopy(HOURLY)]
    if day_boundary is not None:
        rules.append(
            {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
             "space_classes": ["standard"], "max_minor": 3000,
             "day_boundary": day_boundary}
        )
    if week_boundary is not None:
        rules.append(
            {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
             "space_classes": ["standard"], "max_minor": 10000,
             "week_boundary": week_boundary,
             "week_starts_on": "mon" if week_boundary == "calendar_week" else None}
        )
    return {
        "plan_version": "caps-2026-04",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                       "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": None,
        "rules": rules,
        "decisions": [],
    }


def _quote(plan: dict, entry: str, exit_: str) -> dict:
    status, body = run_quote(
        {"plans": [copy.deepcopy(plan)], "entry_at": entry, "exit_at": exit_,
         "space_class": "standard", "currency": "USD"}
    )
    assert status == 200, body
    return body


def _fee(plan: dict, entry: str, exit_: str) -> int:
    return _quote(plan, entry, exit_)["fee_minor"]


# 2026-04-06 is a Monday, and no daylight-saving change falls near it.
MONDAY = "2026-04-06T09:00:00-04:00"


@pytest.mark.guarantee("F56")
def test_an_exit_at_midnight_adds_no_calendar_day():
    """15 hours, Monday 09:00 to Tuesday 00:00: 64.00 uncapped, ONE day's cap."""
    plan = _plan("calendar_day", None)
    assert _fee(plan, MONDAY, "2026-04-07T00:00:00-04:00") == 3000
    # One minute into Tuesday is a second day, and a second cap.
    assert _fee(plan, MONDAY, "2026-04-07T00:01:00-04:00") == 6000
    # The day before is untouched by the fix.
    assert _fee(plan, MONDAY, "2026-04-06T23:59:00-04:00") == 3000


@pytest.mark.guarantee("F56")
def test_a_part_minute_past_midnight_is_in_the_new_day():
    """The stay's own convention: a part-minute is a whole minute."""
    plan = load_plan(_plan("calendar_day", None))
    daily = next(r for r in plan.rules if r.id == "cap-daily")
    entry = parse_instant(MONDAY, "entry")
    on_midnight = make_stay(entry, parse_instant("2026-04-07T00:00:00-04:00", "x"), "standard")
    just_after = make_stay(
        entry, parse_instant("2026-04-07T00:00:00.000001-04:00", "x"), "standard"
    )
    assert days_covered(daily, on_midnight, plan) == 1
    assert days_covered(daily, just_after, plan) == 2


@pytest.mark.guarantee("F56")
def test_exactly_24_hours_is_one_rolling_window_and_a_minute_more_is_two():
    plan = _plan("rolling_24h", None)
    assert _fee(plan, MONDAY, "2026-04-07T09:00:00-04:00") == 3000
    assert _fee(plan, MONDAY, "2026-04-07T09:01:00-04:00") == 6000


@pytest.mark.guarantee("F56")
def test_an_exit_at_the_start_of_a_week_adds_no_week():
    """A weekly cap alone, so the count of weeks is the whole ceiling."""
    plan = _plan(None, "calendar_week")
    start = "2026-04-06T00:00:00-04:00"
    assert _fee(plan, start, "2026-04-13T00:00:00-04:00") == 10000
    assert _fee(plan, start, "2026-04-13T00:01:00-04:00") == 20000


@pytest.mark.guarantee("F56")
def test_exactly_seven_days_is_one_rolling_week_and_a_minute_more_is_two():
    plan = _plan(None, "rolling_7d")
    assert _fee(plan, MONDAY, "2026-04-13T09:00:00-04:00") == 10000
    assert _fee(plan, MONDAY, "2026-04-13T09:01:00-04:00") == 20000


@pytest.mark.guarantee("F56")
def test_a_week_with_a_clock_change_ends_at_the_next_local_midnight():
    """2026-03-08 springs forward, so this week is 167 hours. Leaving at the next
    Monday's local midnight is still one calendar week and seven calendar days."""
    plan = load_plan(_plan("calendar_day", "calendar_week"))
    daily = next(r for r in plan.rules if r.id == "cap-daily")
    weekly = next(r for r in plan.rules if r.id == "cap-weekly")
    entry = parse_instant("2026-03-02T00:00:00-05:00", "entry")
    exit_at = parse_instant("2026-03-09T00:00:00-04:00", "exit")
    stay = make_stay(entry, exit_at, "standard")
    assert stay.duration_minutes == 167 * 60, "the fixture must cross the transition"
    assert days_covered(daily, stay, plan) == 7
    assert weeks_covered(weekly, stay, plan) == 1


@pytest.mark.guarantee("F56")
@pytest.mark.parametrize(
    "day_boundary,week_boundary,entry,exit_",
    [
        ("rolling_24h", "rolling_7d", MONDAY, "2026-04-13T10:00:00-04:00"),
        ("calendar_day", "calendar_week",
         "2026-04-06T00:00:00-04:00", "2026-04-13T01:00:00-04:00"),
    ],
)
def test_seven_days_and_an_hour_pay_one_week_and_one_day(
    day_boundary, week_boundary, entry, exit_
):
    """169 hours: 680.00 uncapped, eight days at 30.00 is 240.00, and two weeks
    at 100.00 was 200.00. The second week holds one hour, which costs at most one
    day's cap, so the stay costs 100.00 + 30.00."""
    body = _quote(_plan(day_boundary, week_boundary), entry, exit_)
    assert body["fee_minor"] == 13000
    weekly = next(ln for ln in body["breakdown"] if ln["rule_id"] == "cap-weekly")
    assert weekly["code"] == "weekly_max.applied"
    assert "100.00 USD + 30.00 USD" in weekly["text"], weekly["text"]


@pytest.mark.guarantee("F56")
def test_a_week_counts_the_rolling_days_it_holds_and_no_more():
    """Eight days exactly, rolling: the second week holds one 24-hour window, not
    two, so it is 30.00 and the stay is 130.00."""
    assert _fee(_plan("rolling_24h", "rolling_7d"), MONDAY, "2026-04-14T09:00:00-04:00") == 13000


@pytest.mark.guarantee("F56")
def test_a_full_week_still_pays_the_weekly_max():
    """The control on the item above: a week whose daily caps add up to more
    than the weekly max is capped at the weekly max, so the change is the short
    week and nothing else. Fourteen days: two full weeks."""
    body = _quote(_plan("rolling_24h", "rolling_7d"), MONDAY, "2026-04-20T09:00:00-04:00")
    assert body["fee_minor"] == 20000
    weekly = next(ln for ln in body["breakdown"] if ln["rule_id"] == "cap-weekly")
    assert "+" not in weekly["text"], weekly["text"]


@pytest.mark.guarantee("F56")
def test_without_a_daily_cap_a_short_week_is_the_weekly_max():
    """No daily cap, nothing to bound the short week by: two weeks at 100.00."""
    assert _fee(_plan(None, "rolling_7d"), MONDAY, "2026-04-13T10:00:00-04:00") == 20000


@pytest.mark.guarantee("F56")
def test_the_two_caps_still_compose_in_either_order():
    """F33's property on the stay this file changes: the weekly cap reads the
    daily caps' TERMS, so the total after CAP is the same whichever runs first."""
    plan = load_plan(_plan("rolling_24h", "rolling_7d"))
    entry = parse_instant(MONDAY, "entry")
    stay = make_stay(entry, entry + timedelta(hours=169), "standard")
    caps = list(plan.rules_for_stage(CAP))
    totals = set()
    for order in (caps, list(reversed(caps))):
        running = 68000
        for rule in order:
            for line in RULE_APPLIERS[rule.type](rule, stay, plan, running):
                running += line.delta_minor
        totals.add(running)
    assert totals == {13000}


@pytest.mark.guarantee("F56")
def test_a_zero_length_stay_is_still_one_day_and_one_week():
    """F24: a stay of zero minutes pays the first period, so it is in one day."""
    plan = load_plan(_plan("calendar_day", "calendar_week"))
    daily = next(r for r in plan.rules if r.id == "cap-daily")
    weekly = next(r for r in plan.rules if r.id == "cap-weekly")
    entry = parse_instant("2026-04-13T00:00:00-04:00", "entry")
    stay = make_stay(entry, entry, "standard")
    assert days_covered(daily, stay, plan) == 1
    assert weeks_covered(weekly, stay, plan) == 1
    assert _fee(_plan("calendar_day", "calendar_week"), entry.isoformat(), entry.isoformat()) == 800
