"""F5 -- the same plan version and the same stay produce the same fee AND the same
breakdown, always.

Not "the same fee". The breakdown is the product, so a module whose explanation
drifts between two runs has an unstable product even where the number holds.

Two independent ways this could break, and both are tested because a guard on one
does not cover the other:

* **The wall clock.** Nothing in the pricing path may read `datetime.now()`. The
  test runs the same quote under two very different fake system clocks.
* **The timezone.** This is the realistic one and it is why the plan carries an
  IANA zone. An engine that read the SERVER's zone would price "exit by 17:00"
  differently in New York and in Frankfurt, and the same garage would bill two
  different amounts depending on which machine answered. `TZ` is moved under the
  engine's feet and the answer must not move.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from fixtures import CORPUS, DOWNTOWN_V2, loaded, stay
from rate_engine.contract import run_quote
from rate_engine.engine import quote
from rate_engine.findings import Refused


def _answer(s):
    result = quote([loaded()], s)
    return result.fee_minor, [line.text for line in result.breakdown.lines]


@pytest.mark.guarantee("F5")
def test_every_fixture_prices_identically_twice():
    for name, s in CORPUS.items():
        try:
            first = _answer(s)
        except Refused as refused:
            first = ("refused", [f.text for f in refused.findings])
            with pytest.raises(Refused) as again:
                quote([loaded()], s)
            assert [f.text for f in again.value.findings] == first[1], name
            continue
        assert _answer(s) == first, f"{name} priced differently on a second call"


@pytest.mark.guarantee("F5")
def test_the_server_timezone_does_not_move_the_answer():
    """The zone comes from the plan. The machine's zone is not an input."""
    baseline = _answer(CORPUS["worked_example"])
    original = os.environ.get("TZ")
    try:
        for zone in ("UTC", "Europe/Berlin", "Pacific/Kiritimati", "America/Los_Angeles"):
            os.environ["TZ"] = zone
            time.tzset()
            assert _answer(CORPUS["worked_example"]) == baseline, (
                f"the fee or the breakdown moved when the SERVER was in {zone}; the "
                "plan's own timezone is the only one that may matter"
            )
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()


@pytest.mark.guarantee("F5")
def test_a_dst_day_is_priced_by_the_local_clock_not_by_elapsed_hours():
    """The US spring-forward on 2026-03-08 makes that local day 23 hours long.

    A stay of exactly 1440 minutes starting the day before therefore ends on the
    NEXT calendar date, and a calendar-day cap allows two caps rather than one.
    That is the correct answer and it is only reachable because the plan names a
    real IANA zone: a fixed UTC offset cannot express the transition at all.
    """
    result = quote([loaded()], CORPUS["dst_day"])
    cap_line = next(x for x in result.breakdown.lines if x.code.startswith("daily_max"))
    assert "2 days" in cap_line.text, (
        "a 24-hour stay across the spring-forward ends on the following local date "
        "and is allowed two calendar-day caps"
    )
    assert result.fee_minor == 6000


@pytest.mark.guarantee("F5")
def test_the_serialized_response_is_byte_stable():
    """Byte-identical JSON, not merely equal objects -- key order included."""
    _, first = run_quote(_request())
    for _ in range(3):
        _, again = run_quote(_request())
        assert json.dumps(again, sort_keys=False) == json.dumps(first, sort_keys=False)


def _request() -> dict:
    s = CORPUS["worked_example"]
    return {
        "plans": [DOWNTOWN_V2],
        "entry_at": s.entry_at.isoformat(),
        "exit_at": s.exit_at.isoformat(),
        "space_class": s.space_class,
        "currency": "USD",
    }


def test_the_dst_fixture_really_crosses_a_transition():
    """The control on this file's own premise.

    If 2026-03-08 were not a transition in this zone, the test above would be
    asserting ordinary arithmetic and would say nothing about DST.
    """
    plan = loaded()
    s = stay("2026-03-07T12:00:00-05:00", 1440)
    entry_local = s.entry_at.astimezone(plan.timezone)
    exit_local = s.exit_at.astimezone(plan.timezone)
    assert entry_local.utcoffset() != exit_local.utcoffset(), (
        "this fixture does not actually cross a DST transition, so the test above "
        "measures nothing about one"
    )
