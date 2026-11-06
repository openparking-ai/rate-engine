"""F70 -- a price can never be below $0, and a discount bigger than the fee never refuses.

Gokhan, 2026-11-07: **"Rate cannot be below $0."** And on a discount bigger than
the fee: it floors at $0, it is not refused. So a fixed discount takes off at most
what the stay costs and the line says it was limited; two discounts in a row take
off at most what is left; a 100% discount makes the stay free; and none of that is
ever answered with `CONFLICT_NEGATIVE_TOTAL`, the refusal that used to stand
behind a negative fee.

Already how the engine prices a fixed discount (F57), so this builds nothing new for
that. It pins the whole claim as a sweep rather than as one stay: every combination
of discounts that can be written, in every order the plan can state, on stays of
every length and on both ways of pricing the time, comes out at $0 or more, adds
up, and is priced.

**What it does not say, and is not decided here.** A percent discount ABOVE 100%
still does not load (F60, Gokhan 2026-10-16: refused when the plan is saved). That is
a refusal of a plan, not of a stay, and nothing he has said since changes it; it is
listed as a question.

`scripts/fail_controls.py` lets a fixed discount take off more than the charge, and
requires this file to go red.
"""

from __future__ import annotations

import itertools

import pytest

from _real_options import TUESDAY_8AM, flat, plan, quote

SATURDAY_10AM = "2026-03-07T10:00:00-05:00"
#: 3.00 the first hour, 3.00 each hour after: small enough that every discount here
#: is bigger than some stay's fee and smaller than another's.
CHEAP = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 60,
    "first_period_minor": 300, "repeat_period_minutes": 60,
    "repeat_period_minor": 300, "rounding": "ceil", "max_duration_minutes": None,
}


def _adjust(rule_id: str, direction: str, amount: dict) -> dict:
    return {
        "id": rule_id, "type": "time_window", "stage": "ADJUST",
        "space_classes": ["standard"], "label": rule_id,
        "applies_on": {"kind": "days_of_week", "days": ["sat"]},
        "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
        "day_span": "same_day",
        "effect": {"kind": "adjust", "direction": direction, "amount": amount,
                   "rounding": "down"},
    }


FIXED = lambda minor: {"kind": "fixed", "minor": minor}  # noqa: E731
PERCENT = lambda bp: {"kind": "percent", "percent_bp": bp}  # noqa: E731

DISCOUNTS = {
    "five": _adjust("five", "discount", FIXED(500)),
    "huge": _adjust("huge", "discount", FIXED(1_000_000)),
    "all": _adjust("all", "discount", PERCENT(10_000)),
    "half": _adjust("half", "discount", PERCENT(5_000)),
    "event": _adjust("event", "increase", FIXED(400)),
}


def _plan(names: tuple[str, ...], order: tuple[str, ...], special: bool) -> dict:
    rules = [CHEAP, *(DISCOUNTS[n] for n in names)]
    if special:
        rules.append(flat("sat-flat", 1200, days=["sat"], day_span="same_day"))
    document = plan(*rules)
    document["adjust_order"] = list(order) if len(names) > 1 else None
    return document


@pytest.mark.guarantee("F70")
def test_a_discount_bigger_than_the_fee_makes_it_free_and_says_it_was_limited():
    document = _plan(("huge",), ("huge",), special=False)
    status, body = quote(document, SATURDAY_10AM, 60)
    assert status == 200, body
    assert body["fee_minor"] == 0
    line = next(ln for ln in body["breakdown"] if ln["rule_id"] == "huge")
    assert line["delta_minor"] == -300
    assert "limited to the 3.00 USD charged" in line["text"]


@pytest.mark.guarantee("F70")
def test_a_100_percent_discount_is_free_and_the_second_discount_has_nothing_left():
    document = _plan(("all", "five"), ("all", "five"), special=False)
    status, body = quote(document, SATURDAY_10AM, 90)
    assert status == 200, body
    assert body["fee_minor"] == 0
    five = next(ln for ln in body["breakdown"] if ln["rule_id"] == "five")
    assert five["delta_minor"] == 0, "nothing is left to take 5.00 off"


@pytest.mark.guarantee("F70")
def test_the_sweep_every_discount_in_every_order_on_every_length_is_priced_at_zero_or_more():
    priced = floored = 0
    names_sets = [n for r in (1, 2, 3) for n in itertools.combinations(sorted(DISCOUNTS), r)]
    for names, special, minutes in itertools.product(
        names_sets, (False, True), (1, 30, 60, 61, 180, 600, 1500)
    ):
        for order in itertools.permutations(names):
            document = _plan(names, order, special)
            status, body = quote(document, SATURDAY_10AM, minutes)
            case = f"{names} {order} special={special} +{minutes}"
            assert status == 200, f"{case}: refused: {body}"
            assert body["fee_minor"] >= 0, case
            assert body["fee_minor"] == sum(ln["delta_minor"] for ln in body["breakdown"]), case
            assert all(f["code"] != "CONFLICT_NEGATIVE_TOTAL"
                       for f in body.get("findings", [])), case
            priced += 1
            floored += body["fee_minor"] == 0
    assert priced > 1000 and floored > 500, (priced, floored)


@pytest.mark.guarantee("F70")
def test_a_discount_on_a_special_is_floored_too():
    document = _plan(("huge",), ("huge",), special=True)
    status, body = quote(document, SATURDAY_10AM, 600)
    assert status == 200 and body["fee_minor"] == 0
    assert any(ln["rule_id"] == "sat-flat" and ln["delta_minor"] == 1200
               for ln in body["breakdown"]), "the special priced the stay, and was floored after"


@pytest.mark.guarantee("F70")
def test_a_discount_that_does_not_exceed_the_fee_takes_off_exactly_its_amount():
    """The floor is not a cap on discounts: 5.00 off a 12.00 fee is 7.00."""
    document = _plan(("five",), ("five",), special=False)
    status, body = quote(document, SATURDAY_10AM, 240)   # 4 h at 3.00 = 12.00
    assert status == 200 and body["fee_minor"] == 700, body


@pytest.mark.guarantee("F70")
def test_a_weekday_stay_is_untouched_by_a_saturday_discount():
    document = _plan(("huge",), ("huge",), special=False)
    status, body = quote(document, TUESDAY_8AM, 60)
    assert status == 200 and body["fee_minor"] == 300
