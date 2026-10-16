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

**What the limit costs, pinned rather than left out.** A fixed INCREASE is added
in full, so a fixed discount larger than the charge, listed before an increase,
no longer takes its excess off it. The owner's admin lists specials in
`adjust_order` in the order he typed them: "Weekend $5 off" then "Event fee $4"
on a 60-minute Saturday stay at $3 was 3 - 5 + 4 = 2.00 and is 0 + 4 = 4.00;
the other way round it is 7 - 5 = 2.00 on both. The first version of this file
said nothing about it, and the contract said no correction raised a fee. Which
semantics the owner wants is put to him in the batch's receipt; this pins what
ships.

**And a fixed discount never ADDS money.** `min` alone limited "5.00 off" to a
total already below zero -- a 150% discount gets it there -- so the line took off
minus 1.50, and a stay the engine refused as a negative fee was priced at zero
under a line contradicting itself. The limit is floored at nothing.

`scripts/fail_controls.py` removes the limit, removes the floor, removes the
words that say it was applied, and limits a fixed increase too, and requires
this file to go red each time.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote
from rate_engine.engine import make_stay, quote
from rate_engine.findings import Refused
from rate_engine.plan import load_plan, parse_instant
from rate_engine.rules import time_window
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


def _quote(exit_: str, plan: dict | None = None):
    return run_quote(
        {"plans": [copy.deepcopy(plan or PLAN)], "entry_at": SATURDAY, "exit_at": exit_,
         "space_class": "standard", "currency": "USD"}
    )


def _weekend_adjust(id_: str, label: str, direction: str, amount: dict) -> dict:
    """A weekend ADJUST shaped like the plan's own, as the admin writes one."""
    return {"id": id_, "type": "time_window", "stage": "ADJUST",
            "space_classes": ["standard"], "label": label,
            "applies_on": {"kind": "days_of_week", "days": ["sat", "sun"]},
            "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
            "day_span": "any_span",
            "effect": {"kind": "adjust", "direction": direction, "amount": amount,
                       "rounding": "down"}}


EVENT_FEE = _weekend_adjust(
    "event", "Event fee $4", "increase", {"kind": "fixed", "minor": 400}
)


def _with(*adjusts: dict, order: list[str]) -> dict:
    plan = copy.deepcopy(PLAN)
    plan["rules"] += [copy.deepcopy(a) for a in adjusts]
    plan["adjust_order"] = order
    return plan


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


# --- what the limit does to an increase after it --------------------------


@pytest.mark.guarantee("F57")
@pytest.mark.parametrize(
    "order,fee,weekend_delta,limited",
    [
        # Listed discount first, as the admin writes it when the owner types
        # "Weekend $5 off" above "Event fee $4": the discount stops at the 3.00
        # charged and the 4.00 is added in full. It was 3 - 5 + 4 = 2.00.
        (["weekend", "event"], 400, -300, True),
        # Listed increase first: 3 + 4 = 7.00, and the whole 5.00 comes off.
        (["event", "weekend"], 200, -500, False),
    ],
)
def test_a_fixed_discount_listed_before_an_increase_no_longer_reduces_it(
    order, fee, weekend_delta, limited
):
    status, body = _quote("2026-03-07T11:00:00-05:00", _with(EVENT_FEE, order=order))
    assert status == 200, body
    assert body["fee_minor"] == fee
    weekend = _discount_line(body)
    assert weekend["delta_minor"] == weekend_delta
    assert ("limited to the 3.00 USD charged" in weekend["text"]) is limited, weekend["text"]
    event = next(ln for ln in body["breakdown"] if ln["rule_id"] == "event")
    assert event["delta_minor"] == 400, "a fixed increase is added in full"
    assert sum(ln["delta_minor"] for ln in body["breakdown"]) == fee


@pytest.mark.guarantee("F57")
def test_a_fixed_increase_larger_than_the_charge_is_added_in_full():
    """The limit is the DISCOUNT's. 10.00 added to a 3.00 stay is 13.00, with
    nothing said about a limit; limiting an increase too would charge 6.00."""
    big_fee = _weekend_adjust(
        "event", "Event fee $10", "increase", {"kind": "fixed", "minor": 1000}
    )
    plan = copy.deepcopy(PLAN)
    plan["rules"] = [r for r in plan["rules"] if r["id"] != "weekend"] + [big_fee]
    status, body = _quote("2026-03-07T11:00:00-05:00", plan)
    assert status == 200, body
    assert body["fee_minor"] == 1300
    event = next(ln for ln in body["breakdown"] if ln["rule_id"] == "event")
    assert event["delta_minor"] == 1000
    assert "limited" not in event["text"], event["text"]


# --- a discount never adds money -------------------------------------------

#: A percentage over 100% loads in the engine (the admin refuses it); it is the
#: only way the running total is below zero when a fixed discount meets it.
OVER_100 = _weekend_adjust(
    "over", "150% off", "discount", {"kind": "percent", "percent_bp": 15000}
)


@pytest.mark.guarantee("F57")
def test_150_percent_then_5_off_is_still_refused_as_a_negative_fee():
    """3.00 less 150% is minus 1.50. The 5.00 off after it takes off nothing --
    not minus 1.50 -- so the total stays below zero and the stay is refused,
    named, as it was before the limit."""
    status, body = _quote("2026-03-07T11:00:00-05:00", _with(OVER_100, order=["over", "weekend"]))
    assert status == 422, f"a negative total was priced: {body}"
    assert [f["code"] for f in body["findings"]] == ["CONFLICT_NEGATIVE_TOTAL"]
    assert "(-150)" in body["findings"][0]["text"], body["findings"][0]["text"]


@pytest.mark.guarantee("F57")
@pytest.mark.parametrize("running_total", [-150, 0])
def test_a_fixed_discount_on_nothing_or_less_takes_off_nothing(running_total):
    """The line itself, on a total at or below zero: no money added, and the
    limit it states is what it took off."""
    plan = load_plan(copy.deepcopy(PLAN))
    rule = next(r for r in plan.rules if r.id == "weekend")
    stay = make_stay(parse_instant(SATURDAY, "entry"),
                     parse_instant("2026-03-07T11:00:00-05:00", "exit"), "standard")
    [line] = time_window.apply(rule, stay, plan, running_total)
    assert line.delta_minor == 0, line.text
    assert "limited to the 0.00 USD charged -- 0.00 USD off" in line.text, line.text
