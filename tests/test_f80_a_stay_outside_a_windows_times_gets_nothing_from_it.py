"""F80 -- a stay that does not match a window's entry and exit times gets nothing from it.

Gokhan, 2026-11-07, on a daily max stated inside a time window ("Max $25, Mon-Fri
6am-6pm"): **"it mean that rate wouldn't apply. That's why they put the entry and
exit times. If it doesn't match it doesn't apply."** So a stay that enters or leaves
outside the window gets no benefit from that rate and pays whatever else applies: the
regular rate, whole. This already worked; this file pins it.

The 25.00 is an example. `scripts/fail_controls.py` lets the max apply to a stay that
leaves after the window closes, and requires this file to go red.
"""

from __future__ import annotations

import pytest

from _real_options import HOURLY, WEEKDAYS, fee, flat, plan, texts

#: "Max $25, Mon-Fri 6am-6pm": a 25.00 price for a stay that enters from 06:00, leaves
#: by 18:00, the same day.
MAX_25 = flat("max-25", 2500, days=WEEKDAYS, enter_from="06:00", enter_by="18:00",
              exit_by="18:00", day_span="same_day")
PLAN = plan(HOURLY, MAX_25)
TUESDAY = "2026-03-03T{}:00-05:00"


@pytest.mark.guarantee("F80")
def test_a_stay_inside_the_window_gets_the_max():
    assert fee(PLAN, TUESDAY.format("07:00"), 600) == 2500      # 10 h is 44.00 by the hour


@pytest.mark.guarantee("F80")
def test_a_stay_that_leaves_after_the_window_closes_is_not_covered():
    """In at 17:00, out at 20:00: three hours, 8 + 2 x 4 = 16.00 by the hour. Not 25.00,
    and not the max for the part before 18:00."""
    assert fee(PLAN, TUESDAY.format("17:00"), 180) == 1600
    said = " ".join(texts(PLAN, TUESDAY.format("17:00"), 180))
    assert "max-25 NOT applied" in said
    assert "so the stay prices on the time-based rate" in said


@pytest.mark.guarantee("F80")
def test_the_max_is_not_a_cap_on_a_stay_it_does_not_cover():
    """In at 17:00, out at 04:00 the next day: eleven hours, 8 + 10 x 4 = 48.00, not
    capped at 25.00 because 17:00 is inside the window."""
    assert fee(PLAN, TUESDAY.format("17:00"), 660) == 4800


@pytest.mark.guarantee("F80")
def test_a_stay_that_enters_before_the_window_opens_is_not_covered():
    assert fee(PLAN, TUESDAY.format("05:00"), 600) == 4400


@pytest.mark.guarantee("F80")
def test_a_stay_on_a_day_the_window_does_not_name_is_not_covered():
    assert fee(PLAN, "2026-03-07T09:00:00-05:00", 600) == 4400   # Saturday
