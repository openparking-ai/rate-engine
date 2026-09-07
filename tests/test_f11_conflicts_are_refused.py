"""F11 -- two rules qualifying at one stage are REFUSED, and both are named.

**This branch had never run.** No plan in the repository put two rules at one
stage, no test referenced `find_conflicts` or `CONFLICT_MULTIPLE_RULES_AT_STAGE`,
and `plan.resolution[stage]` is read in exactly one place: the text of the
conflict finding — which nothing had ever produced. So the plan's `resolution`
field, required on load with no default, was a mechanism that had never been
executed end to end, and the code published in `docs/CONTRACT.md`'s findings
table was a promise with nothing behind it.

A1 detects a conflict and refuses; it does not resolve one. Resolving honestly
needs two rule types that can qualify at one stage, which is round A2 — so the
mode is validated, recorded, quoted back in the refusal, and not acted on. That
is stated in the contract and it is what these tests pin down, so a later session
reads a deliberate boundary rather than a half-built mechanism.
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


#: Two surcharges on the SAME space class. Both qualify; the plan does not say
#: which wins, and A1 will not choose.
TWO_SURCHARGES = _with_extra(
    {
        "id": "vip-extra",
        "type": "space_surcharge",
        "stage": "SURCHARGE",
        "space_classes": ["vip"],
        "surcharge_minor": 700,
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
    vip_stay = stay("2026-03-03T09:14:00-05:00", 180, "vip")
    with pytest.raises(Refused) as caught:
        quote([load_plan(TWO_SURCHARGES)], vip_stay)

    finding = caught.value.findings[0]
    assert finding.code == CONFLICT_MULTIPLE_RULES_AT_STAGE
    assert set(finding.rule_ids) == {"vip-surcharge", "vip-extra"}
    assert "vip-surcharge" in finding.text and "vip-extra" in finding.text
    assert "SURCHARGE" in finding.text


@pytest.mark.guarantee("F11")
def test_the_refusal_quotes_the_resolution_mode_the_plan_stated():
    """The only place `resolution` is ever read, and it had never been reached.

    The mode does not decide anything in A1. It is quoted back so the owner sees
    that the engine HAS their answer and is declining to apply it yet, rather
    than appearing to have ignored a field it made them fill in.
    """
    document = copy.deepcopy(TWO_SURCHARGES)
    document["resolution"]["SURCHARGE"] = "cheapest_wins"
    with pytest.raises(Refused) as caught:
        quote([load_plan(document)], stay("2026-03-03T09:14:00-05:00", 180, "vip"))
    assert "cheapest_wins" in caught.value.findings[0].text

    document["resolution"]["SURCHARGE"] = "stated_order"
    with pytest.raises(Refused) as caught:
        quote([load_plan(document)], stay("2026-03-03T09:14:00-05:00", 180, "vip"))
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

    `downtown_v2` already carries two SURCHARGE-eligible classes; a second
    surcharge scoped to a DIFFERENT class is not a conflict, because only one of
    them can ever qualify for a given stay. Refusing on rule COUNT rather than on
    what QUALIFIES would reject that plan, and this is what says so.
    """
    document = _with_extra(
        {
            "id": "standard-surcharge",
            "type": "space_surcharge",
            "stage": "SURCHARGE",
            "space_classes": ["standard"],
            "surcharge_minor": 100,
        }
    )
    plan = load_plan(document)
    assert len(plan.rules_for_stage("SURCHARGE")) == 2

    # The base is derived from the unmodified plan rather than typed here, so
    # this asserts "the surcharge was added" and not a number that would have to
    # be re-guessed every time the reference plan's hourly rate changes.
    base = quote([load_plan(DOWNTOWN_V2)], THREE_HOURS).fee_minor

    standard = quote([plan], THREE_HOURS)
    assert standard.fee_minor == base + 100

    vip_stay = stay("2026-03-03T09:14:00-05:00", 180, "vip")
    vip_base = quote([load_plan(DOWNTOWN_V2)], vip_stay).fee_minor
    vip = quote([plan], vip_stay)
    assert vip.fee_minor == vip_base, "the vip stay's own surcharge was already in the base"
    assert vip.fee_minor > standard.fee_minor
