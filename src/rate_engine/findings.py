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

GAP_CODES: tuple[str, ...] = (
    GAP_UNDECLARED_SPACE_CLASS,
    GAP_NO_ACCUMULATE_RULE,
    GAP_STAY_EXCEEDS_MAX_DURATION,
    GAP_NO_PLAN_IN_FORCE_AT_ENTRY,
)

CONFLICT_CODES: tuple[str, ...] = (CONFLICT_MULTIPLE_RULES_AT_STAGE,)

ALL_CODES: tuple[str, ...] = GAP_CODES + CONFLICT_CODES


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

    def to_json(self) -> dict[str, object]:
        return {
            "code": self.code,
            "kind": "gap" if self.is_gap else "conflict",
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
