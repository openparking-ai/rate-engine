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

from _quote_shapes import Shape, largest_inside_the_budget, plan, stay
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
    assert work < limits.MAX_QUOTE_WORK, work


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


#: The time the slowest quote just inside the budget may take: about 1 s, twice
#: over for a slower CI runner. On the machine that measured the budget the
#: slowest of all 156 shapes `_quote_shapes.grid()` generates took 0.60 s (best
#: of three), and every shape below at most that.
UNDER_BUDGET_SECONDS = 2.0

#: Shapes from the generated search, each priced at the largest plan the budget
#: lets through. The six the re-review of 8ba1aae timed first, then the slowest
#: the search found, then the fill rule and a cap mix of each kind.
SHAPES = [
    # The re-review's six: 10.8 s, 7.1 s, 3.8 s, 3.1 s, 1.5 s and 1.4 s there.
    Shape("discount", "2h", ways=1000),
    Shape("discount", "2h", ways=400),
    Shape("discount", "2h", ways=200),
    Shape("surcharge", "2h", ways=1000),
    Shape("rate_special", "1d", 0, 16),
    Shape("rate", "1d", 1, 15),
    # The slowest the search found.
    Shape("rate", "2h", 0, 16),
    Shape("flat", "7d", 0, 16),
    Shape("flat", "90d", 4, 4),
    Shape("rate_special", "90d", 1, 15),
    Shape("surcharge", "90d", 1, 1, ways=400),
    Shape("unqualified", "90d", 1, 1, ways=50),
    # The first review's shape, the fill rule, and no caps at all.
    Shape("flat", "90d", 8, 8),
    Shape("discount", "2h", ways=50, fill=True),
    Shape("flat", "2h"),
]


@pytest.mark.guarantee("F67")
@pytest.mark.parametrize("shape", SHAPES, ids=str)
def test_the_slowest_quote_inside_the_budget_is_priced_quickly(shape, monkeypatch):
    """Timed with the deadline lifted, so the test sees how long the work takes
    rather than the deadline refusing it."""
    monkeypatch.setattr(engine, "QUOTE_DEADLINE_SECONDS", 1e9)
    inside, over = largest_inside_the_budget(shape)
    the_stay = stay(shape)
    started = time.perf_counter()
    with _within(UNDER_BUDGET_SECONDS + 1.0):
        engine.quote([inside], the_stay)
    took = time.perf_counter() - started
    assert took < UNDER_BUDGET_SECONDS, f"{shape}: {took:.2f} s inside the budget"
    if len(over.rules) == limits.MAX_RULES_PER_PLAN:
        return  # the rule limit binds before the work budget does, for this shape
    with pytest.raises(engine.Refused) as refused:
        engine.quote([over], the_stay)
    assert [f.code for f in refused.value.findings] == ["GAP_QUOTE_OVER_WORK_BUDGET"]


@pytest.mark.guarantee("F67")
def test_a_quote_past_its_deadline_is_stopped_between_passes_and_told_to_retry(monkeypatch):
    """A deadline already past: the first pass is not begun. It is not a refusal
    of the stay -- the same request may price a moment later on a quieter
    machine -- so the door answers 503 and says try again, never the 422 gap
    that sends a car to an operator."""
    monkeypatch.setattr(engine, "QUOTE_DEADLINE_SECONDS", -1.0)
    shape = Shape("flat", "2h")
    with pytest.raises(engine.QuoteTooLong, match="deadline"):
        engine.quote([load_plan(plan(shape, 3))], stay(shape))
    status, body = run_quote(_request(_plan([HOURLY, _flat(1)])))
    assert status == 503, body
    assert body["retry"] is True and body["retry_after_seconds"] >= 1
    assert "try again" in body["error"]
    assert "findings" not in body and "refused" not in body


@pytest.mark.guarantee("F67")
def test_over_http_a_stopped_quote_carries_retry_after(monkeypatch):
    import json
    import threading
    import urllib.error
    import urllib.request

    from rate_engine import service

    monkeypatch.setattr(engine, "QUOTE_DEADLINE_SECONDS", -1.0)
    server = service.make_server(port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/quote",
            data=json.dumps(_request(_plan([HOURLY, _flat(1)]))).encode(), method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as answered:
            urllib.request.urlopen(request, timeout=10)
        assert answered.value.code == 503
        assert answered.value.headers["Retry-After"] == "1"
        assert json.loads(answered.value.read())["retry"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_the_work_count_refusal_is_still_a_422_and_never_retried():
    """Deterministic, so a retry would get the same answer: a 422 gap."""
    inside, over = largest_inside_the_budget(Shape("flat", "2h", 8, 8))
    status, body = run_quote({"plans": [plan(Shape("flat", "2h", 8, 8), len(over.rules) - 17)],
                              "entry_at": "2026-04-06T09:00:00-04:00",
                              "exit_at": "2026-04-06T11:00:00-04:00",
                              "space_class": "standard", "currency": "USD"})
    assert status == 422, body
    assert body["findings"][0]["code"] == "GAP_QUOTE_OVER_WORK_BUDGET"
    assert "retry" not in body


def test_the_deadline_does_not_touch_an_ordinary_quote():
    shape = Shape("flat", "2h")
    assert engine.quote([load_plan(plan(shape, 3))], stay(shape)).fee_minor > 0


def test_the_cli_says_a_stopped_quote_was_not_priced_and_to_try_again(monkeypatch, capsys):
    from fixtures import PLANS_DIR
    from rate_engine.cli import main

    monkeypatch.setattr(engine, "QUOTE_DEADLINE_SECONDS", -1.0)
    code = main(["quote", "--plan", str(PLANS_DIR / "downtown_v2.json"),
                 "--entry", "2026-03-03T09:14:00-05:00", "--exit", "2026-03-03T18:40:00-05:00",
                 "--space-class", "standard", "--currency", "USD"])
    out = capsys.readouterr().out
    assert code == 1
    assert "not priced, try again" in out and "REFUSED" not in out
