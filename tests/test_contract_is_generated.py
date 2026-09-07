"""The contract's generated blocks must DERIVE what they assert.

GENERATION IS NOT VERIFICATION. Moving a sentence from a document into a template
does not stop it being hand-written: everywhere except the holes it is still
prose nobody checks, and a generated block asserts only what it derives from its
values. Anything else is a fixed string that no measurement can falsify.

So each test below plants a value that CONTRADICTS the document and requires the
document to change. A block that does not move under its own input is a hard-coded
sentence wearing a template's clothes, and this is the only thing that can tell
the two apart.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from plant import ROOT, planted

CONTRACT = ROOT / "docs" / "CONTRACT.md"
GENERATOR = ROOT / "scripts" / "generate_contract.py"


def _render() -> str:
    """Render the contract in a fresh interpreter, without writing it."""
    result = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.argv=['g']; "
         f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
         "import generate_contract as g; print(g.render())"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


def test_the_committed_contract_matches_the_code():
    """A hand-edited number or sentence in docs/CONTRACT.md turns this red."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


#: Registering an EXTRA rule type, rather than renaming one, is what a plant here
#: has to do. A rename breaks the example plan -- the engine refuses a rule type
#: it does not know, correctly -- so the generator stops before it reaches the
#: table, and the control would then be reporting a refusal rather than a
#: document that failed to move. An addition leaves every existing plan valid,
#: which is also the property F7 guarantees.
ADD_A_RULE_TYPE = (
    "rules/space_surcharge.py",
    'register("space_surcharge", SURCHARGE, build, apply)',
    'register("space_surcharge", SURCHARGE, build, apply)\n'
    "from ..stages import ADJUST as _PLANTED_STAGE  # noqa: E402\n"
    'register("planted_extra", _PLANTED_STAGE, build, apply)',
)


def test_the_rule_type_table_is_derived_from_the_registry():
    """PLANT: register an extra rule type. The table must grow a row."""
    baseline = _render()
    assert "| `space_surcharge` | SURCHARGE |" in baseline
    assert "planted_extra" not in baseline

    with planted(*ADD_A_RULE_TYPE):
        planted_render = _render()

    assert "| `planted_extra` | ADJUST |" in planted_render, (
        "the rule-type table did not grow when a rule type was registered, so it is a "
        "hand-written list rather than a reading of the registry"
    )


def test_the_empty_stage_note_is_derived_and_not_a_fixed_sentence():
    """The same plant, on the sentence beside the table.

    A true sentence sitting next to a checked table, borrowing its credit, is one
    of the named failures in this project's process notes. ADJUST ships no rule
    type and the document says so because it COUNTED -- so the moment a stage
    stops being empty, the sentence has to stop saying it.
    """
    baseline = _render()
    assert "Stages with no rule type in this version: ADJUST." in baseline

    with planted(*ADD_A_RULE_TYPE):
        planted_render = _render()

    assert "Stages with no rule type in this version: ADJUST." not in planted_render, (
        "the note about empty stages did not change when ADJUST stopped being empty"
    )
    assert "Every stage has at least one rule type in this version." in planted_render


def test_the_gap_table_is_derived_from_the_findings_registry():
    """PLANT: rename a gap code. The table must follow it."""
    with planted(
        "findings.py",
        'GAP_NO_ACCUMULATE_RULE = "GAP_NO_ACCUMULATE_RULE"',
        'GAP_NO_ACCUMULATE_RULE = "GAP_PLANTED_CODE"',
    ):
        planted_render = _render()

    assert "GAP_PLANTED_CODE" in planted_render
    assert "`GAP_NO_ACCUMULATE_RULE`" not in planted_render


def test_the_worked_example_is_priced_not_transcribed():
    """PLANT: change the example plan's hourly rate. Every number must move.

    This is the block most likely to rot into prose, because it reads like a
    transcript. It is not one -- it is the engine's actual output, so a rate
    change rewrites the lines AND the total AND the sentence about the sum.
    """
    baseline = _render()
    assert "FEE  3000 minor units" in baseline

    plan_path = ROOT / "tests" / "plans" / "downtown_v2.json"
    original = plan_path.read_text()
    document = json.loads(original)
    for rule in document["rules"]:
        if rule["id"] == "cap":
            rule["max_minor"] = 9999
    try:
        plan_path.write_text(json.dumps(document, indent=2))
        planted_render = _render()
    finally:
        plan_path.write_text(original)
        assert plan_path.read_text() == original

    assert "FEE  3000 minor units" not in planted_render, (
        "the worked example did not change when the plan it prices changed, so it is "
        "a transcript rather than a run"
    )
    assert "FEE  4400 minor units" in planted_render
    assert "The lines above sum to 4400" in planted_render, (
        "the sentence about the sum did not follow the numbers -- it is a fixed "
        "string borrowing their credibility"
    )


def test_the_guarantee_table_is_derived_from_the_registry():
    """PLANT: change a guarantee's wording. The published table must follow."""
    registry = Path(ROOT / "tests" / "_guarantees.py")
    original = registry.read_text()
    try:
        registry.write_text(
            original.replace(
                '"F1": (\n        "The engine never guesses.',
                '"F1": (\n        "PLANTED SENTENCE.',
            )
        )
        planted_render = _render()
    finally:
        registry.write_text(original)
        assert registry.read_text() == original

    assert "PLANTED SENTENCE" in planted_render, (
        "the guarantee table is not read from tests/_guarantees.py"
    )


@pytest.mark.parametrize(
    "marker",
    ["schema_version", "stages", "rule_types", "findings", "guarantees", "example", "resolution"],
)
def test_every_generated_block_is_closed(marker):
    text = CONTRACT.read_text()
    assert f"<!--gen:{marker}-->" in text
    assert f"<!--/gen:{marker}-->" in text
