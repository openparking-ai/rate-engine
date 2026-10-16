"""F57 -- a fixed discount takes off at most what the stay costs.

A fixed-amount discount was not limited to the charge, so a stay cheaper than
the discount went below zero and the engine refused it as a negative fee. The
plan check prices nothing, so it accepted the plan. $3 the first hour, $3 an
hour after, "Weekend $5 off": every Saturday stay of 60 minutes or less was
refused with `CONFLICT_NEGATIVE_TOTAL`, and those stays closed unpriced. The
money is the same as a limit gives -- nothing -- but each one was an exception
for somebody to look at.

The discount is now limited to the running total, and the line says so. A
discount smaller than the charge is taken in full, as before, with nothing said
about a limit.

`scripts/fail_controls.py` removes the limit, and separately removes the words
that say it was applied, and requires this file to go red each time.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote
from rate_engine.engine import quote
from rate_engine.findings import Refused
from rate_engine.plan import load_plan
from rate_engine.validator import probe_stays, validate_plan

PLAN = {
    "plan_version": "weekend-off-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                   "ACCUMULATE": {"mode": "cheapest_wins"}},
    "adjust_order": None,
    "rules": [
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 300, "repeat_period_minutes": 60,
         "repeat_period_minor": 300, "rounding": "ceil", "max_duration_minutes": None},
        {"id": "weekend", "type": "time_window", "stage": "ADJUST",
         "space_classes": ["standard"], "label": "Weekend $5 off",
         "applies_on": {"kind": "days_of_week", "days": ["sat", "sun"]},
         "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
         "day_span": "any_span",
         "effect": {"kind": "adjust", "direction": "discount",
                    "amount": {"kind": "fixed", "minor": 500},
                    "rounding": "down"}},
    ],
    "decisions": [],
}

SATURDAY = "2026-03-07T10:00:00-05:00"


def _quote(exit_: str):
    return run_quote(
        {"plans": [copy.deepcopy(PLAN)], "entry_at": SATURDAY, "exit_at": exit_,
         "space_class": "standard", "currency": "USD"}
    )


def _discount_line(body: dict) -> dict:
    return next(ln for ln in body["breakdown"] if ln["rule_id"] == "weekend")


@pytest.mark.guarantee("F57")
@pytest.mark.parametrize(
    "exit_", ["2026-03-07T10:00:00-05:00", "2026-03-07T10:59:00-05:00",
              "2026-03-07T11:00:00-05:00"],
)
def test_a_stay_cheaper_than_the_discount_is_priced_at_zero(exit_):
    status, body = _quote(exit_)
    assert status == 200, f"a stay cheaper than the discount was refused: {body}"
    assert body["fee_minor"] == 0
    line = _discount_line(body)
    assert line["delta_minor"] == -300, "the discount takes off the 3.00 charged, no more"
    assert "limited to the 3.00 USD charged" in line["text"], line["text"]
    assert sum(ln["delta_minor"] for ln in body["breakdown"]) == 0


@pytest.mark.guarantee("F57")
@pytest.mark.parametrize(
    "exit_,fee", [("2026-03-07T11:01:00-05:00", 100), ("2026-03-07T12:01:00-05:00", 400)],
)
def test_a_discount_smaller_than_the_charge_is_taken_in_full(exit_, fee):
    """The control on the item above: past the first hour the stay costs more
    than 5.00, so the whole 5.00 comes off and no limit is mentioned."""
    status, body = _quote(exit_)
    assert status == 200, body
    assert body["fee_minor"] == fee
    line = _discount_line(body)
    assert line["delta_minor"] == -500
    assert "limited" not in line["text"], line["text"]


@pytest.mark.guarantee("F57")
def test_every_stay_the_plan_check_probes_is_priced():
    """The plan check reports this plan clean, and now that is true of every
    stay it probes: none is refused at the counter."""
    plan = load_plan(copy.deepcopy(PLAN))
    assert validate_plan(plan) == []
    refused = []
    for stay in probe_stays(plan):
        try:
            quote([plan], stay)
        except Refused as refused_stay:
            codes = [f.code for f in refused_stay.findings]
            refused.append((stay.entry_at.isoformat(), stay.duration_minutes, codes))
    assert refused == []
