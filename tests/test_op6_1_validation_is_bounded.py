"""OP-6-1 -- `validate-plan` does a bounded amount of work, and refuses past it.

The probe matrix is every space class x every date x every entry time x every
stay length the rules name x every occupancy mark, and every probe asks every
rule. Nothing bounded it: a plan of a hundred event-day specials, each with its
own hours, asked for about 400,000 probes, all built into one list before the
first ran. On the machine that measured it, twenty such rules already took 6.6 s
to validate; a hundred ran out of memory.

Now the work is counted before a probe is built and a plan over
`MAX_VALIDATION_WORK` is refused, 400, `INVALID_PLAN_TOO_LARGE`; within it the
probes are made one at a time, the run is abandoned at a deadline, the findings
are computed once a request rather than twice, and over HTTP only
`MAX_CONCURRENT_VALIDATIONS` run at once. A plan also cannot hold more rules,
space classes or dates than `limits` allows.
"""

from __future__ import annotations

import copy
import json
import signal
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import date, timedelta

import pytest

from fixtures import PLANS_DIR
from rate_engine import contract, limits, service, validator
from rate_engine.contract import run_validate
from rate_engine.plan import InvalidPlan, load_plan

BASE = json.loads((PLANS_DIR / "simple_no_gaps.json").read_text())


