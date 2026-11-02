"""OP-6-3 -- a quote does a bounded amount of work, and refuses past it.

A quote prices the stay once for each way it can be priced (F63, F64), and on
every pass each daily cap walks the stay a day at a time while each weekly cap
walks every daily cap's days again inside each of its weeks. So the work was
ways x daily caps x weekly caps x days, and nothing bounded any of the first
three: a few hundred specials beside eight daily and eight weekly caps on a
90-day stay ran for tens of seconds.

Now a plan holds at most `MAX_CAP_RULES_PER_PLAN` caps, and the work is counted
before any way is priced; a stay over `MAX_QUOTE_WORK` is refused,
`GAP_QUOTE_OVER_WORK_BUDGET`, nothing guessed.
"""

from __future__ import annotations

import copy
import signal
import time
from contextlib import contextmanager

import pytest

from rate_engine import engine, limits
from rate_engine.contract import run_quote
from rate_engine.plan import InvalidPlan, load_plan
from test_f64_a_quote_prices_each_way_once_and_asks_nothing_per_pair import (
    DAILY,
    ENTRY,
    EXIT,
    HOURLY,
    WEEKLY,
    _flat,
    _plan,
    _stay,
    _weekend_flat,
)

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _caps(daily: int, weekly: int) -> list[dict]:
    caps = [dict(copy.deepcopy(DAILY), id=f"daily-{i}", max_minor=3000 + i) for i in range(daily)]
    caps += [
        dict(copy.deepcopy(WEEKLY), id=f"weekly-{i}", max_minor=10_000 + i,
             week_starts_on=DAYS[i % 7])
        for i in range(weekly)
    ]
    return caps


@contextmanager
def _within(seconds: float):
    def expired(signum, frame):
        raise AssertionError(f"ran past {seconds} s")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _request(document: dict) -> dict:
    return {"plans": [document], "entry_at": ENTRY, "exit_at": EXIT,
            "space_class": "standard", "currency": "USD"}


@pytest.mark.guarantee("F67")
def test_many_ways_beside_many_caps_are_refused_quickly_and_by_name():
    document = _plan([HOURLY] + _caps(8, 8) + [_flat(i) for i in range(300)])
    started = time.perf_counter()
    with _within(3.0):
        status, body = run_quote(_request(document))
    took = time.perf_counter() - started
    assert status == 422, body
    assert [f["code"] for f in body["findings"]] == ["GAP_QUOTE_OVER_WORK_BUDGET"]
    assert str(limits.MAX_QUOTE_WORK) in body["findings"][0]["text"]
    assert took < 1.0, f"refusing took {took:.2f} s"


@pytest.mark.guarantee("F67")
def test_a_plan_with_more_caps_than_the_limit_does_not_load():
    document = _plan([HOURLY] + _caps(limits.MAX_CAP_RULES_PER_PLAN, 1))
    with pytest.raises(InvalidPlan, match="CAP rules") as refused:
        load_plan(document)
    assert refused.value.code == "INVALID_PLAN_TOO_LARGE"


def test_the_largest_stress_plan_the_tests_price_is_well_inside_the_budget():
    """F64's 400 qualifying specials beside 400 that do not, a daily and a weekly
    cap, on the longest stay priced."""
    from rate_engine.engine import _Qualified, quote_work

    plan = load_plan(_plan([HOURLY, DAILY, WEEKLY] + [_flat(i) for i in range(400)]
                           + [_weekend_flat(i) for i in range(400)]))
    stay = _stay()
    work = quote_work(plan, stay, _Qualified(plan, stay))
    assert work * 1.25 < limits.MAX_QUOTE_WORK, work


def test_the_count_is_never_less_than_the_passes_made(monkeypatch):
    """An upper bound: the passes `_the_cheapest_way` makes are counted in it."""
    from rate_engine.engine import _Qualified, quote_work

    plan = load_plan(_plan([HOURLY, DAILY, WEEKLY] + [_flat(i) for i in range(20)]))
    stay = _stay()
    passes = 0
    real = engine._priced

    def counted(*args, **kwargs):
        nonlocal passes
        passes += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, "_priced", counted)
    engine.quote([plan], stay)
    assert passes * len(plan.rules) <= quote_work(plan, stay, _Qualified(plan, stay))


#: The time the slowest quote just inside the budget may take. About 0.6 s on the
#: machine that measured it; the margin is for a slower CI runner.
UNDER_BUDGET_SECONDS = 2.0


def _largest_inside_the_budget(daily: int, weekly: int):
    """The plan with these caps and the most specials whose quote still fits the
    budget, and the same plan with one special more."""
    from rate_engine.engine import _Qualified, quote_work

    def plan(n):
        return load_plan(_plan([HOURLY] + _caps(daily, weekly) + [_flat(i) for i in range(n)]))

    stay = _stay()
    # As many specials as a plan may hold, less one so the plan one over still loads;
    # every shape here runs out of budget before that.
    low, high = 0, limits.MAX_RULES_PER_PLAN - 2 - daily - weekly
    while low < high:
        mid = (low + high + 1) // 2
        candidate = plan(mid)
        if quote_work(candidate, stay, _Qualified(candidate, stay)) <= limits.MAX_QUOTE_WORK:
            low = mid
        else:
            high = mid - 1
    return plan(low), plan(low + 1)


@pytest.mark.guarantee("F67")
@pytest.mark.parametrize("daily, weekly", [(8, 8), (1, 15), (16, 0), (0, 0)])
def test_the_slowest_quote_inside_the_budget_is_priced_quickly(daily, weekly):
    """The review's shape first: eight daily and eight weekly caps, which with each
    day of a cap's walk counted as one rule read fit the budget with 259 specials
    and took about 4 s a quote."""
    inside, over = _largest_inside_the_budget(daily, weekly)
    stay = _stay()
    started = time.perf_counter()
    with _within(UNDER_BUDGET_SECONDS + 1.0):
        engine.quote([inside], stay)
    took = time.perf_counter() - started
    assert took < UNDER_BUDGET_SECONDS, f"{daily}+{weekly} caps: {took:.2f} s inside the budget"
    with pytest.raises(engine.Refused) as refused:
        engine.quote([over], stay)
    assert [f.code for f in refused.value.findings] == ["GAP_QUOTE_OVER_WORK_BUDGET"]
