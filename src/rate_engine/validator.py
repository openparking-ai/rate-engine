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

#: The reference entry the validator has always used: early enough that an
#: early-bird rule CAN qualify, so the QUALIFY branch is exercised even by a plan
#: that declares no entry limit at all. Kept as one mark among many rather than
#: as THE entry -- being the only one was the defect.
DEFAULT_PROBE_ENTRY_MINUTE = 7 * 60


def _entry_minutes_of_day(plan: Plan) -> set[int]:
    """Every ENTRY time this plan makes interesting, as minutes past local midnight.

    **This is the half that was missing, and it is what let a conflict through.**
    Every probe used to enter at 07:00 and vary only the duration, so two rules
    that both qualify only for an EARLY entry never overlapped in any probe: the
    validator reported a plan clean and the engine then refused a real stay for a
    conflict. A rule that names a time makes that time interesting, and the plan
    is where those times live.
    """
    marks = {DEFAULT_PROBE_ENTRY_MINUTE, 0}  # the original reference, and midnight
    for rule in plan.rules_for_stage(QUALIFY):
        enter_by = rule.params.get("enter_by")
        if enter_by is not None:
            at = enter_by.hour * 60 + enter_by.minute
            # ON the limit and one minute INSIDE it: a rule qualifies at or before
            # `enter_by`, so both of those qualify and the pair is what makes two
            # rules overlap. One minute after is covered by the next rule's marks
            # and by the base entry.
            marks.update({at, at - 1})
    return {m for m in marks if 0 <= m < 24 * 60}


def _duration_marks(plan: Plan, entry_minute: int) -> set[int]:
    """Every stay LENGTH that is interesting from this particular entry time.

    Computed per entry rather than once, because an exit limit is a wall-clock
    time: how long a stay has to be to land on 17:00 depends on when it started.
    The old code derived these against a single fixed entry, which is the same
    defect as the fixed entry itself, one level down.
    """
    marks: set[int] = {0, 1}
    for rule in plan.rules_for_stage(ACCUMULATE):
        for key in ("first_period_minutes", "repeat_period_minutes"):
            length = rule.params.get(key)
            if length:
                marks.update({length - 1, length, length + 1})
        ceiling = rule.params.get("max_duration_minutes")
        if ceiling:
            marks.update({ceiling - 1, ceiling, ceiling + 1})
        else:
            # Unbounded rules still need a long probe, or a cap's multi-day
            # branch is never entered by any stay the validator tries.
            marks.add(3 * 24 * 60)

    for rule in plan.rules_for_stage(QUALIFY):
        exit_by = rule.params.get("exit_by")
        if exit_by is not None:
            limit = (exit_by.hour * 60 + exit_by.minute) - entry_minute
            if limit > 0:
                marks.update({limit - 1, limit, limit + 1})

    # Always probe across a local midnight and across more than one day, because
    # a day-boundary branch that no probe reaches is a branch the validator
    # cannot report on.
    marks.update({17 * 60, 25 * 60, 49 * 60})
    return {m for m in marks if m >= 0}


def probe_stays(plan: Plan) -> list[Stay]:
    """Stays either side of every boundary this plan DECLARES.

    Two axes, both read out of the rules: when the stay ENTERS and how long it
    lasts. Neither is a written list of scenarios -- a fixed list can only find
    the gaps whoever wrote it already thought of -- and neither is a search: the
    probes are the plan's own stated times, each side of each.

    **What this does NOT claim.** It is not exhaustive over all possible stays,
    and no bounded probe set could be. It is exhaustive over the boundaries the
    plan STATES, which is the class of conflict a rule can express in A1: every
    qualification a rule makes turns on a time it declares or a duration it
    declares. `validate_plan`'s docstring and the README say exactly that and no
    more -- see the limit recorded there.
    """
    day = datetime(2026, 3, 3, 0, 0, tzinfo=plan.timezone)  # a Tuesday, local midnight

    stays: list[Stay] = []
    for space_class in plan.space_classes:
        for entry_minute in sorted(_entry_minutes_of_day(plan)):
            entry_at = day + timedelta(minutes=entry_minute)
            for minutes in sorted(_duration_marks(plan, entry_minute)):
                stays.append(
                    Stay(
                        entry_at=entry_at,
                        exit_at=entry_at + timedelta(minutes=minutes),
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