def _window(i: int) -> dict:
    """An event-day special on its own date with its own hours: each one adds a
    date to probe on and four entry times to probe at."""
    hour, minute = divmod(7 * i % 1380 + 30, 60)
    return {
        "id": f"event-{i:03d}", "type": "time_window", "stage": "QUALIFY",
        "space_classes": ["standard"], "label": f"Event {i}",
        "applies_on": {"kind": "dates", "dates": [f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}"]},
        "enter_from": f"{hour:02d}:{minute:02d}",
        "enter_by": f"{min(hour + 1, 23):02d}:{minute:02d}",
        "exit_by": "23:59", "day_span": "same_day",
        "effect": {"kind": "flat", "price_minor": 1000 + i},
    }


def _days(first: int, count: int) -> list[str]:
    return [(date(2026, 1, 1) + timedelta(days=first + i)).isoformat() for i in range(count)]


def _plan_with_windows(n: int) -> dict:
    plan = copy.deepcopy(BASE)
    plan["rules"] += [_window(i) for i in range(n)]
    return plan


@contextmanager
def _within(seconds: float):
    """Stop the code inside after `seconds`, so the unbounded version fails the
    test instead of running for minutes."""

    def expired(signum, frame):
        raise AssertionError(f"ran past {seconds} s")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.guarantee("F65")
def test_a_plan_of_a_hundred_event_specials_is_refused_quickly_and_by_name():
    document = _plan_with_windows(100)
    started = time.perf_counter()
    with _within(2.0):
        status, body = run_validate({"plan": document})
    took = time.perf_counter() - started
    assert status == 400, body
    assert body["code"] == "INVALID_PLAN_TOO_LARGE"
    assert str(limits.MAX_VALIDATION_WORK) in body["error"]
    assert took < 1.0, f"refusing took {took:.2f} s"


def test_the_same_plan_is_still_priced_by_a_quote():
    """The budget is the validator's: a quote probes nothing, so it still prices."""
    status, body = contract.run_quote({
        "plans": [_plan_with_windows(100)], "entry_at": "2026-03-03T09:00:00-05:00",
        "exit_at": "2026-03-03T11:00:00-05:00", "space_class": "standard", "currency": "USD",
    })
    assert status == 200, body


@pytest.mark.parametrize("name", sorted(p.name for p in PLANS_DIR.glob("*.json")))
def test_every_fixture_plan_is_far_inside_the_budget(name):
    plan = load_plan(json.loads((PLANS_DIR / name).read_text()))
    work = validator.probe_work(plan)
    assert work == len(validator.probe_stays(plan)) * len(plan.rules)
    assert work * 10 < limits.MAX_VALIDATION_WORK, (name, work)


@pytest.mark.guarantee("F65")
def test_the_work_is_counted_without_building_a_probe(monkeypatch):
    def built(*args, **kwargs):
        raise AssertionError("a probe stay was built for a plan over the budget")

    monkeypatch.setattr(validator, "Stay", built)
    with pytest.raises(InvalidPlan) as refused:
        validator.validate_plan(load_plan(_plan_with_windows(100)))
    assert refused.value.code == "INVALID_PLAN_TOO_LARGE"


def test_the_probes_are_made_one_at_a_time_and_in_the_same_order():
    plan = load_plan(_plan_with_windows(3))
    lazy = validator.iter_probe_stays(plan)
    assert iter(lazy) is lazy, "a generator, not a list"
    assert list(lazy) == validator.probe_stays(plan)


@pytest.mark.guarantee("F65")
def test_a_request_runs_the_probes_once(monkeypatch):
    plan_document = json.loads((PLANS_DIR / "lot_c_with_gaps.json").read_text())
    plan = load_plan(plan_document)
    probes = len(validator.probe_stays(plan))
    calls = 0
    real = validator.find_gaps

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(validator, "find_gaps", counted)
    status, body = run_validate({"plan": plan_document})
    assert status == 200, body
    assert body["outstanding"] + body["settled"] == len(body["findings"])
    assert calls == probes, f"{calls} probes run for {probes} probe stays"


def test_a_validation_past_its_deadline_is_a_503(monkeypatch):
    monkeypatch.setattr(contract, "VALIDATION_DEADLINE_SECONDS", -1.0)
    status, body = run_validate({"plan": BASE})
    assert status == 503, body
    assert "deadline" in body["error"]


@pytest.mark.guarantee("F65")
@pytest.mark.parametrize(
    "field, build",
    [
        ("rules", lambda p: p["rules"].extend(
            dict(_window(i), id=f"many-{i}") for i in range(limits.MAX_RULES_PER_PLAN))),
        ("space_classes", lambda p: p.update(
            space_classes=[f"class-{i}" for i in range(limits.MAX_SPACE_CLASSES + 1)])),
        ("applies_on.dates", lambda p: p["rules"].append(dict(
            _window(0), applies_on={"kind": "dates",
                                    "dates": _days(0, limits.MAX_DATES_PER_RULE + 1)}))),
    ],
)
def test_a_plan_over_a_load_limit_is_refused_by_name(field, build):
    document = copy.deepcopy(BASE)
    build(document)
    with pytest.raises(InvalidPlan) as refused:
        load_plan(document)
    assert refused.value.code == "INVALID_PLAN_TOO_LARGE"
    assert field.split(".")[-1] in str(refused.value)


def test_the_dates_across_a_plan_are_bounded_too():
    document = copy.deepcopy(BASE)
    per_rule = limits.MAX_DATES_PER_RULE
    rules_needed = limits.MAX_DATES_PER_PLAN // per_rule + 1
    for r in range(rules_needed):
        days = _days(r * per_rule, per_rule)
        document["rules"].append(dict(_window(r), applies_on={"kind": "dates", "dates": days}))
    with pytest.raises(InvalidPlan, match="dates across its rules") as refused:
        load_plan(document)
    assert refused.value.code == "INVALID_PLAN_TOO_LARGE"


@pytest.mark.guarantee("F65")
def test_only_so_many_validations_run_at_once_over_http(monkeypatch):
    monkeypatch.setattr(service, "_VALIDATIONS", threading.BoundedSemaphore(1))
    service._VALIDATIONS.acquire()  # one validation already running
    server = service.make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/validate-plan"
        request = urllib.request.Request(
            url, data=json.dumps({"plan": BASE}).encode(), method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as answered:
            urllib.request.urlopen(request, timeout=5)
        assert answered.value.code == 503
        assert "try again" in json.loads(answered.value.read())["error"]

        service._VALIDATIONS.release()
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
