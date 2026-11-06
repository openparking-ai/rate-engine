"""F67 -- the patterns real garages list are all expressible, each as the listing words it.

Gokhan, 2026-11-07, after real listings from New York, Chicago and Los Angeles were
collected: **"We need to accomodate all those options exactly the way they
describe."** Four patterns were not confirmed to work, so each is proven here rather
than assumed. All four already worked once a special could state a stay limit
(F65, F66), so this file builds nothing: it pins what the listings say, in the
listings' own shape, and the plan beside it (`tests/plans/example_listing_patterns.json`)
is the same patterns in one plan.

* **Banded prices** -- "up to 3 hours = X, up to 6 hours = Y". Each band is a flat
  special with a maximum stay; the cheapest price wins, so a stay pays the lowest
  band that covers it or the hour, whichever is less.
* **A max that applies only inside a weekday window** -- "Max $25, Mon-Fri
  6am-6pm". A flat special for stays that ENTER in the window and leave the same
  day: with the cheapest price winning, the stay pays the hour or the max, whichever
  is less. What this does NOT say is what a window max means for a stay that leaves
  the window or runs to the next day: that stay is not covered and pays the regular
  rate (the last test pins that); whether the listing means something else is the
  owner's to say, and is listed as a question rather than decided here.
* **A flat "24 hours" price** -- "$50/24 h" -- a flat special for a stay of at most
  24 hours; a longer stay is priced whole by the regular rate.
* **An evening window past midnight as ONE rule** -- "in after 5pm, out by 6am" is a
  single `next_day` window with an `exit_by` before its `enter_from`, not two rules.

Every price here is an EXAMPLE chosen for easy arithmetic, never a real garage's.
`scripts/fail_controls.py` takes out the maximum stay and the next-day span and
requires this file to go red each time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _real_options import WEEKDAYS, fee, flat, plan, texts
from rate_engine.plan import load_plan
from rate_engine.validator import validate_plan

#: 12.00 the first hour, 8.00 each hour after: 1 h 12, 2 h 20, 3 h 28, 4 h 36,
#: 5 h 44, 6 h 52, 7 h 60. Dear enough that a band can beat it.
DEAR_HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 60,
    "first_period_minor": 1200, "repeat_period_minutes": 60,
    "repeat_period_minor": 800, "rounding": "ceil", "max_duration_minutes": None,
}
TUESDAY_8AM = "2026-03-03T08:00:00-05:00"
FRIDAY_6PM = "2026-03-06T18:00:00-05:00"
SATURDAY_8AM = "2026-03-07T08:00:00-05:00"


# --- banded prices ---------------------------------------------------------

BANDS = plan(
    DEAR_HOURLY,
    flat("up-to-3-hours", 2400, stay_at_most_minutes=180),
    flat("up-to-6-hours", 3800, stay_at_most_minutes=360),
)


@pytest.mark.guarantee("F67")
def test_a_band_is_charged_where_it_is_the_cheapest_price():
    assert fee(BANDS, TUESDAY_8AM, 60) == 1200    # the hour is cheaper than a band
    assert fee(BANDS, TUESDAY_8AM, 180) == 2400   # 3 h by the hour is 28.00
    assert fee(BANDS, TUESDAY_8AM, 240) == 3600   # 4 h by the hour, 36.00, beats 38.00
    assert fee(BANDS, TUESDAY_8AM, 300) == 3800   # 5 h by the hour is 44.00
    assert fee(BANDS, TUESDAY_8AM, 360) == 3800


@pytest.mark.guarantee("F67")
def test_a_stay_past_the_last_band_is_priced_whole_by_the_regular_rate():
    assert fee(BANDS, TUESDAY_8AM, 361) == 6000   # 7 h: 12.00 + 6 x 8.00
    said = " ".join(texts(BANDS, TUESDAY_8AM, 361))
    assert "up-to-6-hours NOT applied" in said and "at most 360 min" in said


# --- a max that applies only inside a weekday window -----------------------

WINDOW_MAX = plan(
    {**DEAR_HOURLY, "first_period_minor": 800, "repeat_period_minor": 400},
    flat("max-25", 2500, days=WEEKDAYS, enter_from="06:00", enter_by="18:00",
         exit_by="23:59", day_span="same_day"),
)


@pytest.mark.guarantee("F67")
def test_a_weekday_window_max_holds_the_fee_for_a_stay_inside_it():
    assert fee(WINDOW_MAX, TUESDAY_8AM, 360) == 2500   # 6 h by the hour is 28.00
    assert fee(WINDOW_MAX, TUESDAY_8AM, 120) == 1200   # under the max: the hour


@pytest.mark.guarantee("F67")
def test_the_window_max_does_not_apply_outside_its_days_or_hours():
    assert fee(WINDOW_MAX, SATURDAY_8AM, 360) == 2800                    # not a weekday
    assert fee(WINDOW_MAX, "2026-03-03T05:00:00-05:00", 360) == 2800    # before 06:00
    assert fee(WINDOW_MAX, "2026-03-03T18:01:00-05:00", 300) == 2400    # after 18:00, 5 h


@pytest.mark.guarantee("F67")
def test_a_stay_that_leaves_the_window_day_is_not_covered_and_pays_the_regular_rate():
    """The limit this pattern does not cross, pinned so it cannot change unseen:
    in at 08:00, out at 01:00 the next day (17 h), is by the hour, not 25.00."""
    assert fee(WINDOW_MAX, TUESDAY_8AM, 17 * 60) == 7200   # 8.00 + 16 x 4.00 = 72.00


# --- a flat "24 hours" price -----------------------------------------------

DAY_PRICE = plan(
    {**DEAR_HOURLY, "first_period_minor": 800, "repeat_period_minor": 400},
    flat("24-hours", 5000, stay_at_most_minutes=24 * 60),
)


@pytest.mark.guarantee("F67")
def test_a_flat_24_hour_price_covers_a_stay_of_up_to_24_hours_from_any_entry():
    for entry in (TUESDAY_8AM, FRIDAY_6PM, "2026-03-03T23:30:00-05:00"):
        assert fee(DAY_PRICE, entry, 24 * 60) == 5000   # 24 h by the hour is 100.00
    assert fee(DAY_PRICE, TUESDAY_8AM, 4 * 60) == 2000   # an hourly stay is cheaper


@pytest.mark.guarantee("F67")
def test_a_stay_past_24_hours_is_priced_whole_by_the_regular_rate():
    assert fee(DAY_PRICE, TUESDAY_8AM, 24 * 60 + 1) == 10400   # 25 h: 8.00 + 24 x 4.00


# --- one window running past midnight, written as ONE rule -----------------

EVENING = plan(
    {**DEAR_HOURLY, "first_period_minor": 800, "repeat_period_minor": 400},
    flat("evening", 1000, enter_from="17:00", enter_by="23:59", exit_by="06:00",
         day_span="next_day"),
)


@pytest.mark.guarantee("F67")
def test_one_evening_rule_covers_a_stay_that_crosses_midnight():
    assert len([r for r in EVENING["rules"] if r["type"] == "time_window"]) == 1
    assert fee(EVENING, FRIDAY_6PM, 4 * 60) == 1000          # out at 22:00, same night
    assert fee(EVENING, "2026-03-06T22:00:00-05:00", 4 * 60) == 1000   # out at 02:00
    assert fee(EVENING, FRIDAY_6PM, 12 * 60 - 1) == 1000     # out at 05:59 next day


@pytest.mark.guarantee("F67")
def test_the_evening_rule_stops_at_its_limit_and_its_start():
    assert fee(EVENING, FRIDAY_6PM, 12 * 60 + 1) == 5600     # out at 06:01, 13 h: 8.00 + 12 x 4.00
    assert fee(EVENING, "2026-03-06T16:59:00-05:00", 600) == 4400   # in before 17:00


# --- the example plan ------------------------------------------------------

EXAMPLE = Path(__file__).parent / "plans" / "example_listing_patterns.json"


@pytest.mark.guarantee("F67")
def test_the_example_plan_loads_validates_clean_and_prices_each_pattern():
    document = json.loads(EXAMPLE.read_text())
    assert validate_plan(load_plan(document)) == []
    assert {r["id"] for r in document["rules"]} >= {
        "up-to-3-hours", "up-to-6-hours", "24-hours", "weekday-max", "evening",
        "early-bird",
    }
    assert fee(document, TUESDAY_8AM, 180) == 2400          # a band
    assert fee(document, FRIDAY_6PM, 4 * 60) == 1000        # the evening rule
    assert fee(document, "2026-03-03T07:00:00-05:00", 540) == 1800   # early bird, 9 h
