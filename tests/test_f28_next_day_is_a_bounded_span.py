"""F28 -- `next_day` is BOUNDED, and that is the whole reason it exists.

Gokhan's Friday/Saturday pair: a stay entering Friday 22:00 and leaving Saturday
05:00 is one night and should get the overnight rate. `same_day` refuses it.
`any_span` accepts it -- and accepts the car that left on SUNDAY at 05:00 under
the same flat overnight price, which is the same class of hole `day_span` itself
was created to close: the engine pricing a stay under a rule whose author never
imagined it.

So there is a middle value, and it is bounded at one local day.

**The three spans are compared on ONE stay.** Three scenarios each shown under
one span would prove that three plans price three stays; only the same stay under
all three makes `day_span` an axis, and only an axis can show that the middle
value is genuinely between the other two.

March 2026 dates are chosen away from the US daylight-saving transition on the
8th, so nothing below turns on a 23-hour day.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.contract import run_quote
from rate_engine.plan import parse_instant

OVERNIGHT_PRICE = 1800
FRIDAY_2200 = "2026-03-13T22:00:00-04:00"
#: Fri 22:00 -> Sat 05:00. Seven hours: 800 + 6 x 400.
TO_SATURDAY_MINUTES, TIME_BASED_SATURDAY = 420, 3200
#: Fri 22:00 -> Sun 05:00. Thirty-one hours: 800 + 30 x 400.
TO_SUNDAY_MINUTES, TIME_BASED_SUNDAY = 1860, 12800

PLAN = {
    "plan_version": "overnight-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": {
        "QUALIFY": "cheapest_wins", "ACCUMULATE": "stated_order", "CAP": "stated_order",
        "SURCHARGE": "stated_order", "ADJUST": "stated_order",
    },
    "adjust_order": None,
    "rules": [
        {"id": "overnight", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Overnight rate",
         "applies_on": {"kind": "days_of_week",
                        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
         "enter_from": "18:00", "enter_by": "23:59", "exit_by": "06:00",
         "day_span": "next_day", "effect": {"kind": "flat", "price_minor": OVERNIGHT_PRICE}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


def _fee(day_span: str, minutes: int) -> tuple[int, str]:
    document = copy.deepcopy(PLAN)
    document["rules"][0]["day_span"] = day_span
    entry_at = parse_instant(FRIDAY_2200, "entry")
    status, body = run_quote(
        {
            "plans": [document],
            "entry_at": FRIDAY_2200,
            "exit_at": (entry_at + timedelta(minutes=minutes)).isoformat(),
            "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 200, body
    line = [ln for ln in body["breakdown"] if ln["code"].startswith("time_window")][0]
    return body["fee_minor"], line["text"]


def test_the_fixture_can_tell_the_outcomes_apart():
    """The control on the fixture. Three prices, all different, or the table
    below would pass without measuring the span at all."""
    assert len({OVERNIGHT_PRICE, TIME_BASED_SATURDAY, TIME_BASED_SUNDAY}) == 3


@pytest.mark.guarantee("F28")
def test_the_THREE_SPANS_on_ONE_STAY_are_an_axis():
    """The whole guarantee in one table.

    The same two stays under all three spans. `next_day` must sit strictly
    between the other two -- accepting what `same_day` refuses and refusing what
    `any_span` accepts -- or it is a spelling of one of them.
    """
    to_saturday = {span: _fee(span, TO_SATURDAY_MINUTES)[0] for span in
                   ("same_day", "next_day", "any_span")}
    to_sunday = {span: _fee(span, TO_SUNDAY_MINUTES)[0] for span in
                 ("same_day", "next_day", "any_span")}

    assert to_saturday == {
        "same_day": TIME_BASED_SATURDAY,
        "next_day": OVERNIGHT_PRICE,
        "any_span": OVERNIGHT_PRICE,
    }, f"the day-after stay: {to_saturday}"

    assert to_sunday == {
        "same_day": TIME_BASED_SUNDAY,
        "next_day": TIME_BASED_SUNDAY,
        "any_span": OVERNIGHT_PRICE,
    }, f"the day-after-that stay: {to_sunday}"

    assert to_saturday["next_day"] != to_saturday["same_day"], (
        "next_day accepts nothing same_day refuses -- it is same_day with another name"
    )
    assert to_sunday["next_day"] != to_sunday["any_span"], (
        "next_day refuses nothing any_span accepts -- it is any_span with another name"
    )


@pytest.mark.guarantee("F28")
def test_the_line_says_the_stay_ran_PAST_the_span_and_names_the_field():
    """The counter question is "why is a two-night stay not the overnight rate?",
    and the answer has to be in the breakdown."""
    _fee_minor, text = _fee("next_day", TO_SUNDAY_MINUTES)
    assert "is more than one local day after entry" in text, text
    assert "day_span 'next_day'" in text, (
        f"the line does not name the field that decided it: {text}"
    )


@pytest.mark.guarantee("F28")
def test_same_day_still_says_what_it_always_said():
    """The control on the wording: generalising the message must not have changed
    the sentence the shipped span prints."""
    _fee_minor, text = _fee("same_day", TO_SATURDAY_MINUTES)
    assert "is not the same local day as entry" in text, text
    assert "day_span 'same_day'" in text, text
