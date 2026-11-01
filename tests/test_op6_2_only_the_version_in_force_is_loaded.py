"""OP-6-2 -- a quote loads only the plan version in force at entry.

A quote request carries every version of a garage's plan, and every one was
loaded before the one in force was chosen. So a single stored version that no
longer loads -- written for an older schema, carrying a float, or larger than
`limits` allows -- failed every quote for that garage with a 400, although it
priced none of them.

Now each version's `effective_from` is read first, the one in force at entry is
chosen (with every version tied with it, so a tie is still refused), and only
those are loaded.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2, downtown_v1
from rate_engine import limits
from rate_engine.contract import run_quote

ENTRY = "2026-03-03T09:14:00-05:00"
EXIT = "2026-03-03T18:40:00-05:00"


def _request(plans: list) -> dict:
    return {"plans": plans, "entry_at": ENTRY, "exit_at": EXIT,
            "space_class": "standard", "currency": "USD"}


def _unloadable_old_version() -> dict:
    """An old version this engine no longer loads: a float in a money field."""
    old = downtown_v1()
    old["plan_version"] = "downtown-2025-06"
    old["effective_from"] = "2025-06-01T00:00:00-04:00"
    old["rules"][0]["first_period_minor"] = 8.0
    return old


def _oversized_future_version() -> dict:
    future = copy.deepcopy(DOWNTOWN_V2)
    future["plan_version"] = "downtown-2027-01"
    future["effective_from"] = "2027-01-01T00:00:00-05:00"
    future["space_classes"] = [f"class-{i}" for i in range(limits.MAX_SPACE_CLASSES + 1)]
    return future


@pytest.mark.guarantee("F66")
@pytest.mark.parametrize("other", [_unloadable_old_version, _oversized_future_version])
def test_a_version_not_in_force_does_not_fail_the_quote(other):
    alone_status, alone = run_quote(_request([copy.deepcopy(DOWNTOWN_V2)]))
    assert alone_status == 200, alone
    status, body = run_quote(_request([other(), copy.deepcopy(DOWNTOWN_V2)]))
    assert status == 200, body
    assert body == alone, "the version in force prices exactly as it does alone"


@pytest.mark.guarantee("F66")
def test_the_version_in_force_is_still_loaded_and_refused_when_it_does_not_load():
    broken = copy.deepcopy(DOWNTOWN_V2)
    broken["rules"][0]["first_period_minor"] = 8.0
    status, body = run_quote(_request([downtown_v1(), broken]))
    assert status == 400, body
    assert "request.plans[1]" in body["error"]


def test_a_tie_at_the_chosen_instant_is_still_refused_as_ambiguous():
    twin = copy.deepcopy(DOWNTOWN_V2)
    twin["plan_version"] = "downtown-2026-02-twin"
    status, body = run_quote(_request([_unloadable_old_version(), DOWNTOWN_V2, twin]))
    assert status == 422, body
    assert [f["code"] for f in body["findings"]] == ["CONFLICT_AMBIGUOUS_PLAN_SELECTION"]


def test_two_versions_sharing_a_name_are_still_refused():
    old = _unloadable_old_version()
    old["plan_version"] = DOWNTOWN_V2["plan_version"]
    status, body = run_quote(_request([old, DOWNTOWN_V2]))
    assert status == 400, body
    assert "same plan_version" in body["error"]


def test_with_none_in_force_the_refusal_still_names_the_earliest():
    status, body = run_quote(dict(_request([DOWNTOWN_V2, _oversized_future_version()]),
                                  entry_at="2025-01-01T09:00:00-05:00",
                                  exit_at="2025-01-01T10:00:00-05:00"))
    assert status == 422, body
    assert body["findings"][0]["code"] == "GAP_NO_PLAN_IN_FORCE_AT_ENTRY"
    assert "2026-02-01" in body["findings"][0]["text"]


def test_a_version_whose_effective_from_cannot_be_read_is_refused_by_name():
    undated = _unloadable_old_version()
    undated["effective_from"] = "sometime"
    status, body = run_quote(_request([undated, DOWNTOWN_V2]))
    assert status == 400, body
    assert "request.plans[0].effective_from" in body["error"]
