"""F31 -- a percentage is basis points, and its `rounding` is CONSULTED.

**This is the first thing in the module that rounds MONEY.** Every rule before it
was an integer add or an integer replace, and `money.py` said in as many words
that nothing here rounds money. A percentage of a fee lands on a fraction of a
minor unit and somebody has to say who keeps it, so the plan says, per rule, with
no default -- the same disposition as every other pricing decision here.

**Integer basis points, not a decimal.** 20% is `2000` and 12.5% is `1250`.
`money.refuse_non_integer_money` rejects a float ANYWHERE in a plan, so a percent
field that could hold `20.5` would either be refused at load or would smuggle a
float into the pricing path through a field nobody was watching. Basis points
keep the arithmetic integer end to end, and the rendering turns them back into a
percentage a customer recognises.

The fixture is chosen so the fraction is real: 12.5% of 9.99 is 1.24875, which is
1.24 down and 1.25 up. A stay whose percentage came out whole would let this file
pass against an applier that ignored the field entirely -- the
`increment.rounding` shape, which shipped here once.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote

RESOLUTION = {
    "QUALIFY": "cheapest_wins", "ACCUMULATE": "stated_order", "CAP": "stated_order",
    "SURCHARGE": "stated_order", "ADJUST": "stated_order",
}

#: 999 minor units for the stay, so 12.5% is 124.875 -- a genuine fraction.
BASE = 999

PLAN = {
    "plan_version": "rounding-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": RESOLUTION,
    "rules": [
        {"id": "flat-hour", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": BASE, "repeat_period_minutes": 60,
         "repeat_period_minor": BASE, "rounding": "ceil", "max_duration_minutes": None},
        {"id": "midweek", "type": "time_window", "stage": "ADJUST",
         "space_classes": ["standard"], "label": "Midweek discount",
         "applies_on": {"kind": "days_of_week",
                        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
         "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
         "day_span": "any_span",
         "effect": {"kind": "adjust", "direction": "discount",
                    "amount": {"kind": "percent", "percent_bp": 1250},
                    "rounding": "down"}},
    ],
    "decisions": [],
}


def _quote(rounding: str | None = None, amount: dict | None = None):
    document = copy.deepcopy(PLAN)
    if rounding is not None:
        document["rules"][1]["effect"]["rounding"] = rounding
    if amount is not None:
        document["rules"][1]["effect"]["amount"] = amount
    return run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T10:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )


def _adjust_line(body: dict) -> dict:
    return [ln for ln in body["breakdown"] if ln["code"] == "time_window.applied"][0]


def test_the_fixture_lands_on_a_REAL_FRACTION():
    """The control on the fixture, and it runs first.

    12.5% of 999 is 124.875. If it had come out whole, an applier that never read
    `rounding` would pass every assertion below.
    """
    assert BASE * 1250 % 10_000 != 0


@pytest.mark.guarantee("F31")
def test_the_same_stay_differs_by_ONE_MINOR_UNIT_between_up_and_down():
    _s, down = _quote("down")
    _s, up = _quote("up")
    assert down["fee_minor"] == BASE - 124
    assert up["fee_minor"] == BASE - 125
    assert down["fee_minor"] - up["fee_minor"] == 1, (
        f"rounding changed nothing: {down['fee_minor']} both ways -- the field is "
        f"validated, stored, and never read"
    )


@pytest.mark.guarantee("F31")
def test_the_LINE_SAYS_which_way_it_went():
    """A customer disputing a cent has to be shown the answer, not told it."""
    for rounding in ("up", "down"):
        _s, body = _quote(rounding)
        assert f"(rounded {rounding})" in _adjust_line(body)["text"], (
            _adjust_line(body)["text"]
        )


@pytest.mark.guarantee("F31")
def test_basis_points_RENDER_as_a_percentage_a_customer_recognises():
    """The plan carries 1250 because a plan carries integers. The receipt says
    12.5%, because that is what the operator quoted."""
    _s, body = _quote("down")
    assert "12.5% discount on 9.99 USD" in _adjust_line(body)["text"], _adjust_line(body)["text"]

    _s, whole = _quote("down", {"kind": "percent", "percent_bp": 2000})
    assert "20% discount" in _adjust_line(whole)["text"], _adjust_line(whole)["text"]
    assert "20.0" not in _adjust_line(whole)["text"]


@pytest.mark.guarantee("F31")
def test_a_FIXED_amount_needs_no_rounding_and_is_priced_exactly():
    """The other amount kind, and the control on the arithmetic above: an amount
    stated in minor units is subtracted as written."""
    _s, body = _quote("down", {"kind": "fixed", "minor": 250})
    assert body["fee_minor"] == BASE - 250
    assert "2.50 USD discount on 9.99 USD" in _adjust_line(body)["text"]
    assert "rounded" not in _adjust_line(body)["text"], (
        "a fixed amount rounds nothing, so the line must not claim a direction"
    )


@pytest.mark.guarantee("F31")
@pytest.mark.parametrize(
    "effect,expected",
    [
        ({"kind": "adjust", "direction": "discount",
          "amount": {"kind": "percent", "percent_bp": 1250}}, "missing required field"),
        ({"kind": "adjust", "direction": "discount", "rounding": "down",
          "amount": {"kind": "percent", "percent_bp": 12.5}}, "float"),
        ({"kind": "adjust", "direction": "discount", "rounding": "down",
          "amount": {"kind": "percent", "percent_bp": 0}}, "positive whole number"),
        ({"kind": "adjust", "direction": "discount", "rounding": "nearest",
          "amount": {"kind": "percent", "percent_bp": 1250}}, "rounding is 'nearest'"),
        ({"kind": "adjust", "direction": "less", "rounding": "down",
          "amount": {"kind": "percent", "percent_bp": 1250}}, "direction is 'less'"),
        ({"kind": "adjust", "direction": "discount", "rounding": "down",
          "amount": {"kind": "ratio", "numerator": 1}}, "kind is 'ratio'"),
        ({"kind": "multiply", "factor": 2}, "kind is 'multiply'"),
    ],
)
def test_a_shape_the_engine_cannot_price_is_REFUSED_by_name(effect, expected):
    """No default anywhere, and a mode this version does not implement is refused
    rather than priced under another one."""
    document = copy.deepcopy(PLAN)
    document["rules"][1]["effect"] = effect
    status, body = run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T10:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )
    assert status == 400, f"{effect!r} was accepted"
    assert expected in body["error"], body["error"]
