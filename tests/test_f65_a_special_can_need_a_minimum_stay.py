"""F65 -- a special can need a minimum stay.

The real listings: *"early bird, 5-hour minimum"* (Chicago, Midtown NYC). Gokhan,
2026-11-07: **"plain readings are good."** So a special with `stay_at_least_minutes`
applies only if the REAL stay is at least that many minutes. A shorter stay gets the
regular rate, whole, with a line saying the special did not apply and why. The stay
is measured in real minutes, not the rounded ones the periods are counted in: a
stay of 4 h 59 min 30 s is not a five-hour stay.

And the cheapest price still wins (Gokhan, 2026-11-07, "cheapest calculation wins
for the customer"): a special the stay qualifies for that costs MORE than the
regular rate is not charged.

The prices are examples. `scripts/fail_controls.py` ignores the minimum, rounds
the stay up before comparing it, and reads "at least" as "more than", and requires
this file to go red each time.
"""

from __future__ import annotations

import pytest

from _real_options import HOURLY, TUESDAY_8AM, fee, flat, plan, texts
from rate_engine.money import NotMinorUnits
from rate_engine.plan import InvalidPlan, load_plan

FIVE_HOURS = 300
#: Hourly is 8.00 + 4.00 an hour: 5 h is 24.00, 6 h is 28.00. An early bird of 20.00
#: with a five-hour minimum is cheaper from five hours up.
EARLY_BIRD = flat("early-bird", 2000, exit_by="23:59", day_span="same_day",
                  stay_at_least_minutes=FIVE_HOURS)
PLAN = plan(HOURLY, EARLY_BIRD)


@pytest.mark.guarantee("F65")
def test_a_stay_of_at_least_the_minimum_gets_the_special():
    assert fee(PLAN, TUESDAY_8AM, 300) == 2000
    assert fee(PLAN, TUESDAY_8AM, 360) == 2000


@pytest.mark.guarantee("F65")
def test_a_shorter_stay_pays_the_regular_rate_and_the_line_says_why():
    assert fee(PLAN, TUESDAY_8AM, 299) == 2400  # 8.00 + 4 x 4.00
    said = " ".join(texts(PLAN, TUESDAY_8AM, 299))
    assert "early-bird NOT applied" in said
    assert "the stay is 299 min and this rule needs a stay of at least 300 min" in said


@pytest.mark.guarantee("F65")
def test_the_stay_is_measured_in_real_minutes_not_rounded_ones():
    """4 h 59 min 30 s rounds UP to 300 minutes elsewhere in the engine. Here it is
    still short of five hours, and 5 h 0 min 1 s is not."""
    assert fee(PLAN, TUESDAY_8AM, 299, seconds=30) == 2400
    assert fee(PLAN, TUESDAY_8AM, 300, seconds=1) == 2000
    said = " ".join(texts(PLAN, TUESDAY_8AM, 299, seconds=30))
    assert "299 min 30 s" in said


@pytest.mark.guarantee("F65")
def test_the_cheapest_price_still_wins_over_a_special_that_qualifies():
    """A 40.00 special with a minimum, on a stay that meets it: the regular rate is
    24.00 for five hours, so the customer pays that, and the line says so."""
    dear = plan(HOURLY, flat("early-bird", 4000, stay_at_least_minutes=FIVE_HOURS,
                             day_span="same_day"))
    assert fee(dear, TUESDAY_8AM, 300) == 2400
    assert any("early-bird 40.00 USD not used: by the time-based rate 24.00 USD is less" in t
               for t in texts(dear, TUESDAY_8AM, 300))


@pytest.mark.guarantee("F65")
def test_a_plan_with_no_minimum_prices_every_stay_as_before():
    plain = plan(HOURLY, flat("early-bird", 2000, day_span="same_day"))
    assert fee(plain, TUESDAY_8AM, 60) == 800   # the regular rate is cheaper
    assert fee(plain, TUESDAY_8AM, 300) == 2000


@pytest.mark.guarantee("F65")
@pytest.mark.parametrize("bad", [0, -5, "300"])
def test_a_minimum_that_is_not_a_positive_whole_number_does_not_load(bad):
    document = plan(HOURLY, flat("early-bird", 2000, day_span="same_day",
                                 stay_at_least_minutes=bad))
    with pytest.raises(InvalidPlan, match="stay_at_least_minutes"):
        load_plan(document)


@pytest.mark.guarantee("F65")
@pytest.mark.parametrize("bad", [1.5, True])
def test_a_fractional_or_boolean_minimum_does_not_load_either(bad):
    """A float or a bool anywhere in a plan is refused by the walk that covers every
    leaf, before this field is read."""
    document = plan(HOURLY, flat("early-bird", 2000, day_span="same_day",
                                 stay_at_least_minutes=bad))
    with pytest.raises(NotMinorUnits):
        load_plan(document)


@pytest.mark.guarantee("F65")
def test_a_minimum_above_the_maximum_does_not_load_and_names_the_fix():
    document = plan(HOURLY, flat("early-bird", 2000, day_span="same_day",
                                 stay_at_least_minutes=600, stay_at_most_minutes=300))
    with pytest.raises(InvalidPlan, match="could never apply"):
        load_plan(document)


@pytest.mark.guarantee("F65")
def test_the_validator_probes_a_minute_either_side_of_the_minimum():
    from rate_engine.validator import probe_stays

    lengths = {int((s.exit_at - s.entry_at).total_seconds() // 60)
               for s in probe_stays(load_plan(PLAN))}
    assert {FIVE_HOURS - 1, FIVE_HOURS, FIVE_HOURS + 1} <= lengths
