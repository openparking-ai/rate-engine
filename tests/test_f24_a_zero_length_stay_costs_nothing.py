"""F24 -- a stay of no length costs nothing, and one second is priced as a minute.

Gokhan, 2026-11-07: **"there is always a grace period. 0 means $0. 1 means round
up."** So a car that enters and leaves in the same instant pays $0, with or without
a grace period in the plan, and the receipt says why. A stay of one second is one
minute here (`Stay.duration_minutes` rounds UP) and is priced from the first period
like any other stay past grace, so the line between $0 and the first period is the
line between no time and some.

This replaces the decision of 2026-09-07, under which a zero-length stay paid the
first period and said so in the contract with the divergence from the platform's
older fee code, which returned zero. The two now agree.

What it does NOT change: a negative stay (exit before entry) is still REFUSED as a
caller bug, and a stay the plan cannot price at all (an undeclared space class, no
rule covering the class) is still refused for that, zero-length or not -- the
zero-length rule is decided after everything that refuses has had its say.

`scripts/fail_controls.py` takes the rule out and requires this file to go red.
"""

from __future__ import annotations

import copy
import pathlib

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import run_quote


def _quote(entry: str, exit_: str, plan: dict | None = None, space_class: str = "standard"):
    return run_quote(
        {
            "plans": [copy.deepcopy(plan or DOWNTOWN_V2)], "entry_at": entry,
            "exit_at": exit_, "space_class": space_class, "currency": "USD",
        }
    )


@pytest.mark.guarantee("F24")
def test_entry_equals_exit_costs_nothing_and_the_receipt_says_why():
    status, body = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:14:00-05:00")
    assert status == 200
    assert body["fee_minor"] == 0
    assert body["breakdown"][0]["text"].startswith("Entered 09:14 Tue 03 Mar, 0 minutes")
    zero = [line for line in body["breakdown"] if line["code"] == "zero_length_stay"]
    assert len(zero) == 1 and zero[0]["delta_minor"] == 0
    assert "no charge" in zero[0]["text"]
    assert sum(line["delta_minor"] for line in body["breakdown"]) == 0


@pytest.mark.guarantee("F24")
def test_no_rule_is_asked_so_no_surcharge_cap_or_adjustment_is_added():
    """A VIP space under a plan with a per-stay surcharge still costs nothing for a
    stay of no length: free means free, as it does for grace."""
    status, body = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:14:00-05:00",
                          space_class="vip")
    assert status == 200 and body["fee_minor"] == 0
    assert [line["code"] for line in body["breakdown"]] == ["stay", "zero_length_stay"]


@pytest.mark.guarantee("F24")
def test_one_second_is_one_minute_and_pays_the_first_period():
    zero = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:14:00-05:00")[1]
    one_second = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:14:01-05:00")[1]
    one_minute = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:15:00-05:00")[1]
    fifty_nine = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T10:13:00-05:00")[1]
    assert zero["fee_minor"] == 0
    assert one_second["fee_minor"] == one_minute["fee_minor"] == fifty_nine["fee_minor"] == 800


@pytest.mark.guarantee("F24")
def test_a_NEGATIVE_stay_is_a_different_case_and_is_REFUSED():
    """Pricing it at zero would hide a caller bug. This is not the zero-length
    decision and must not be folded into it.

    It comes back as a named 400, not an exception -- that is X1's boundary fix,
    and asserting `pytest.raises` here would re-assert the escape X1 removed.
    """
    status, body = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:13:00-05:00")
    assert status == 400
    assert body["invalid"] is True
    assert "is before entry_at" in body["error"]


@pytest.mark.guarantee("F24")
def test_a_stay_the_plan_cannot_price_is_still_refused_when_it_is_zero_length():
    """The zero-length rule is not a way round a gap: an undeclared space class is
    refused for that, as it is at any length."""
    status, body = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:14:00-05:00",
                          space_class="no-such-class")
    assert status == 422
    assert any(f["code"] == "GAP_UNDECLARED_SPACE_CLASS" for f in body["findings"])


def test_the_DECISION_IS_PUBLISHED_where_an_integrator_reads():
    """The control on the documentation half. The behaviour was decided in a chat and
    must not live only there: if the published paragraph is deleted or reworded away
    this goes red, keyed on the CLAIM, not on one phrasing."""
    contract = (pathlib.Path(__file__).resolve().parent.parent / "docs" / "CONTRACT.md")
    text = " ".join(contract.read_text().split()).lower()
    assert "a stay of zero length costs nothing" in text, (
        "docs/CONTRACT.md no longer publishes the zero-length decision"
    )
    assert "one second" in text and "first period" in text, (
        "the published decision no longer says where the zero ends"
    )
