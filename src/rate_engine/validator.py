"""`validate-plan`: every gap and every conflict, before a stay ever arrives.

Same mechanism as the engine's refusal -- literally the same two functions,
``engine.find_gaps`` and ``engine.find_conflicts`` -- run over a matrix of probe
stays instead of one real one. That is what makes the promise in R5 structural: a
gap the validator reports and a gap the engine refuses on are the same object
with the same identifier, because there is one implementation and the validator
is the thing calling it repeatedly.

**The probe matrix is DERIVED from the plan, not written down.** A fixed list of
scenarios can only find the gaps whoever wrote the list already thought of. So
the probes are built from the plan's own thresholds -- every rule's period
lengths, every stated ceiling, every early-bird limit -- with a stay either side
of each. A plan whose ceiling is 24 hours gets probed at 24h and at 24h+1m
whatever those numbers are, because they are read out of the rules.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .engine import Stay, find_conflicts, find_gaps
from .findings import Finding
from .plan import Plan
from .stages import ACCUMULATE, QUALIFY


def probe_stays(plan: Plan) -> list[Stay]:
    """Stays either side of every threshold this plan actually branches on."""
    # A reference entry that is early enough for an early-bird rule to be able to
    # qualify, so the QUALIFY branch is genuinely exercised rather than being
    # skipped for every probe.
    base = datetime(2026, 3, 3, 7, 0, tzinfo=plan.timezone)  # a Tuesday, 07:00 local

    minute_marks: set[int] = {0, 1}
    for rule in plan.rules_for_stage(ACCUMULATE):
        for key in ("first_period_minutes", "repeat_period_minutes"):
            length = rule.params.get(key)
            if length:
                minute_marks.update({length - 1, length, length + 1})
        ceiling = rule.params.get("max_duration_minutes")
        if ceiling:
            minute_marks.update({ceiling - 1, ceiling, ceiling + 1})
        else:
            # Unbounded rules still need a long probe, or a cap's multi-day
            # branch is never entered by any stay the validator tries.
            minute_marks.add(3 * 24 * 60)

    for rule in plan.rules_for_stage(QUALIFY):
        exit_by = rule.params.get("exit_by")
        if exit_by is not None:
            limit = (exit_by.hour * 60 + exit_by.minute) - (base.hour * 60 + base.minute)
            if limit > 0:
                minute_marks.update({limit - 1, limit, limit + 1})

    # Always probe across a local midnight and across more than one day, because
    # a day-boundary branch that no probe reaches is a branch the validator
    # cannot report on.
    minute_marks.update({17 * 60, 25 * 60, 49 * 60})

    stays: list[Stay] = []
    for space_class in plan.space_classes:
        for minutes in sorted(m for m in minute_marks if m >= 0):
            stays.append(
                Stay(
                    entry_at=base,
                    exit_at=base + timedelta(minutes=minutes),
                    space_class=space_class,
                )
            )
    return stays


def validate_plan(plan: Plan) -> list[Finding]:
    """Every distinct gap and conflict, deduplicated by (code, rule_ids).

    Deduplicated by identifier rather than by sentence: the same gap found at
    three probe durations says a slightly different number each time, and an
    owner should be asked about it once.
    """
    seen: dict[tuple[str, tuple[str, ...]], Finding] = {}
    for stay in probe_stays(plan):
        for finding in find_gaps(plan, stay) + find_conflicts(plan, stay):
            seen.setdefault((finding.code, finding.rule_ids), finding)
    return [seen[key] for key in sorted(seen)]


def undecided(plan: Plan) -> list[Finding]:
    """The findings the owner has not recorded a decision for.

    A decision is matched on the finding's CODE, which is why the codes live in
    one registry. Substring-matching a decision against a sentence would let a
    reworded message quietly un-decide a gap an owner had already settled.
    """
    decided = {d["code"] for d in plan.decisions}
    return [f for f in validate_plan(plan) if f.code not in decided]
