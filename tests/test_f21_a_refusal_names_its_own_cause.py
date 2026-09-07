"""F21 -- every refusal's CODE names the thing that actually happened.

A negative total was refused with `CONFLICT_MULTIPLE_RULES_AT_STAGE`, a code
documented exclusively for two rules qualifying at one stage. Nothing was
mispriced and the SENTENCE said what really happened -- but the code is what
anything mechanical keys off, and a consumer routing on it would have told an
operator to settle a resolution order that was not the problem.

`findings.py`'s own header says it: "The sentence is for the operator; `code` is
what anything mechanical uses." A code that names a cause which did not occur is
a claim defect, and this module refuses to guess about money in every other place.

**Reachability, stated honestly.** With the four rule types A1 ships a negative
total cannot occur: every money field goes through `as_non_negative_minor`, and
`daily_max` sets the total to exactly `max_minor x days`, which is non-negative.
The branch is registered and tested anyway, because a rule type is this module's
unit of growth and the first one that can return a negative Line should meet a
named refusal rather than a mislabelled one. The test reaches it the only way it
can be reached -- by registering such a rule type.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.breakdown import Line
from rate_engine.contract import run_quote
from rate_engine.engine import QUALIFIERS, quote
from rate_engine.findings import (
    CONFLICT_MULTIPLE_RULES_AT_STAGE,
    CONFLICT_NEGATIVE_TOTAL,
    Refused,
)
from rate_engine.plan import load_plan
from rate_engine.rules import RULE_APPLIERS, RULE_TYPES, Rule, common_fields, register
from rate_engine.stages import ACCUMULATE

TYPE_NAME = "f21_negative"


def _register_a_rule_that_returns_a_negative_line(amount: int = -5000):
    def build(raw, plan_space_classes, where):
        rule_id, classes = common_fields(raw, plan_space_classes, where, {"amount"})
        return Rule(id=rule_id, type=TYPE_NAME, stage=ACCUMULATE,
                    space_classes=classes, params={})

    def apply(rule, stay, plan):
        return [Line(code="f21.negative", rule_id=rule.id, text="a negative line",
                     delta_minor=amount)]

    register(TYPE_NAME, ACCUMULATE, build, apply)
    QUALIFIERS[TYPE_NAME] = lambda rule, stay, plan: rule.covers(stay.space_class)


def _unregister():
    RULE_TYPES.pop(TYPE_NAME, None)
    RULE_APPLIERS.pop(TYPE_NAME, None)
    QUALIFIERS.pop(TYPE_NAME, None)


def _document() -> dict:
    document = copy.deepcopy(DOWNTOWN_V2)
    document["rules"] = [
        r for r in document["rules"] if r["id"] not in ("hourly", "eb-weekday", "cap")
    ] + [
        {"id": "f21-1", "type": TYPE_NAME, "stage": "ACCUMULATE",
         "space_classes": ["standard", "vip"], "amount": 0}
    ]
    return document


@pytest.fixture
def negative_rule():
    _register_a_rule_that_returns_a_negative_line()
    try:
        yield
    finally:
        _unregister()


@pytest.mark.guarantee("F21")
def test_a_negative_total_is_refused_by_ITS_OWN_code(negative_rule):
    with pytest.raises(Refused) as caught:
        quote([load_plan(_document())], _stay())
    finding = caught.value.findings[0]
    assert finding.code == CONFLICT_NEGATIVE_TOTAL
    assert finding.code != CONFLICT_MULTIPLE_RULES_AT_STAGE, (
        "the refusal names a cause that did not occur"
    )
    assert "negative fee" in finding.text


@pytest.mark.guarantee("F21")
def test_the_code_reaches_a_caller_unchanged(negative_rule):
    """A code nothing mechanical can read is not a code."""
    status, body = run_quote(
        {
            "plans": [_document()], "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T10:40:00-05:00", "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 422
    assert body["findings"][0]["code"] == CONFLICT_NEGATIVE_TOTAL
    assert body["findings"][0]["kind"] == "conflict"


@pytest.mark.guarantee("F21")
def test_the_MULTI_RULE_conflict_still_uses_the_multi_rule_code():
    """The control on the item above, and the half that would catch an over-broad
    fix: splitting a code must not have moved the case it was split FROM."""
    document = copy.deepcopy(DOWNTOWN_V2)
    document["space_classes"] = ["standard"]
    document["rules"] = [
        {"id": "eb-a", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Early bird A",
         "applies_on": {"kind": "days_of_week", "days": ["tue"]},
         "enter_from": "00:00", "enter_by": "09:00", "exit_by": "17:00",
         "day_span": "same_day", "effect": {"kind": "flat", "price_minor": 1000}},
        {"id": "eb-b", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Early bird B",
         "applies_on": {"kind": "days_of_week", "days": ["tue"]},
         "enter_from": "00:00", "enter_by": "10:00", "exit_by": "18:00",
         "day_span": "same_day", "effect": {"kind": "flat", "price_minor": 1100}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
    ]
    status, body = run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T08:00:00-05:00",
            "exit_at": "2026-03-03T12:00:00-05:00", "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 422
    assert body["findings"][0]["code"] == CONFLICT_MULTIPLE_RULES_AT_STAGE


def _stay():
    from rate_engine.engine import make_stay
    from rate_engine.plan import parse_instant

    return make_stay(
        parse_instant("2026-03-03T09:14:00-05:00", "e"),
        parse_instant("2026-03-03T10:40:00-05:00", "x"),
        "standard",
    )


def test_no_two_registered_codes_share_a_string():
    """Cheap, and it is the failure this item is an instance of.

    Two constants with the same value would make `kind` and every consumer
    ambiguous while every test still passed.
    """
    from rate_engine.findings import ALL_CODES

    assert len(ALL_CODES) == len(set(ALL_CODES)), "two finding codes share a value"
