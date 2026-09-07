"""F35 -- two adjustments both apply, and the ORDER is the plan's to state.

**Not a choice between them. A sequence.** Twenty per cent off then five dollars
off is not five dollars off then twenty per cent off, and the difference is money
on a receipt. So this is neither the QUALIFY case -- where one rule wins and the
resolution mode picks -- nor the CAP case, where both apply and the total comes
out the same whichever ran first. It is a third thing, and it carries its own
finding code so a consumer routing on codes can tell "settle which of these is
the price" from "tell me what order to apply both in".

`adjust_order` deliberately does NOT live inside `resolution`. That field records
CHOICES, and an order is not a choice. It is required-and-nullable like
`max_duration_minutes` and `week_starts_on`, because a field that may simply be
absent is a field somebody forgets while believing they set it.

**A rule missing from a stated order is a refusal, not a silent position.** That
is the array-order disease this module already refuses at `select_plan`, where
two plan versions sharing a date used to be settled by whichever the caller put
first.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote
from rate_engine.findings import CONFLICT_UNORDERED_ADJUSTMENTS

RESOLUTION = {
    "QUALIFY": "cheapest_wins", "ACCUMULATE": "stated_order", "CAP": "stated_order",
    "SURCHARGE": "stated_order", "ADJUST": "stated_order",
}
EVERY_DAY = {"kind": "days_of_week",
             "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}

BASE = 3200  # 800 + 6 x 400, seven hours on the rate below

PERCENT_OFF = {
    "id": "pct", "type": "time_window", "stage": "ADJUST",
    "space_classes": ["standard"], "label": "Midweek 20% off",
    "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
    "exit_by": "23:59", "day_span": "any_span",
    "effect": {"kind": "adjust", "direction": "discount",
               "amount": {"kind": "percent", "percent_bp": 2000}, "rounding": "down"},
}
FIVE_OFF = {
    "id": "voucher", "type": "time_window", "stage": "ADJUST",
    "space_classes": ["standard"], "label": "Voucher 5.00 off",
    "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
    "exit_by": "23:59", "day_span": "any_span",
    "effect": {"kind": "adjust", "direction": "discount",
               "amount": {"kind": "fixed", "minor": 500}, "rounding": "down"},
}

#: percent first: 3200 - 640 = 2560, then -500 = 2060.
PERCENT_THEN_FIXED = 2060
#: fixed first: 3200 - 500 = 2700, then 20% of 2700 = 540 off = 2160.
FIXED_THEN_PERCENT = 2160


def _plan(adjust_order=None) -> dict:
    return {
        "plan_version": "order-2026-03",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York", "currency": "USD",
        "space_classes": ["standard"],
        "resolution": RESOLUTION,
        "adjust_order": adjust_order,
        "rules": [
            {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
             "space_classes": ["standard"], "first_period_minutes": 60,
             "first_period_minor": 800, "repeat_period_minutes": 60,
             "repeat_period_minor": 400, "rounding": "ceil",
             "max_duration_minutes": None},
            copy.deepcopy(PERCENT_OFF),
            copy.deepcopy(FIVE_OFF),
        ],
        "decisions": [],
    }


def _quote(plan: dict):
    return run_quote(
        {
            "plans": [plan], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T16:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )


def test_the_two_ORDERS_genuinely_disagree():
    """The control on the fixture, and it runs first. If these matched, "the
    plan must state the order" would be ceremony rather than arithmetic."""
    assert PERCENT_THEN_FIXED != FIXED_THEN_PERCENT


@pytest.mark.guarantee("F35")
def test_no_stated_order_is_REFUSED_and_names_BOTH():
    status, body = _quote(_plan(adjust_order=None))
    assert status == 422, body
    finding = body["findings"][0]
    assert finding["code"] == CONFLICT_UNORDERED_ADJUSTMENTS
    assert set(finding["rule_ids"]) == {"pct", "voucher"}
    assert "pct" in finding["text"] and "voucher" in finding["text"]
    assert "adjust_order" in finding["text"], finding["text"]


@pytest.mark.guarantee("F35")
def test_each_stated_order_produces_ITS_OWN_total():
    status, body = _quote(_plan(adjust_order=["pct", "voucher"]))
    assert status == 200, body
    assert body["fee_minor"] == PERCENT_THEN_FIXED

    status, body = _quote(_plan(adjust_order=["voucher", "pct"]))
    assert status == 200, body
    assert body["fee_minor"] == FIXED_THEN_PERCENT


@pytest.mark.guarantee("F35")
def test_the_BREAKDOWN_follows_the_stated_order_too():
    """The receipt reads in the order the money moved, so the second adjustment
    must name the total the first one left behind."""
    _s, body = _quote(_plan(adjust_order=["pct", "voucher"]))
    adjustments = [ln for ln in body["breakdown"] if ln["code"] == "time_window.applied"]
    assert [ln["rule_id"] for ln in adjustments] == ["pct", "voucher"]
    assert "on 25.60 USD" in adjustments[1]["text"], adjustments[1]["text"]

    _s, other = _quote(_plan(adjust_order=["voucher", "pct"]))
    adjustments = [ln for ln in other["breakdown"] if ln["code"] == "time_window.applied"]
    assert [ln["rule_id"] for ln in adjustments] == ["voucher", "pct"]
    assert "on 27.00 USD" in adjustments[1]["text"], adjustments[1]["text"]


@pytest.mark.guarantee("F35")
def test_ONE_qualifying_adjustment_needs_no_order():
    """The control on the refusal: it must fire on ambiguity, not on the presence
    of an ADJUST rule."""
    single = _plan(adjust_order=None)
    single["rules"] = [r for r in single["rules"] if r["id"] != "voucher"]
    status, body = _quote(single)
    assert status == 200, body
    assert body["fee_minor"] == BASE - 640


@pytest.mark.guarantee("F35")
def test_two_adjustments_that_cannot_BOTH_qualify_need_no_order_either():
    """Refusing on rule COUNT rather than on what QUALIFIES would reject a plan
    with a weekday discount and a weekend one, which is an ordinary garage."""
    weekday_and_weekend = _plan(adjust_order=None)
    for rule in weekday_and_weekend["rules"]:
        if rule["id"] == "pct":
            rule["applies_on"] = {"kind": "days_of_week", "days": ["mon", "tue"]}
        if rule["id"] == "voucher":
            rule["applies_on"] = {"kind": "days_of_week", "days": ["sat", "sun"]}
    status, body = _quote(weekday_and_weekend)
    assert status == 200, body
    assert body["fee_minor"] == BASE - 640


@pytest.mark.guarantee("F35")
@pytest.mark.parametrize(
    "order,expected",
    [
        (["pct"], "Missing: voucher"),
        (["pct", "voucher", "hourly"], "Not an ADJUST rule in this plan: hourly"),
        (["pct", "pct"], "names a rule more than once"),
        ("pct,voucher", "must be a list of rule ids"),
        ([1, 2], "must be a list of rule ids"),
    ],
)
def test_an_order_that_does_not_name_every_adjustment_EXACTLY_ONCE_is_REFUSED(order, expected):
    """Named explicitly and exhaustively, never by position: a rule left out
    would otherwise take a silent place in the sequence."""
    status, body = _quote(_plan(adjust_order=order))
    assert status == 400, f"{order!r} was accepted"
    assert "adjust_order" in body["error"], body["error"]
    assert expected in body["error"], body["error"]
