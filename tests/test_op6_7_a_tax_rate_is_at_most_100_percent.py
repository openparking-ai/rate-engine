"""OP-6-7 -- a tax rate is at most 100% of the money paid.

A tax rule's `percent_bp` had a floor (one basis point) and no ceiling, so a
rate typed in the wrong unit -- or any number at all -- loaded and taxed a stay
many times over: 1,000,000 bp on 20.00 is a 2,000.00 tax line.

Now a rule over `MAX_TAX_PERCENT_BP`, 10,000 bp, does not load: 400, naming the
field, at both tax doors.
"""

from __future__ import annotations

import pytest

from rate_engine import limits
from rate_engine.contract import run_tax, run_validate_tax_sets
from rate_engine.plan import InvalidPlan, parse_instant
from rate_engine.tax import load_tax_sets, tax_lines


def _sets(bp: int) -> list[dict]:
    return [{"effective_from": "2026-01-01T00:00:00-05:00",
             "rules": [{"id": "city", "label": "City parking tax", "percent_bp": bp,
                        "rounding": "nearest", "sequence": 1}]}]


@pytest.mark.guarantee("F71")
@pytest.mark.parametrize("bp", [limits.MAX_TAX_PERCENT_BP + 1, 1_000_000])
def test_a_rate_over_100_percent_does_not_load(bp):
    with pytest.raises(InvalidPlan, match=r"tax_sets\[0\]\.rules\[0\]\.percent_bp"):
        load_tax_sets(_sets(bp))
    status, body = run_validate_tax_sets({"tax_sets": _sets(bp)})
    assert status == 400, body
    status, body = run_tax({"tax_sets": _sets(bp), "subtotal_minor": 2000,
                            "currency": "USD", "at": "2026-06-01T12:00:00-04:00"})
    assert status == 400, body
    assert "percent_bp" in body["error"]


@pytest.mark.guarantee("F71")
def test_a_rate_of_exactly_100_percent_loads_and_is_taken_in_full():
    sets = load_tax_sets(_sets(limits.MAX_TAX_PERCENT_BP))
    lines = tax_lines(sets, subtotal_minor=2000, currency="USD",
                      at=parse_instant("2026-06-01T12:00:00-04:00", "at"))
    assert [line.delta_minor for line in lines] == [2000]
