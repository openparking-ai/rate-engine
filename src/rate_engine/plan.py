"""The plan document: data, validated on load, never code.

Every field below is REQUIRED. There is no default anywhere in this file, and
that is the module's whole disposition rather than a style preference -- a
default is a pricing decision made by whoever wrote the engine, applied to a
garage whose owner never saw it. Where a plan is silent, the engine refuses and
says which field would have had to be invented.

**An unknown key is REJECTED and named, never ignored.** §2 versions a commercial
contract on the assumption it will GAIN fields, and that assumption is only safe
in one direction: a NEW engine must tolerate an OLD plan, but an OLD engine must
never silently accept a key it does not understand. An operator who adds
`weekend_rate` to a plan running on a version that has no weekend rule has a
garage pricing weekends wrong and a document saying it does not. So a key this
version does not know is a refusal that names the key.

**TIME. The plan states its timezone and every stay is an aware instant.**
This is not incidental. `early_bird` speaks of "enter by 09:00"; `daily_max`
speaks of a day. Both are wall-clock ideas and neither means anything without a
zone -- and a day is 23 or 25 hours across a DST transition, so "24 hours" and
"a calendar day" are genuinely different rules rather than two spellings of one.
The plan names an IANA zone, entry and exit arrive as offset-aware ISO 8601, and
a naive timestamp is refused. `zoneinfo` is standard library, so this costs no
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .currency import is_known
from .money import refuse_non_integer_money
from .rules import RULE_TYPES, Rule, build_rule
from .stages import STAGES


class InvalidPlan(ValueError):
    """The plan document cannot be loaded. The message names the field."""


#: Resolution modes a plan may state for a stage. A1 VALIDATES this field and
#: does not act on it: with one rule type per stage the only way two rules
#: qualify at once is two rules of the same type, and A1 refuses that as a
#: conflict rather than resolving it. The field is required now so that A2 can
#: add the resolution behaviour without changing the shape of a plan that
#: already exists -- see F7, which is the guarantee that makes that safe.
RESOLUTION_MODES: tuple[str, ...] = ("cheapest_wins", "stated_order")

PLAN_KEYS: frozenset[str] = frozenset(
    {
        "plan_version",
        "effective_from",
        "timezone",
        "currency",
        "space_classes",
        "resolution",
        "rules",
        "decisions",
    }
)


def _require_keys(document: dict, keys: frozenset[str], where: str) -> None:
    present = set(document)
    missing = sorted(keys - present)
    unknown = sorted(present - keys)
    if missing:
        raise InvalidPlan(
            f"{where} is missing required field(s): {', '.join(missing)}. "
            "This module has no defaults; a field it cannot read is a pricing "
            "decision nobody made."
        )
    if unknown:
        raise InvalidPlan(
            f"{where} carries key(s) this version does not understand: "
            f"{', '.join(unknown)}. They are REJECTED rather than ignored -- an "
            "ignored key is how a plan an operator believes is live prices "
            "something else. Upgrade the engine, or remove the key."
        )


def parse_instant(value: object, label: str) -> datetime:
    """Parse an offset-aware ISO 8601 instant, or refuse."""
    if not isinstance(value, str):
        raise InvalidPlan(f"{label} must be an ISO 8601 string, got {type(value).__name__}.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidPlan(f"{label} is not ISO 8601: {value!r} ({exc}).") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidPlan(
            f"{label} has no UTC offset ({value!r}). A naive timestamp is refused: it "
            "would be read in whatever zone the server happens to run in, which is a "
            "different fee on a different machine."
        )
    return parsed


@dataclass(frozen=True)
class Plan:
    plan_version: str
    effective_from: datetime
    timezone: ZoneInfo
    timezone_name: str
    currency: str
    space_classes: tuple[str, ...]
    resolution: dict[str, str]
    rules: tuple[Rule, ...]
    decisions: tuple[dict, ...]

    def rules_for_stage(self, stage: str) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.stage == stage)


def load_plan(document: object, where: str = "plan") -> Plan:
    """Validate a plan document and return it, or refuse and name the field."""
    if not isinstance(document, dict):
        raise InvalidPlan(f"{where} must be an object, got {type(document).__name__}.")

    # Before any field is read. A float in a key this version ignores is still a
    # float in a live plan; see money.refuse_non_integer_money.
    refuse_non_integer_money(document, where)
    _require_keys(document, PLAN_KEYS, where)

    plan_version = document["plan_version"]
    if not isinstance(plan_version, str) or not plan_version.strip():
        raise InvalidPlan(f"{where}.plan_version must be a non-empty string.")

    effective_from = parse_instant(document["effective_from"], f"{where}.effective_from")

    timezone_name = document["timezone"]
    if not isinstance(timezone_name, str):
        raise InvalidPlan(f"{where}.timezone must be an IANA zone name, e.g. 'America/New_York'.")
    try:
        timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidPlan(
            f"{where}.timezone {timezone_name!r} is not an IANA zone ({exc}). "
            "'EST' and 'UTC-5' are refused: they cannot express a DST transition, "
            "and a daily cap has to know whether a day was 23 hours or 25."
        ) from exc

    currency = document["currency"]
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isupper():
        raise InvalidPlan(
            f"{where}.currency must be a three-letter uppercase ISO 4217 code, "
            f"got {currency!r}."
        )
    # AND IT MUST BE ONE THIS MODULE CAN RENDER. The sentence above said "ISO
    # 4217" and the check tested only shape, so `ZZZ` loaded and priced. That was
    # half of one defect: the other half was `format_minor` assuming every
    # currency has two decimal places. Both need the same thing -- the currency's
    # minor-unit exponent -- so membership is checked here and the exponent is
    # read there, from one table. See currency.py for what is excluded and why.
    if not is_known(currency):
        raise InvalidPlan(
            f"{where}.currency is {currency!r}, which is not an ISO 4217 currency this "
            "module prices in. The number of minor units in a major one would have to "
            "be guessed to render any amount, and a guessed exponent renders money "
            "wrong by a factor of ten or a hundred. Codes with no minor unit -- XXX, "
            "XTS, the metals and the fund codes -- are refused for the same reason."
        )

    space_classes = document["space_classes"]
    if (
        not isinstance(space_classes, list)
        or not space_classes
        or not all(isinstance(s, str) and s for s in space_classes)
    ):
        raise InvalidPlan(f"{where}.space_classes must be a non-empty list of strings.")
    if len(set(space_classes)) != len(space_classes):
        raise InvalidPlan(f"{where}.space_classes contains a duplicate.")

    resolution = document["resolution"]
    if not isinstance(resolution, dict):
        raise InvalidPlan(f"{where}.resolution must be an object keyed by stage.")
    _require_keys(resolution, frozenset(STAGES), f"{where}.resolution")
    for stage, mode in resolution.items():
        if mode not in RESOLUTION_MODES:
            raise InvalidPlan(
                f"{where}.resolution.{stage} is {mode!r}; expected one of "
                f"{', '.join(RESOLUTION_MODES)}. There is no default: which rule wins "
                "differs by state, so the engine will not choose one for you."
            )

    raw_rules = document["rules"]
    if not isinstance(raw_rules, list) or not raw_rules:
        raise InvalidPlan(f"{where}.rules must be a non-empty list.")
    rules = tuple(
        build_rule(raw, tuple(space_classes), f"{where}.rules[{i}]")
        for i, raw in enumerate(raw_rules)
    )
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise InvalidPlan(f"{where}.rules contains two rules with id {rule.id!r}.")
        seen.add(rule.id)

    decisions = document["decisions"]
    if not isinstance(decisions, list):
        raise InvalidPlan(
            f"{where}.decisions must be a list (empty is fine). It records the owner's "
            "answer to each gap and conflict, with who and when."
        )
    for i, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise InvalidPlan(f"{where}.decisions[{i}] must be an object.")
        _require_keys(
            decision,
            frozenset({"code", "decided_by", "decided_at", "note"}),
            f"{where}.decisions[{i}]",
        )

    return Plan(
        plan_version=plan_version,
        effective_from=effective_from,
        timezone=timezone,
        timezone_name=timezone_name,
        currency=currency,
        space_classes=tuple(space_classes),
        resolution=dict(resolution),
        rules=rules,
        decisions=tuple(decisions),
    )


__all__ = ["InvalidPlan", "Plan", "load_plan", "parse_instant", "RESOLUTION_MODES", "RULE_TYPES"]
