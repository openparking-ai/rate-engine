"""F79 -- a flat price can be charged per 24 hours, and the cheapest way still wins.

Gokhan, 2026-11-07, on a flat 24-hour price used on a longer stay: **"cheapest win"**.
So a flat special marked `charged: "per_24_hours"` is charged once for every 24 hours of
the stay, and it is a candidate beside the regular rate: the customer pays the lower.

**A started 24 hours counts as a whole one -- Claude's choice, not Gokhan's.** Real
time, `exit_at - entry_at`: 24 h 0 min is one block, 24 h and one second is two.

Worked example (examples, not a real rate): hourly is 8.00 the first hour and 4.00
each hour after; the flat price is 20.00 per 24 hours.

    stay        regular rate   flat x blocks     BEFORE (flat only for <= 24 h)   NOW
    2 h             12.00      1 x 20 = 20.00        12.00                        12.00
    5 h             28.00      1 x 20 = 20.00        20.00                        20.00
    24 h            96.00      1 x 20 = 20.00        20.00                        20.00
    30 h           124.00      2 x 20 = 40.00       124.00                        40.00
    49 h           200.00      3 x 20 = 60.00       200.00                        60.00

`scripts/fail_controls.py` charges the flat once however long the stay, counts only
whole 24 hours, rounds the stay up before counting, and drops the regular rate as a
candidate, and requires this file to go red each time.
"""

from __future__ import annotations

import pytest

from _real_options import HOURLY, TUESDAY_8AM, fee, flat, plan, quote, texts
from rate_engine.contract import run_quote

HOUR = 60


def _per_day(price: int, **limits):
    return flat("day-flat", price, day_span="any_span", exit_by="23:59", charged="per_24_hours",
                **limits)


PLAN = plan(HOURLY, _per_day(2000))

#: The same flat as it was: one 24-hour price for a stay of at most 24 hours.
BEFORE = plan(HOURLY, flat("day-flat", 2000, day_span="any_span", stay_at_most_minutes=24 * HOUR))


@pytest.mark.guarantee("F79")
@pytest.mark.parametrize("hours,expected", [(2, 1200), (5, 2000), (24, 2000), (30, 4000),
                                            (49, 6000)])
def test_the_worked_example(hours, expected):
    assert fee(PLAN, TUESDAY_8AM, hours * HOUR) == expected


@pytest.mark.guarantee("F79")
def test_before_a_longer_stay_dropped_to_the_regular_rate():
    """The same stays on the plan that has only the 24-hour flat: 30 h is 124.00."""
    assert fee(BEFORE, TUESDAY_8AM, 30 * HOUR) == 12400
    assert fee(BEFORE, TUESDAY_8AM, 49 * HOUR) == 20000
    assert fee(BEFORE, TUESDAY_8AM, 24 * HOUR) == 2000


@pytest.mark.guarantee("F79")
def test_a_started_24_hours_counts_as_a_whole_one_in_real_time():
    assert fee(PLAN, TUESDAY_8AM, 24 * HOUR) == 2000
    assert fee(PLAN, TUESDAY_8AM, 24 * HOUR, seconds=1) == 4000   # 24 h 1 s: two blocks
    assert fee(PLAN, TUESDAY_8AM, 48 * HOUR) == 4000
    assert fee(PLAN, TUESDAY_8AM, 48 * HOUR, seconds=1) == 6000


@pytest.mark.guarantee("F79")
def test_a_clock_change_does_not_change_a_block():
    """Sat 07 Mar 12:00 EST to Sun 08 Mar 13:00 EDT is 24 real hours (25 on the wall
    clock): one block. Sun 08 Mar 14:00 EDT is 25 real hours: two."""
    def at(exit_at):
        status, body = run_quote({
            "plans": [PLAN], "entry_at": "2026-03-07T12:00:00-05:00", "exit_at": exit_at,
            "space_class": "standard", "currency": "USD",
        })
        assert status == 200, body
        return body["fee_minor"]

    assert at("2026-03-08T13:00:00-04:00") == 2000
    assert at("2026-03-08T14:00:00-04:00") == 4000


@pytest.mark.guarantee("F79")
def test_the_regular_rate_wins_when_it_is_cheaper_at_any_length():
    """A 200.00 flat per 24 h: 30 h is 2 x 200 = 400.00, the hour costs 124.00."""
    dear = plan(HOURLY, _per_day(20000))
    assert fee(dear, TUESDAY_8AM, 30 * HOUR) == 12400
    assert fee(dear, TUESDAY_8AM, 2 * HOUR) == 1200


@pytest.mark.guarantee("F79")
def test_the_breakdown_shows_the_blocks():
    said = " ".join(texts(PLAN, TUESDAY_8AM, 30 * HOUR))
    assert "for each started 24 hours, 2 x 20.00 USD = 40.00 USD" in said


@pytest.mark.guarantee("F79")
def test_the_other_conditions_still_hold():
    """A per-24-hours flat is still a window: a minimum stay it needs is needed."""
    needs_four = plan(HOURLY, _per_day(2000, stay_at_least_minutes=240))
    assert fee(needs_four, TUESDAY_8AM, 2 * HOUR) == 1200      # under the minimum
    assert fee(needs_four, TUESDAY_8AM, 6 * HOUR) == 2000


@pytest.mark.guarantee("F79")
def test_it_must_be_a_stated_way():
    bad = plan(HOURLY, flat("day-flat", 2000, day_span="any_span", charged="yes"))
    status, body = quote(bad, TUESDAY_8AM, 60)
    assert status != 200
    assert "charged" in str(body) and "per_24_hours" in str(body)


@pytest.mark.guarantee("F79")
def test_a_flat_that_does_not_say_it_is_one_price_for_the_stay():
    assert fee(plan(HOURLY, flat("f", 2000, day_span="any_span")), TUESDAY_8AM, 30 * HOUR) == 2000
