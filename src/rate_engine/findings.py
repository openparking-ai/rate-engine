"""Gaps and conflicts: ONE registry, read by the validator and by the engine.

A gap is a stay the plan cannot price. A conflict is two rules qualifying at one
stage whose resolution the plan does not state. The validator reports them so an
owner can decide; the engine REFUSES on them so a stay is never priced by a
guess. Those are two behaviours of one mechanism, and the whole point of this
file is that they cannot drift apart -- both sides key off the identifiers
below, and ``tests/test_f1_never_guesses.py`` requires every identifier here to
be reachable from a fixture.

**Keyed by identifier, never matched by substring.** A validator that reported
"nothing prices a stay past 24 hours" and an engine that refused with a
differently-worded sentence would agree to a human reader and to no test. The
sentence is for the operator; ``code`` is what anything mechanical uses.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- gap codes -------------------------------------------------------------
#: The stay's space class is not one the plan declares.
GAP_UNDECLARED_SPACE_CLASS = "GAP_UNDECLARED_SPACE_CLASS"
#: Nothing accumulates time for this stay: no ACCUMULATE rule covers the space
#: class, and no QUALIFY special took over the pricing.
GAP_NO_ACCUMULATE_RULE = "GAP_NO_ACCUMULATE_RULE"
#: An ACCUMULATE rule covers the space class but states a maximum duration this
#: stay exceeds. This is §8's own example -- "nothing prices a stay past 24
#: hours" -- and it is expressible only because `max_duration_minutes` is a
#: required field on the rule rather than an assumed infinity.
GAP_STAY_EXCEEDS_MAX_DURATION = "GAP_STAY_EXCEEDS_MAX_DURATION"
#: No plan version was in force at the stay's ENTRY time.
GAP_NO_PLAN_IN_FORCE_AT_ENTRY = "GAP_NO_PLAN_IN_FORCE_AT_ENTRY"

# --- conflict codes --------------------------------------------------------
#: Two or more rules qualify at the same stage. A1 detects and refuses; the
#: resolution modes that would settle it are round A2 (see docs/CONTRACT.md,
#: "What this version does not do").
CONFLICT_MULTIPLE_RULES_AT_STAGE = "CONFLICT_MULTIPLE_RULES_AT_STAGE"
#: Two or more plan versions share the latest `effective_from` at or before the
#: stay's entry, so "the version in force at entry" names more than one document.
#:
#: This was a LIVE DEFECT, not a hypothetical. `select_plan` used
#: `max(in_force, key=...effective_from)`, and `max` returns the FIRST maximal
#: element -- so two versions carrying the same date priced the same car at 300
#: or at 2700 minor units depending only on which the caller happened to put
#: first in a JSON array, with nothing said. Deciding money by the order of a
#: list, silently, is the exact opposite of this project's standing acceptance,
#: and the answer is the same as everywhere else here: refuse, and name both.
CONFLICT_AMBIGUOUS_PLAN_SELECTION = "CONFLICT_AMBIGUOUS_PLAN_SELECTION"

#: The rules between them produced a NEGATIVE total. Refused rather than handing a
#: customer a negative amount.
#:
#: It used to be raised as CONFLICT_MULTIPLE_RULES_AT_STAGE, which is documented
#: exclusively for two rules qualifying at one stage. Nothing was mispriced -- the
#: refusal is correct and the SENTENCE said what really happened -- but the CODE
#: named a cause that had not occurred, and the code is what anything mechanical
#: keys off. A consumer routing on it would have told an operator to settle a
#: resolution order that was not the problem.
#:
#: Unreachable with the four rule types A1 ships: every money field goes through
#: `as_non_negative_minor`, and `daily_max` sets the total to exactly
#: `max_minor x days`, which is >= 0. It is registered anyway because a rule type
#: is the unit of growth here, and the first one that can return a negative Line
#: should meet a named refusal rather than a mislabelled one.
CONFLICT_NEGATIVE_TOTAL = "CONFLICT_NEGATIVE_TOTAL"

# --- fault codes -----------------------------------------------------------
#: A registered rule type returned something that is not a list of Lines.
#:
#: This is a THIRD kind, and it is deliberately not filed under the other two.
#: A gap is a stay the plan cannot price and a conflict is two rules the plan
#: does not order -- both are questions for the OWNER, and both are things
#: `validate-plan` reports. This is neither: it is a defect in a rule type's
#: implementation, which no owner can decide and no plan can fix. Filing it as a
#: conflict would have been the same mistake the negative-fee refusal makes --
#: a refusal whose code names something that did not happen.
FAULT_RULE_RETURNED_NOT_LINES = "FAULT_RULE_RETURNED_NOT_LINES"

GAP_CODES: tuple[str, ...] = (
    GAP_UNDECLARED_SPACE_CLASS,
    GAP_NO_ACCUMULATE_RULE,
    GAP_STAY_EXCEEDS_MAX_DURATION,
    GAP_NO_PLAN_IN_FORCE_AT_ENTRY,
)

CONFLICT_CODES: tuple[str, ...] = (
    CONFLICT_MULTIPLE_RULES_AT_STAGE,
    CONFLICT_AMBIGUOUS_PLAN_SELECTION,
    CONFLICT_NEGATIVE_TOTAL,
)

#: Faults are never produced by the validator: it probes a plan against stays and
#: never runs an applier, so a fault can only arise while actually pricing.
FAULT_CODES: tuple[str, ...] = (FAULT_RULE_RETURNED_NOT_LINES,)

ALL_CODES: tuple[str, ...] = GAP_CODES + CONFLICT_CODES + FAULT_CODES


@dataclass(frozen=True)
class Finding:
    """A gap or a conflict, in a form an owner can act on and a test can key off."""

    code: str
    #: Plain English. What is missing, and what the engine would have had to
    #: invent to answer anyway.
    text: str
    #: The rule ids involved, where the finding is about rules.
    rule_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.code not in ALL_CODES:
            raise ValueError(
                f"{self.code!r} is not a registered finding code. Add it to "
                "findings.py so the validator, the engine and the contract all "
                "learn about it at once."
            )

    @property
    def is_gap(self) -> bool:
        return self.code in GAP_CODES

    @property
    def kind(self) -> str:
        """Which of the three this is, decided by membership rather than by an else.

        It used to be ``"gap" if self.is_gap else "conflict"``, which was true
        while there were exactly two kinds and would have quietly labelled the
        third one a conflict the day it was added. A two-way branch over a
        three-way registry is a wrong answer with no way to notice it.
        """
        for codes, name in (
            (GAP_CODES, "gap"),
            (CONFLICT_CODES, "conflict"),
            (FAULT_CODES, "fault"),
        ):
            if self.code in codes:
                return name
        raise AssertionError(f"{self.code!r} is registered but belongs to no kind.")

    def to_json(self) -> dict[str, object]:
        return {
            "code": self.code,
            "kind": self.kind,
            "text": self.text,
            "rule_ids": list(self.rule_ids),
        }


class Refused(Exception):
    """The engine will not price this stay, and this is exactly what is missing.

    Carries the findings rather than a message, so a caller can show the owner
    the same objects `validate-plan` would have shown them.
    """

    def __init__(self, findings: list[Finding]) -> None:
        self.findings = findings
        joined = " · ".join(f.text for f in findings)
        super().__init__(f"refused, nothing was guessed: {joined}")

    def to_json(self) -> dict[str, object]:
        return {
            "refused": True,
            "findings": [f.to_json() for f in self.findings],
        }
