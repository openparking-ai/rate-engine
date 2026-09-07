"""The control on the corpus itself: does it hold cases on BOTH sides of every axis?

A fixture is part of the measurement. This test enumerates the threshold
constants OUT OF THE REFERENCE PLAN -- not out of a list somebody typed -- and
requires the corpus to contain a stay strictly below and a stay at or above each
one. A corpus that could only ever exercise one branch would make the whole suite
green while measuring half of it, and nothing else here would notice.
"""

from __future__ import annotations

import pytest

from fixtures import CORPUS, DOWNTOWN_V2, loaded, stay
from rate_engine.engine import quote
from rate_engine.findings import Refused


def _rule(rule_id: str) -> dict:
    return next(r for r in DOWNTOWN_V2["rules"] if r["id"] == rule_id)


def _durations() -> list[int]:
    return [s.duration_minutes for s in CORPUS.values()]


@pytest.mark.parametrize(
    "label,threshold",
    [
        ("increment.first_period_minutes", _rule("hourly")["first_period_minutes"]),
        ("increment.repeat_period_minutes", _rule("hourly")["repeat_period_minutes"]),
        ("increment.max_duration_minutes", _rule("hourly")["max_duration_minutes"]),
    ],
)
def test_the_corpus_straddles_every_duration_threshold(label, threshold):
    durations = _durations()
    below = [d for d in durations if d < threshold]
    at_or_above = [d for d in durations if d >= threshold]
    assert below, f"no fixture is below {label} ({threshold} min); that side is unmeasured"
    assert at_or_above, f"no fixture reaches {label} ({threshold} min); that side is unmeasured"


def test_the_corpus_straddles_the_early_bird_limits():
    """Both conditions, each missed and each met -- F2 is only worth running if so."""
    plan = loaded()
    outcomes = set()
    for s in CORPUS.values():
        if s.space_class != "standard":
            continue
        entry_local = s.entry_at.astimezone(plan.timezone)
        exit_local = s.exit_at.astimezone(plan.timezone)
        outcomes.add(entry_local.time() <= plan.rules[0].params["enter_by"])
        outcomes.add(
            exit_local.date() == entry_local.date()
            and exit_local.time() <= plan.rules[0].params["exit_by"]
        )
    assert outcomes == {True, False}, (
        "every fixture falls on the same side of an early-bird condition, so F2 would "
        "pass without exercising the rule"
    )


def test_the_corpus_straddles_the_cap():
    """Some stays must reach the daily max and some must not."""
    plan = loaded()
    reached, not_reached = [], []
    for name, s in CORPUS.items():
        try:
            result = quote([plan], s)
        except Refused:
            continue
        codes = {line.code for line in result.breakdown.lines}
        (reached if "daily_max.applied" in codes else not_reached).append(name)
    assert reached, "no fixture reaches the daily max; the capping branch is unmeasured"
    assert not_reached, "every fixture is capped; the un-capped branch is unmeasured"


def test_the_corpus_straddles_the_space_class_axis():
    classes = {s.space_class for s in CORPUS.values()}
    assert classes == set(DOWNTOWN_V2["space_classes"]), (
        f"the corpus covers {sorted(classes)} but the plan declares "
        f"{sorted(DOWNTOWN_V2['space_classes'])}; an unexercised class is an "
        "unmeasured surcharge"
    )


def test_the_axes_control_can_fail():
    """The positive control for this file.

    A corpus with one stay in it must make the straddle assertions fail. Without
    this, "both sides are present" is a sentence that has never been tested
    against a corpus where they are not.
    """
    only_short = [stay("2026-03-03T09:14:00-05:00", 30)]
    threshold = _rule("hourly")["first_period_minutes"]
    durations = [s.duration_minutes for s in only_short]
    assert not [d for d in durations if d >= threshold], (
        "the control corpus was supposed to sit entirely below the threshold"
    )
