"""F4 -- money is an integer of minor units, and a plan that says otherwise is
refused at load.

Refused AT LOAD, not at the point the arithmetic goes wrong: a float that reaches
the pipeline has already been written into a plan an operator believes is live.

Three shapes are tested separately because they are three different ways in and a
guard that stops one lets the others past:

* a plain float (``8.5``)
* a float that looks whole (``800.0``, and JSON's ``8e2`` which parses to one)
* a ``bool``, which is an ``int`` subclass in Python -- ``isinstance(True, int)``
  is ``True``, so a naive integer check accepts it and prices the stay at one cent

And a fourth that is not about a field the engine reads: a float sitting in a
part of the plan this version ignores. It is refused too, because the round that
adds the rule type which reads it is the round it starts pricing something.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from fixtures import DOWNTOWN_V2, plan_with, with_rule_field
from rate_engine.money import NotMinorUnits, as_minor
from rate_engine.plan import InvalidPlan, load_plan


def _refused(document) -> str:
    with pytest.raises((InvalidPlan, NotMinorUnits)) as caught:
        load_plan(document)
    return str(caught.value)


@pytest.mark.guarantee("F4")
def test_a_fractional_price_is_refused_at_load():
    message = _refused(with_rule_field("hourly", first_period_minor=8.5))
    assert "float" in message
    assert "first_period_minor" in message, "the refusal must name the field"


@pytest.mark.guarantee("F4")
def test_a_float_that_looks_whole_is_refused_too():
    """800.0 is not 800. There is no "but it is a whole number" branch, because
    that branch is how every other float gets in."""
    assert "float" in _refused(with_rule_field("hourly", first_period_minor=800.0))


@pytest.mark.guarantee("F4")
def test_json_exponent_form_parses_to_a_float_and_is_refused():
    """A plan author writing 8e2 for eight dollars produces a float, silently."""
    raw = json.dumps(DOWNTOWN_V2).replace('"first_period_minor": 800', '"first_period_minor": 8e2')
    document = json.loads(raw)
    assert isinstance(
        next(r for r in document["rules"] if r["id"] == "hourly")["first_period_minor"], float
    ), "this test's own premise: JSON exponent form is a float"
    assert "float" in _refused(document)


@pytest.mark.guarantee("F4")
def test_a_bool_is_refused_even_though_python_calls_it_an_int():
    assert isinstance(True, int), "this test's own premise: bool subclasses int in Python"
    message = _refused(with_rule_field("hourly", first_period_minor=True))
    assert "boolean" in message


@pytest.mark.guarantee("F4")
def test_a_decimal_is_refused():
    """Accurate, and still refused: one money type all the way down."""
    with pytest.raises(NotMinorUnits) as caught:
        as_minor(Decimal("8.00"), "rules[0].first_period_minor")
    assert "Decimal" in str(caught.value)


@pytest.mark.guarantee("F4")
def test_a_float_in_a_field_this_version_ignores_is_refused_as_well():
    """It is not read today. It is in a live plan, and it will be read one day."""
    document = plan_with(decisions=[])
    document["rules"][0]["space_classes"] = ["standard"]
    document["decisions"] = [
        {
            "code": "GAP_NO_ACCUMULATE_RULE",
            "decided_by": "owner",
            "decided_at": "2026-03-01",
            "note": 1.5,
        }
    ]
    assert "float" in _refused(document)


