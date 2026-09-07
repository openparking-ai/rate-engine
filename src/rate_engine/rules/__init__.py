"""The rule registry. Adding a rule type is how this module grows.

"In every state they have a different way to handle" -- so the list of ways to
calculate a fee GROWS, and the property that makes that safe is F7: registering
a new rule type changes no existing plan's answer, fee AND breakdown, byte for
byte. A registry whose members cannot see each other is what buys that; no rule
reads another rule's output, and none of them can reach the running total except
by returning a Line.

**The contract every rule type keeps, and the engine enforces on every quote:**

1. It returns LINES. Not a total, not a delta applied by side effect. A rule
   that changes the fee without saying so in words an operator can read is the
   failure this module exists to prevent, and it is unrepresentable here.
2. It is a pure function of (stay, plan, rule). No clock, no randomness, no
   ambient state -- F5.
3. Its money is integer minor units at every step -- F4.
4. It declares whether it qualified -- **and whether a non-qualifying rule SPEAKS
   depends on its stage.** A QUALIFY rule always returns a line: at delta zero,
   saying which condition failed. That is not politeness: "why didn't early bird
   apply?" is the question operators ask, and a breakdown that answers it only
   when the answer is good news is a breakdown nobody trusts. A rule at any other
   stage that does not cover the stay returns NOTHING -- the engine skips it --
   because a standard-space receipt listing every VIP tier the garage does not
   charge for is noise, not clarity.

   **This item used to say a non-qualifying rule ALWAYS returns a zero line, full
   stop, and that was false for every stage except QUALIFY.** `space_surcharge`
   documented the opposite in its own docstring, so the framework contract and a
   shipped rule type contradicted each other and nothing measured either. The
   distinction is real and worth keeping -- "this special could have applied to
   you and did not" is information; "a tier that was never about your space
   exists" is not -- but it is a rule about STAGES, not a blanket one.
   `tests/test_f22_the_silence_rule_is_per_stage.py` holds both halves.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..stages import STAGES


@dataclass(frozen=True)
class Rule:
    id: str
    type: str
    stage: str
    space_classes: tuple[str, ...]
    #: Type-specific, already validated by the builder that produced it.
    params: dict[str, Any]

    def covers(self, space_class: str) -> bool:
        return space_class in self.space_classes


#: type name -> (stage, builder). The builder validates and returns a Rule; the
#: applier lives beside it and is looked up by type at pipeline time.
RULE_TYPES: dict[str, tuple[str, Callable[..., Rule]]] = {}
RULE_APPLIERS: dict[str, Callable[..., Any]] = {}


def register(
    rule_type: str, stage: str, builder: Callable[..., Rule], applier: Callable[..., Any]
):
    if stage not in STAGES:
        raise ValueError(f"{rule_type} declares stage {stage!r}, which is not a pipeline stage.")
    if rule_type in RULE_TYPES:
        # A module RELOAD re-runs its register() call, and the fail-controls
        # reload rule modules to plant defects in them. Re-registration from the
        # module that already owns the type is that, and is allowed. Registration
        # of the same name from a DIFFERENT module is two rule types fighting over
        # one name, which is the collision this guard exists for.
        incumbent = RULE_TYPES[rule_type][1].__module__
        if incumbent != builder.__module__:
            raise ValueError(
                f"rule type {rule_type!r} is registered by {incumbent} and "
                f"{builder.__module__} is trying to claim it."
            )
    RULE_TYPES[rule_type] = (stage, builder)
    RULE_APPLIERS[rule_type] = applier


def build_rule(raw: object, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan  # circular by design: one refusal type for a plan

    if not isinstance(raw, dict):
        raise InvalidPlan(f"{where} must be an object, got {type(raw).__name__}.")
    if "type" not in raw:
        raise InvalidPlan(f"{where} has no `type`.")
    rule_type = raw["type"]
    if rule_type not in RULE_TYPES:
        raise InvalidPlan(
            f"{where}.type is {rule_type!r}, which this version does not know. "
            f"Registered: {', '.join(sorted(RULE_TYPES))}. An unknown rule type is "
            "rejected rather than skipped -- a skipped rule is a rate an operator "
            "believes is live and that nothing applies."
        )
    _stage, builder = RULE_TYPES[rule_type]
    return builder(raw, plan_space_classes, where)


def common_fields(raw: dict, plan_space_classes: tuple[str, ...], where: str, extra: set[str]):
    """Validate the fields every rule has, and reject unknown keys by name."""
    from ..plan import InvalidPlan

    required = {"id", "type", "stage", "space_classes"} | extra
    present = set(raw)
    missing = sorted(required - present)
    unknown = sorted(present - required)
    if missing:
        raise InvalidPlan(f"{where} is missing required field(s): {', '.join(missing)}.")
    if unknown:
        raise InvalidPlan(
            f"{where} carries key(s) this version does not understand: "
            f"{', '.join(unknown)}. Rejected, not ignored."
        )

    rule_id = raw["id"]
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise InvalidPlan(f"{where}.id must be a non-empty string.")

    declared_stage, _builder = RULE_TYPES[raw["type"]]
    if raw["stage"] != declared_stage:
        raise InvalidPlan(
            f"{where}.stage is {raw['stage']!r} but rule type {raw['type']!r} runs at "
            f"{declared_stage}. The stage is stated in the plan so the document is "
            "readable on its own, and checked here so the two cannot disagree."
        )

    space_classes = raw["space_classes"]
    if (
        not isinstance(space_classes, list)
        or not space_classes
        or not all(isinstance(s, str) for s in space_classes)
    ):
        raise InvalidPlan(f"{where}.space_classes must be a non-empty list of strings.")
    unknown_classes = sorted(set(space_classes) - set(plan_space_classes))
    if unknown_classes:
        raise InvalidPlan(
            f"{where}.space_classes names {', '.join(unknown_classes)}, which the plan "
            "does not declare in its own space_classes."
        )
    return rule_id, tuple(space_classes)
