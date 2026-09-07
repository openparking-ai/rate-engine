"""F8 -- the fee is the sum of the breakdown's deltas, by construction.

The brief asked for a rule "whose reported line disagrees with its own effect".
Under the ledger that defect is not writable: a rule's only way to change the fee
IS to return a Line, so its line and its effect are the same object. That is the
point -- the guarantee is structural rather than a comparison between two copies
of one claim, and §6 is explicit that comparing two copies verifies nothing.

So the defect this file plants is the one that IS writable and that would
reintroduce the problem: a second route to the total. An engine that adjusts the
fee outside the ledger, or a rule that mutates something the ledger does not see.
The invariant in `engine._assert_ledger_is_the_fee` catches it, it lives in the
production path rather than only in tests, and `scripts/fail_controls.py` plants
exactly that second route and requires red.

The other half is registration-time: a rule that returns something which is not a
Line, or a Line carrying non-integer money, cannot enter the ledger at all.
"""

from __future__ import annotations

import pytest

from fixtures import CORPUS, loaded
from rate_engine.breakdown import Ledger, Line
from rate_engine.engine import quote
from rate_engine.findings import Refused
from rate_engine.money import NotMinorUnits


@pytest.mark.guarantee("F8")
def test_every_priced_fixture_equals_the_sum_of_its_lines():
    priced = 0
    for name, s in CORPUS.items():
        try:
            result = quote([loaded()], s)
        except Refused:
            continue
        priced += 1
        assert result.fee_minor == sum(line.delta_minor for line in result.breakdown.lines), name
    assert priced >= 10, f"only {priced} fixtures were priced; this proves too little"


@pytest.mark.guarantee("F8")
def test_a_cap_gives_back_exactly_what_it_took():
    """The line that made a plain sum impossible, and the arithmetic it now shows."""
    result = quote([loaded()], CORPUS["worked_example"])
    lines = {line.code: line for line in result.breakdown.lines}

    charged = (
        lines["increment.first_period"].delta_minor
        + lines["increment.repeat_periods"].delta_minor
    )
    assert charged == 4400
    assert lines["daily_max.applied"].delta_minor == -1400
    assert result.fee_minor == 3000 == charged + lines["daily_max.applied"].delta_minor
    assert "44.00 USD reduced to 30.00 USD" in lines["daily_max.applied"].text, (
        "the line must describe its own delta, not merely announce that a cap applied"
    )


@pytest.mark.guarantee("F8")
def test_a_rule_that_did_not_apply_contributes_exactly_zero():
    result = quote([loaded()], CORPUS["worked_example"])
    for line in result.breakdown.lines:
        if line.code.endswith(("not_applied", "not_reached")) or line.code == "stay":
            assert line.delta_minor == 0, f"{line.code} moved the fee while reporting it did not"


@pytest.mark.guarantee("F8")
def test_a_line_cannot_carry_non_integer_money():
    """Registration-time half: a Line is refused before it can reach a ledger."""
    for bad in (8.5, 800.0, True, "800"):
        with pytest.raises(NotMinorUnits):
            Line(code="x", rule_id=None, text="t", delta_minor=bad)


@pytest.mark.guarantee("F8")
def test_the_ledger_offers_no_route_to_the_total_except_adding_a_line():
    """A structural assertion about the type, not about one run of it.

    If a `set_total`, an `adjust` or a writable `total_minor` ever appears, the
    invariant becomes bypassable and this goes red the moment it is added rather
    than the round somebody uses it.
    """
    ledger = Ledger()
    writable = [
        name
        for name in dir(ledger)
        if not name.startswith("_") and name not in {"lines", "add", "total_minor", "to_json"}
    ]
    assert writable == [], f"Ledger grew {writable}; a second route to the total is a defect"

    with pytest.raises(AttributeError):
        ledger.total_minor = 999


def test_the_sum_check_can_tell_a_wrong_total_from_a_right_one():
    """The control on this file's own assertion.

    Without it, "the fee equals the sum" is a sentence that has never been shown
    to be false for anything.
    """
    ledger = Ledger()
    ledger.add(Line(code="a", rule_id=None, text="a", delta_minor=800))
    ledger.add(Line(code="b", rule_id=None, text="b", delta_minor=-300))
    assert ledger.total_minor == 500
    assert ledger.total_minor != 501
