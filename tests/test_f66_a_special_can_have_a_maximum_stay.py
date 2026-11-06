"""F66 -- a special can have a maximum stay.

The real listings: *"early bird, up to 10 hours"* (NYC Upper East Side and Midtown
West). Gokhan, 2026-11-07: **"plain readings are good."** So a special with
`stay_at_most_minutes` applies only if the REAL stay is at most that many minutes.
A longer stay is not charged the special for the hours it covers and the regular
rate for the rest: **the regular rate prices the whole stay, nothing split**, and
the breakdown says the special did not apply because the stay was longer than its
maximum. Real minutes, not rounded ones: 10 h 0 min 30 s is over a ten-hour maximum.

Cheapest still wins, from both sides: a special the stay qualifies for that costs
more than the regular rate is not charged.

The prices are examples. `scripts/fail_controls.py` ignores the maximum, rounds the
stay up before comparing, reads "at most" as "less than", and charges the special
for the covered part of a longer stay, and requires this file to go red each time.
"""

from __future__ import annotations

import pytest

from _real_options import HOURLY, TUESDAY_8AM, fee, flat, plan, texts

TEN_HOURS = 600
#: Hourly is 8.00 + 4.00 an hour: 10 h is 44.00, 11 h is 48.00. A 30.00 early bird
#: with a ten-hour maximum is cheaper than the hour up to ten hours, and not after.
EARLY_BIRD = flat("early-bird", 3000, day_span="same_day", stay_at_most_minutes=TEN_HOURS)
PLAN = plan(HOURLY, EARLY_BIRD)


@pytest.mark.guarantee("F66")
def test_a_stay_of_at_most_the_maximum_gets_the_special():
    assert fee(PLAN, TUESDAY_8AM, 600) == 3000
    assert fee(PLAN, TUESDAY_8AM, 480) == 3000   # 8 h by the hour is 36.00


@pytest.mark.guarantee("F66")
def test_a_longer_stay_is_priced_whole_by_the_regular_rate_nothing_split():
    """601 minutes is 11 hours by the hour: 8.00 + 10 x 4.00 = 48.00. Not 30.00 for
    the first ten hours and 4.00 for the last."""
    assert fee(PLAN, TUESDAY_8AM, 601) == 4800
    said = " ".join(texts(PLAN, TUESDAY_8AM, 601))
    assert "early-bird NOT applied" in said
    assert "the stay is 601 min and this rule covers a stay of at most 600 min" in said
    assert "so the stay prices on the time-based rate" in said


@pytest.mark.guarantee("F66")
def test_the_stay_is_measured_in_real_minutes_not_rounded_ones():
    """10 h 0 min 30 s rounds UP to 601 minutes elsewhere; here it is simply over
    ten hours. 9 h 59 min 59 s is under it, though it also rounds up to 600."""
    assert fee(PLAN, TUESDAY_8AM, 600, seconds=30) == 4800
    assert fee(PLAN, TUESDAY_8AM, 599, seconds=59) == 3000
    assert "600 min 30 s" in " ".join(texts(PLAN, TUESDAY_8AM, 600, seconds=30))


@pytest.mark.guarantee("F66")
def test_the_cheapest_price_still_wins_over_a_special_that_qualifies():
    """A 60.00 special with a ten-hour maximum, on a stay inside it: the hour is
    44.00 for ten hours, so the customer pays 44.00."""
    dear = plan(HOURLY, flat("early-bird", 6000, day_span="same_day",
                             stay_at_most_minutes=TEN_HOURS))
    assert fee(dear, TUESDAY_8AM, 600) == 4400


@pytest.mark.guarantee("F66")
def test_a_minimum_and_a_maximum_together_are_a_window_of_lengths():
    """Three to six hours for 20.00. By the hour 3 h is 16.00, 4 h 20.00, 5 h 24.00,
    6 h 28.00, 7 h 32.00."""
    band = plan(HOURLY, flat("mid", 2000, stay_at_least_minutes=180, stay_at_most_minutes=360))
    assert fee(band, TUESDAY_8AM, 179) == 1600   # under the minimum: the hour
    assert fee(band, TUESDAY_8AM, 300) == 2000   # inside, and cheaper than 24.00
    assert fee(band, TUESDAY_8AM, 360) == 2000   # on the maximum: inside
    assert fee(band, TUESDAY_8AM, 361) == 3200   # over it: the hour, whole
