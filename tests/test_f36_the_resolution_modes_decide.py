"""F36 -- the resolution modes finally DECIDE something.

**They were a decision the owner made and the software ignored.** `resolution`
was required on every plan, validated against two named modes, published in the
contract's own table -- and read in exactly one place: the text of a conflict
finding, quoting the mode back while declining to apply it. `find_conflicts` said
so in its own docstring. A required field that changes no answer is the shape of
defect this project has a name for, and it shipped here for a whole round.

Two modes, and the same stay under both, because that is the only arrangement
that shows the FIELD deciding rather than one plan pricing one way:

* `cheapest_wins` -- the lowest fee for the customer. Gokhan's, confirmed in
  session.
* `stated_order` -- the plan names the rule ids and the first that qualifies
  wins.

**And the rules that LOST still appear on the receipt.** §8's first requirement
is that a customer can read why they were charged what they were charged, and a
breakdown that silently omits a rate the customer nearly got cannot answer the
question an attendant is actually asked. The line names the loser, its price, the
winner, the winner's price, and the mode that chose between them.

The fixture prices the two windows DIFFERENTLY on purpose: at the same price
neither mode could be shown deciding, and `cheapest_wins` would refuse instead.
"""

from __future__ import annotations

import pytest

from rate_engine.contract import run_quote

EVERY_DAY = {"kind": "days_of_week",
             "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}

EARLY_BIRD = 1200
WEEKEND = 1500


def _window(rule_id: str, label: str, price: int) -> dict:
    return {
        "id": rule_id, "type": "time_window", "stage": "QUALIFY",
        "space_classes": ["standard"], "label": label,
        "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
        "exit_by": "23:59", "day_span": "any_span",
        "effect": {"kind": "flat", "price_minor": price},
    }


def _plan(resolution: dict) -> dict:
    return {
        "plan_version": "resolve-2026-03",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York", "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {"QUALIFY": resolution, "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": None,
        "rules": [
            _window("eb", "Early bird", EARLY_BIRD),
            _window("weekend", "Weekend rate", WEEKEND),
            {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
             "space_classes": ["standard"], "first_period_minutes": 60,
             "first_period_minor": 800, "repeat_period_minutes": 60,
             "repeat_period_minor": 400, "rounding": "ceil",
             "max_duration_minutes": None},
        ],
        "decisions": [],
    }


def _quote(resolution: dict):
    return run_quote(
        {
            "plans": [_plan(resolution)], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T13:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )


def _applied(body: dict) -> list[str]:
    return [ln["rule_id"] for ln in body["breakdown"] if ln["code"] == "time_window.applied"]


def _resolved(body: dict) -> list[dict]:
    return [ln for ln in body["breakdown"] if ln["code"] == "resolved"]


def test_the_fixture_can_tell_the_two_winners_apart():
    """The control on the fixture, and it runs first. If both windows charged the
    same, `cheapest_wins` would refuse and `stated_order` would be the only mode
    this file could exercise."""
    assert EARLY_BIRD != WEEKEND


@pytest.mark.guarantee("F36")
def test_cheapest_wins_picks_the_LOWER_FEE_FOR_THE_CUSTOMER():
    status, body = _quote({"mode": "cheapest_wins"})
    assert status == 200, body
    assert body["fee_minor"] == EARLY_BIRD
    assert _applied(body) == ["eb"]


@pytest.mark.guarantee("F36")
def test_stated_order_picks_THE_ONE_THE_PLAN_NAMES_FIRST_on_the_same_stay():
    """The same stay, the same two rules, a different field -- and a different
    answer. That is what makes this the FIELD deciding."""
    status, body = _quote({"mode": "stated_order", "order": ["weekend", "eb"]})
    assert status == 200, body
    assert body["fee_minor"] == WEEKEND, (
        "the stated order was ignored and the cheaper rule won anyway"
    )
    assert _applied(body) == ["weekend"]


@pytest.mark.guarantee("F36")
def test_and_REVERSING_the_stated_order_reverses_the_answer():
    """The control on the item above: an order that happened to agree with
    `cheapest_wins` would prove nothing about the order being read."""
    status, body = _quote({"mode": "stated_order", "order": ["eb", "weekend"]})
    assert status == 200, body
    assert body["fee_minor"] == EARLY_BIRD
    assert _applied(body) == ["eb"]


@pytest.mark.guarantee("F36")
def test_the_rule_that_LOST_still_appears_and_names_the_winner():
    """The line an attendant is read at the counter."""
    _status, body = _quote({"mode": "cheapest_wins"})
    lost = _resolved(body)
    assert len(lost) == 1, [ln["code"] for ln in body["breakdown"]]
    line = lost[0]
    assert line["rule_id"] == "weekend"
    assert line["delta_minor"] == 0, "a rule that did not apply moved the fee"
    assert line["text"] == (
        "Weekend rate qualified at 15.00 USD -- Early bird 12.00 USD applied "
        "instead (plan resolves QUALIFY by cheapest_wins)"
    ), line["text"]


@pytest.mark.guarantee("F36")
def test_the_loser_line_names_the_MODE_THAT_CHOSE_and_it_follows_the_plan():
    """Not a fixed sentence: change the mode and the sentence has to change with
    it, or it is prose borrowing the mechanism's credibility."""
    _s, cheapest = _quote({"mode": "cheapest_wins"})
    _s, stated = _quote({"mode": "stated_order", "order": ["weekend", "eb"]})

    assert "by cheapest_wins" in _resolved(cheapest)[0]["text"]
    assert "by stated_order" in _resolved(stated)[0]["text"]
    assert _resolved(stated)[0]["rule_id"] == "eb", (
        "the loser under a stated order is the rule the order did not name first"
    )


@pytest.mark.guarantee("F36")
def test_the_LEDGER_still_sums_when_a_rule_is_resolved_away():
    """A rule removed from the pricing must be removed from the MONEY too. The
    engine asserts this on every quote; this is the fixture that reaches it with
    a loser in the breakdown."""
    _status, body = _quote({"mode": "cheapest_wins"})
    assert sum(ln["delta_minor"] for ln in body["breakdown"]) == body["fee_minor"]
    assert body["fee_minor"] == EARLY_BIRD, "the loser's price leaked into the fee"


@pytest.mark.guarantee("F36")
def test_resolution_is_keyed_ONLY_by_the_stages_that_can_resolve():
    """A mode stated for a stage that cannot resolve is a decision that does
    nothing, and this module has shipped one of those. CAP composes -- both caps
    apply -- so a mode there could never choose anything, and the key is refused
    by name like every other key this version does not understand."""
    document = _plan({"mode": "cheapest_wins"})
    document["resolution"]["CAP"] = {"mode": "cheapest_wins"}
    status, body = run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T13:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )
    assert status == 400
    assert "CAP" in body["error"] and "does not understand" in body["error"], body["error"]
