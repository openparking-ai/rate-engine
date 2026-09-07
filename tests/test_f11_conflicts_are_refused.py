"""F11 -- two rules qualifying at one stage are REFUSED, and both are named.

**This branch had never run.** No plan in the repository put two rules at one
stage, no test referenced `find_conflicts` or `CONFLICT_MULTIPLE_RULES_AT_STAGE`,
and `plan.resolution[stage]` is read in exactly one place: the text of the
conflict finding — which nothing had ever produced. So the plan's `resolution`
field, required on load with no default, was a mechanism that had never been
executed end to end, and the code published in `docs/CONTRACT.md`'s findings
table was a promise with nothing behind it.

The engine detects a conflict and refuses; it does not resolve one. The mode is
validated, recorded, quoted back in the refusal, and not acted on. That is stated
in the contract and it is what these tests pin down, so a later session reads a
deliberate boundary rather than a half-built mechanism.

**THE FIXTURES MOVED FROM SURCHARGE TO QUALIFY, and that is the point of F34
rather than a convenience here.** This file used to prove the refusal on two
surcharges, because in A1 no plan could put two rules at a RESOLVING stage --
there was one QUALIFY rule type and one ACCUMULATE rule type, so the only
reachable "two rules at one stage" was two of the same type at a composing one.
Refusing there was wrong and was going to bite: two ceilings are not a
contradiction, they are two ceilings, and the lower one wins. A2 makes the
distinction real, so this file now measures the refusal where it belongs -- two
specials competing to BE the price -- and
`tests/test_f34_composing_stages_do_not_conflict.py` holds the other arm.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2, stay
from rate_engine.engine import find_conflicts, quote
from rate_engine.findings import CONFLICT_MULTIPLE_RULES_AT_STAGE, Refused
from rate_engine.plan import load_plan

THREE_HOURS = stay("2026-03-03T09:14:00-05:00", 180)


def _with_extra(rule: dict) -> dict:
    document = copy.deepcopy(DOWNTOWN_V2)
    document["rules"] = document["rules"] + [rule]
    return document


#: Two windows that both qualify for the same stay. Both are bases; only one can
#: be the price, the plan does not say which, and the engine will not choose.
TWO_WINDOWS = _with_extra(
    {
        "id": "eb-late",
        "type": "time_window",
        "stage": "QUALIFY",
        "space_classes": ["standard"],
        "label": "Late bird",
        "applies_on": {"kind": "days_of_week", "days": ["mon", "tue", "wed", "thu", "fri"]},
        "enter_from": "06:00",
        "enter_by": "10:00",
        "exit_by": "17:00",
        "day_span": "same_day",
        "effect": {"kind": "flat", "price_minor": 1500},
    }
)

#: The same shape at a different stage, so the refusal is a property of the
#: pipeline rather than of one rule type.
TWO_INCREMENTS = _with_extra(
    {
        "id": "hourly-alternative",
        "type": "increment",
        "stage": "ACCUMULATE",
        "space_classes": ["standard"],
        "first_period_minutes": 30,
        "first_period_minor": 600,
        "repeat_period_minutes": 30,
        "repeat_period_minor": 300,
        "rounding": "ceil",
        "max_duration_minutes": None,
    }
)


def test_the_reference_plan_has_no_conflict_to_find():
    """The control, and it is why these fixtures had to be built at all.

    If the plan every other test uses already conflicted, the suite would be
    refusing everywhere and F11 would be measuring nothing.
    """
    assert find_conflicts(load_plan(DOWNTOWN_V2), THREE_HOURS) == []


@pytest.mark.guarantee("F11")
def test_two_rules_qualifying_at_one_stage_are_refused_and_both_named():
    early = stay("2026-03-03T08:30:00-05:00", 240)  # inside both windows
    with pytest.raises(Refused) as caught:
        quote([load_plan(TWO_WINDOWS)], early)

    finding = caught.value.findings[0]
    assert finding.code == CONFLICT_MULTIPLE_RULES_AT_STAGE
    assert set(finding.rule_ids) == {"eb-weekday", "eb-late"}
    assert "eb-weekday" in finding.text and "eb-late" in finding.text
    assert "QUALIFY" in finding.text


@pytest.mark.guarantee("F11")
def test_the_refusal_quotes_the_resolution_mode_the_plan_stated():
    """The only place `resolution` is ever read, and it had never been reached.

    The mode does not decide anything in A1. It is quoted back so the owner sees
    that the engine HAS their answer and is declining to apply it yet, rather
    than appearing to have ignored a field it made them fill in.
    """
    early = stay("2026-03-03T08:30:00-05:00", 240)
    document = copy.deepcopy(TWO_WINDOWS)
    document["resolution"]["QUALIFY"] = "cheapest_wins"
    with pytest.raises(Refused) as caught:
        quote([load_plan(document)], early)
    assert "cheapest_wins" in caught.value.findings[0].text

    document["resolution"]["QUALIFY"] = "stated_order"
    with pytest.raises(Refused) as caught:
        quote([load_plan(document)], early)
    assert "stated_order" in caught.value.findings[0].text, (
        "the refusal prints a fixed word rather than the plan's own mode"
    )


@pytest.mark.guarantee("F11")
def test_a_conflict_at_a_different_stage_is_refused_the_same_way():
    with pytest.raises(Refused) as caught:
        quote([load_plan(TWO_INCREMENTS)], THREE_HOURS)
    finding = caught.value.findings[0]
    assert finding.code == CONFLICT_MULTIPLE_RULES_AT_STAGE
    assert set(finding.rule_ids) == {"hourly", "hourly-alternative"}
    assert "ACCUMULATE" in finding.text


@pytest.mark.guarantee("F11")
def test_two_rules_at_one_stage_that_cannot_both_qualify_still_price():
    """The control that stops F11 being bought by refusing too widely.

    A second window scoped to days the stay does not fall on is not a conflict,
    because only one of them can ever qualify for a given stay. Refusing on rule
    COUNT rather than on what QUALIFIES would reject that plan, and this is what
    says so.
    """
    document = _with_extra(
        {
            "id": "eb-weekend",
            "type": "time_window",
            "stage": "QUALIFY",
            "space_classes": ["standard"],
            "label": "Weekend rate",
            "applies_on": {"kind": "days_of_week", "days": ["sat", "sun"]},
            "enter_from": "06:00",
            "enter_by": "09:00",
            "exit_by": "17:00",
            "day_span": "same_day",
            "effect": {"kind": "flat", "price_minor": 1500},
        }
    )
    plan = load_plan(document)
    assert len(plan.rules_for_stage("QUALIFY")) == 2

    # Derived from the unmodified plan rather than typed here, so this asserts
    # "the extra window changed nothing" and not a number that would have to be
    # re-guessed every time the reference plan's hourly rate changes.
    base = quote([load_plan(DOWNTOWN_V2)], THREE_HOURS).fee_minor
    assert quote([plan], THREE_HOURS).fee_minor == base

    # And it is not simply inert: on a Saturday it is the one that qualifies.
    saturday = stay("2026-03-07T07:00:00-05:00", 240)
    assert quote([plan], saturday).fee_minor == 1500
