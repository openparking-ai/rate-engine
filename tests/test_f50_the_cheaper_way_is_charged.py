"""F50 -- the driver pays the cheaper of the special and the time-based rate.

**Before U7g fix 1 a special that qualified REPLACED the time-based charge, even
when it cost more.** The gate's walk found it: a weekday car in at 08:00 and out
at 10:30 qualifies for an early bird at 9.00, and was charged 9.00, while the same
stay by the hour is 7.00. The owner's rule, 2026-10-11: "always cheaper goes
first"; asked on 2026-10-12 about exactly this stay, he answered "read your
question". Chat's reading, told to him: the driver always pays the cheapest way
the stay can be priced.

So under `cheapest_wins` the stay is priced through the WHOLE pipeline both ways
-- with the special, and by the time-based rate alone, caps and adjustments
included -- and charged the lower. A tie keeps the special. The breakdown says
which way was used and what the other would have charged.

**The fixture straddles the comparison on purpose.** One stay where the hourly
rate is cheaper (08:00 -> 10:30: 3.00 + 2 x 2.00 = 7.00 against 9.00) and one
where the special is (05:00 -> 18:00: 3.00 + 12 x 2.00 = 27.00 against 9.00). A
test holding only one of them passes one of the two plants.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import stay
from rate_engine.contract import run_quote
from rate_engine.engine import SPECIAL_USED, TIME_BASED_USED, quote
from rate_engine.plan import load_plan

EARLY_BIRD = 900
#: Tuesday 2026-03-03, New York.
IN_0800_OUT_1030 = stay("2026-03-03T08:00:00-05:00", 150)
IN_0500_OUT_1800 = stay("2026-03-03T05:00:00-05:00", 780)

PLAN = {
    "plan_version": "early-bird-2026",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}},
    "adjust_order": None,
    "rules": [
        {"id": "early-bird", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Early bird",
         "applies_on": {"kind": "days_of_week", "days": ["mon", "tue", "wed", "thu", "fri"]},
         "enter_from": "05:00", "enter_by": "09:00", "exit_by": "18:00",
         "day_span": "same_day", "effect": {"kind": "flat", "price_minor": EARLY_BIRD}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 300, "repeat_period_minutes": 60,
         "repeat_period_minor": 200, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


def _plan(**changes) -> dict:
    document = copy.deepcopy(PLAN)
    document.update(changes)
    return document


def _with_rule(document: dict, rule: dict) -> dict:
    document = copy.deepcopy(document)
    document["rules"].append(rule)
    return document


def _quote(document: dict, at):
    return quote([load_plan(copy.deepcopy(document))], at)


def _codes(result) -> list[str]:
    return [line.code for line in result.breakdown.lines]


def _compared(result):
    lines = [ln for ln in result.breakdown.lines if ln.code in (SPECIAL_USED, TIME_BASED_USED)]
    assert len(lines) == 1, _codes(result)
    return lines[0]


def test_the_fixture_puts_a_stay_on_each_side_of_the_comparison():
    """The control on the fixture. Under `stated_order` the special replaces, as
    it always did, so these are the special's prices; the hourly ones are worked
    by hand: 3.00 + 2 x 2.00 and 3.00 + 12 x 2.00."""
    replaces = _plan(resolution={
        "QUALIFY": {"mode": "stated_order", "order": ["early-bird"]},
        "ACCUMULATE": {"mode": "cheapest_wins"},
    })
    assert _quote(replaces, IN_0800_OUT_1030).fee_minor == EARLY_BIRD
    assert _quote(replaces, IN_0500_OUT_1800).fee_minor == EARLY_BIRD
    by_the_hour = _plan(rules=[r for r in PLAN["rules"] if r["id"] == "hourly"])
    assert _quote(by_the_hour, IN_0800_OUT_1030).fee_minor == 700
    assert _quote(by_the_hour, IN_0500_OUT_1800).fee_minor == 2700


@pytest.mark.guarantee("F50")
def test_the_hourly_rate_is_charged_where_it_is_LESS_and_the_breakdown_names_both():
    result = _quote(PLAN, IN_0800_OUT_1030)
    assert result.fee_minor == 700
    assert "time_window.applied" not in _codes(result), "the dearer special was applied"
    assert "increment.first_period" in _codes(result)
    line = _compared(result)
    assert line.code == TIME_BASED_USED
    assert line.rule_id == "early-bird"
    assert line.compared_minor == EARLY_BIRD
    assert line.delta_minor == 0
    assert "Early bird 9.00 USD not used" in line.text, line.text
    assert "7.00 USD is less" in line.text, line.text


@pytest.mark.guarantee("F50")
def test_the_special_is_charged_where_IT_is_less_and_says_what_the_hour_would_be():
    result = _quote(PLAN, IN_0500_OUT_1800)
    assert result.fee_minor == EARLY_BIRD
    assert "time_window.applied" in _codes(result)
    assert "increment.first_period" not in _codes(result)
    line = _compared(result)
    assert line.code == SPECIAL_USED
    assert line.compared_minor == 2700
    assert "Early bird 9.00 USD used" in line.text and "27.00 USD" in line.text, line.text


@pytest.mark.guarantee("F50")
def test_a_daily_most_cheaper_than_both_is_what_the_driver_pays():
    """Caps are inside the comparison: both ways reach the 6.00 most a day."""
    document = _with_rule(PLAN, {
        "id": "day", "type": "daily_max", "stage": "CAP", "space_classes": ["standard"],
        "max_minor": 600, "day_boundary": "calendar_day",
    })
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == 600
    assert "daily_max.applied" in _codes(result)
    assert _compared(result).compared_minor == 600


@pytest.mark.guarantee("F50")
def test_the_whole_pipeline_is_compared_not_the_bases_alone():
    """The other way is priced to the end, cap included. With a 5.00 most a day
    the hourly way is 7.00 capped to 5.00, and that 5.00 -- not the raw 7.00 a
    comparison of bases would report -- is what the line says it would charge."""
    document = _with_rule(PLAN, {
        "id": "day", "type": "daily_max", "stage": "CAP", "space_classes": ["standard"],
        "max_minor": 500, "day_boundary": "calendar_day",
    })
    document["rules"][0]["effect"]["price_minor"] = 450
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == 450
    line = _compared(result)
    assert line.code == SPECIAL_USED and line.compared_minor == 500


@pytest.mark.guarantee("F50")
def test_adjustments_run_on_both_ways():
    """A 10 % discount applies to whichever way is charged, and the comparison is
    made after it: 7.00 - 0.70 = 6.30 against 9.00 - 0.90 = 8.10."""
    document = _with_rule(PLAN, {
        "id": "members", "type": "time_window", "stage": "ADJUST",
        "space_classes": ["standard"], "label": "Members",
        "applies_on": {"kind": "days_of_week",
                       "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
        "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59", "day_span": "any_span",
        "effect": {"kind": "adjust", "direction": "discount",
                   "amount": {"kind": "percent", "percent_bp": 1000}, "rounding": "down"},
    })
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == 630
    line = _compared(result)
    assert line.code == TIME_BASED_USED and line.compared_minor == 810


@pytest.mark.guarantee("F50")
def test_a_tie_keeps_the_special():
    document = copy.deepcopy(PLAN)
    document["rules"][0]["effect"]["price_minor"] = 700
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == 700
    assert "time_window.applied" in _codes(result)
    line = _compared(result)
    assert line.code == SPECIAL_USED and line.compared_minor == 700
    assert "would be 7.00 USD too" in line.text, line.text


@pytest.mark.guarantee("F50")
def test_stated_order_still_lets_the_special_replace():
    document = _plan(resolution={
        "QUALIFY": {"mode": "stated_order", "order": ["early-bird"]},
        "ACCUMULATE": {"mode": "cheapest_wins"},
    })
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == EARLY_BIRD
    assert SPECIAL_USED not in _codes(result) and TIME_BASED_USED not in _codes(result)


@pytest.mark.guarantee("F50")
def test_grace_still_beats_everything():
    document = _with_rule(PLAN, {
        "id": "grace", "type": "grace", "stage": "QUALIFY", "space_classes": ["standard"],
        "minutes": 15,
    })
    result = _quote(document, stay("2026-03-03T08:00:00-05:00", 10))
    assert result.fee_minor == 0
    assert SPECIAL_USED not in _codes(result) and TIME_BASED_USED not in _codes(result)


@pytest.mark.guarantee("F50")
def test_a_stay_the_hourly_rate_cannot_price_is_priced_by_the_special():
    """The time-based rate stops at 2 hours; the 13-hour early bird stay has no
    other way to be priced, and the line says so rather than naming a number."""
    document = copy.deepcopy(PLAN)
    document["rules"][1]["max_duration_minutes"] = 120
    result = _quote(document, IN_0500_OUT_1800)
    assert result.fee_minor == EARLY_BIRD
    line = _compared(result)
    assert line.code == SPECIAL_USED and line.compared_minor is None
    assert "cannot price this stay" in line.text


@pytest.mark.guarantee("F50")
def test_the_compared_amount_reaches_the_caller_and_only_on_its_line():
    status, body = run_quote({
        "plans": [copy.deepcopy(PLAN)],
        "entry_at": "2026-03-03T08:00:00-05:00",
        "exit_at": "2026-03-03T10:30:00-05:00",
        "space_class": "standard",
        "currency": "USD",
    })
    assert status == 200, body
    assert body["fee_minor"] == 700
    carrying = [ln for ln in body["breakdown"] if "compared_minor" in ln]
    pairs = [(ln["code"], ln["compared_minor"]) for ln in carrying]
    assert pairs == [(TIME_BASED_USED, EARLY_BIRD)]
    assert sum(ln["delta_minor"] for ln in body["breakdown"]) == 700
