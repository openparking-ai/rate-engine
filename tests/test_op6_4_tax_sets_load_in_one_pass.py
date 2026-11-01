"""OP-6-4 -- a garage's tax sets load in one pass, and are bounded.

`load_tax_sets` refused two sets taking effect at one instant by comparing every
set with every later one: the square of the sets. A statement of a few thousand
sets, well inside the 1 MiB body, took seconds; nothing bounded how many sets, or
how many rules in a set, a statement could hold.

Now the sets are keyed by their instant, which an aware datetime hashes by, so
one pass finds a pair; and `MAX_TAX_SETS` and `MAX_TAX_RULES_PER_SET` bound them.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from rate_engine import limits, tax
from rate_engine.contract import run_validate_tax_sets
from rate_engine.plan import InvalidPlan
from rate_engine.tax import load_tax_sets

START = datetime(2000, 1, 1, tzinfo=UTC)


def _sets(n: int) -> list[dict]:
    return [
        {"effective_from": (START + timedelta(hours=i)).isoformat(), "rules": []}
        for i in range(n)
    ]


def _rule(i: int) -> dict:
    return {"id": f"tax-{i}", "label": f"Tax {i}", "percent_bp": 100,
            "rounding": "nearest", "sequence": i}


@pytest.mark.guarantee("F68")
def test_ten_thousand_sets_are_checked_in_one_pass(monkeypatch):
    """Over the limit, so the limit is lifted to time the check itself."""
    monkeypatch.setattr(tax, "MAX_TAX_SETS", 20_000, raising=False)
    document = _sets(10_000)
    started = time.perf_counter()
    loaded = load_tax_sets(document)
    took = time.perf_counter() - started
    assert len(loaded) == 10_000
    assert took < 1.0, f"{took:.2f} s for 10,000 sets"


@pytest.mark.guarantee("F68")
def test_two_sets_at_one_instant_are_still_refused_both_named():
    document = _sets(5)
    # The same instant as set 1, written in another offset.
    document.append({"effective_from": "1999-12-31T20:00:00-05:00", "rules": []})
    with pytest.raises(InvalidPlan) as refused:
        load_tax_sets(document)
    assert "tax_sets[1] and tax_sets[5] both take effect" in str(refused.value)


@pytest.mark.guarantee("F68")
def test_a_statement_over_the_set_limit_is_refused_quickly_and_by_name():
    document = _sets(limits.MAX_TAX_SETS + 1)
    started = time.perf_counter()
    status, body = run_validate_tax_sets({"tax_sets": document})
    assert time.perf_counter() - started < 0.5
    assert status == 400, body
    assert f"at most {limits.MAX_TAX_SETS}" in body["error"]


def test_a_set_over_the_rule_limit_is_refused_by_name():
    document = [{"effective_from": START.isoformat(),
                 "rules": [_rule(i) for i in range(limits.MAX_TAX_RULES_PER_SET + 1)]}]
    status, body = run_validate_tax_sets({"tax_sets": document})
    assert status == 400, body
    assert "tax_sets[0].rules" in body["error"]
    assert f"at most {limits.MAX_TAX_RULES_PER_SET}" in body["error"]


def test_a_statement_at_the_limits_loads():
    document = _sets(limits.MAX_TAX_SETS)
    document[0]["rules"] = [_rule(i) for i in range(limits.MAX_TAX_RULES_PER_SET)]
    assert len(load_tax_sets(document)) == limits.MAX_TAX_SETS
