"""F22 -- whether a non-qualifying rule speaks depends on its STAGE.

The rule framework's contract said, flatly: *"A rule that did NOT qualify still
returns a line, with delta zero, saying why not."* `space_surcharge` documented
the opposite in its own docstring -- *"A stay in a space class this rule does not
cover produces NO line"* -- so the framework contract and a shipped rule type
contradicted each other and nothing measured either. The engine skips every
non-qualifying rule outside QUALIFY (`engine.py`, `if not QUALIFIERS[...]:
continue`), so the framework sentence was false for every stage except one.

The DISTINCTION is right and is kept. "This special could have applied to you and
did not" is the answer to the question operators actually ask at the counter; "a
VIP tier that was never about your space exists" is noise on a standard receipt.
What was wrong was stating it as a blanket property of every rule.

Both halves are pinned here, because a corrected sentence with no check is a
sentence that drifts back, and this one drifted for a whole round.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import run_quote
from rate_engine.stages import QUALIFY


def _codes(document: dict, space_class: str = "standard") -> list[str]:
    status, body = run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T10:40:00-05:00", "space_class": space_class,
            "currency": "USD",
        }
    )
    assert status == 200, body
    return [line["code"] for line in body["breakdown"]]


@pytest.mark.guarantee("F22")
def test_a_QUALIFY_rule_that_did_not_qualify_STILL_SPEAKS():
    """The half that was always true, and the reason the distinction exists."""
    codes = _codes(copy.deepcopy(DOWNTOWN_V2))
    assert "time_window.not_applied" in codes, (
        "the special that did not apply said nothing, so the breakdown cannot answer "
        "'why didn't I get the early bird rate'"
    )


@pytest.mark.guarantee("F22")
def test_a_rule_at_ANOTHER_stage_that_does_not_cover_the_stay_IS_SILENT():
    """The half the framework contract denied. `space_surcharge` on a vip-only
    class must not appear on a standard receipt."""
    codes = _codes(copy.deepcopy(DOWNTOWN_V2))
    assert not any(c.startswith("space_surcharge") for c in codes), (
        f"a surcharge that was never about this space appeared on the receipt: {codes}"
    )


@pytest.mark.guarantee("F22")
def test_and_it_DOES_speak_when_it_applies():
    """The control on the item above: silence must be about non-coverage, not a
    rule that has stopped working."""
    codes = _codes(copy.deepcopy(DOWNTOWN_V2), space_class="vip")
    assert "space_surcharge.applied" in codes


@pytest.mark.guarantee("F22")
def test_the_silence_rule_holds_at_EVERY_non_qualify_stage_that_ships():
    """Derived from the registry, not from a list of the stages that exist today.

    A rule type registered at a new non-QUALIFY stage is covered the day it is
    added; a written list could not notice it. §6's enumeration rule.
    """
    from rate_engine.rules import RULE_TYPES

    document = copy.deepcopy(DOWNTOWN_V2)
    # Restrict every non-QUALIFY rule to 'vip', then price a 'standard' stay: no
    # rule outside QUALIFY covers it, so none of them may appear.
    non_qualify_ids = set()
    for rule in document["rules"]:
        # The rule's OWN stage, not the type's. A type may now run at more than
        # one stage -- `time_window` is a base at QUALIFY and an adjustment at
        # ADJUST -- so the registry answers "where may this type run" and the
        # rule answers "where does this one run". The loader makes the document's
        # claim and the code's derivation agree, so reading it here is still a
        # derivation rather than a list somebody types.
        stages, _builder = RULE_TYPES[rule["type"]]
        assert rule["stage"] in stages, f"{rule['id']} states a stage its type cannot run at"
        if rule["stage"] != QUALIFY:
            rule["space_classes"] = ["vip"]
            non_qualify_ids.add(rule["type"])
    assert non_qualify_ids, "no non-QUALIFY rule type ships, so this proves nothing"

    status, body = run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T10:40:00-05:00", "space_class": "standard",
            "currency": "USD",
        }
    )
    # Nothing prices the time for 'standard' now, so this is a refusal -- and a
    # refusal carries findings, not lines. That is itself the point: the engine
    # says what is missing rather than emitting explanatory zero lines for rules
    # that were never about this stay.
    assert status == 422
    assert body["findings"][0]["code"] == "GAP_NO_ACCUMULATE_RULE"


def test_the_framework_contract_no_longer_states_the_blanket_claim():
    """The control on the DOCUMENTATION half.

    Keyed on the claim rather than on a phrase somebody might reword: the module
    must not say a non-qualifying rule always returns a line without also saying
    the rule is per stage.
    """
    import rate_engine.rules as framework

    text = " ".join((framework.__doc__ or "").split())
    assert "depends on its stage" in text.lower(), (
        "the rule framework no longer says the silence rule is per stage"
    )
    assert "A rule that did NOT qualify still returns a line, with delta zero, saying" \
        not in text, "the blanket claim has come back"
