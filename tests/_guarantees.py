"""The canonical registry of this module's guarantees. ONE source, three consumers.

    conftest.py       requires every id below to have RUN in the session
    docs/CONTRACT.md  is generated from this table
    test_f*.py        each declares its id with @pytest.mark.guarantee

Why a registry rather than a list of module names: `vehicle-id`'s equivalent
guard names the test MODULES that may not vanish, in a tuple somebody has to
remember to update, and matches skip allowances by SUBSTRING. Both shapes are
ones this project's own rules forbid elsewhere -- a hard-coded list cannot notice
something added to what it is supposed to cover, and a substring match is not a
structural guarantee. So the mechanism is copied and those two properties are
not: ids are declared on the marks, collected from the run, and compared as a
SET against this table by equality. A guarantee test that stops being collected
-- because its module failed to import, because a file was renamed, because
somebody deleted it -- leaves an id unaccounted for and the run fails naming it.

An allowance is an explicit id in RATE_ENGINE_ALLOW_UNRUN, matched exactly. This
module has no optional dependency and no weights, so there is nothing it can
legitimately skip, and CI names no allowance at all: the variable exists so that
the escape hatch is a decision somebody writes down rather than a green build.
"""

from __future__ import annotations

#: id -> the promise the test proves, in the words the contract publishes.
GUARANTEES: dict[str, str] = {
    "F1": (
        "The engine never guesses. A stay the plan cannot price is REFUSED, naming "
        "the gap, and no number is returned."
    ),
    "F2": (
        "A special rate is all-conditions-or-nothing. Miss one condition by a minute "
        "and it does not apply at all -- no pro-rating and no partial credit."
    ),
    "F3": (
        "The plan version in force at ENTRY prices the whole stay. A rate change "
        "mid-stay never splits it."
    ),
    "F4": (
        "Money is an integer of minor units. A float, a bool or a Decimal anywhere in "
        "a plan is refused at load."
    ),
    "F4b": (
        "That sentence is true at EVERY leaf of a plan, not at the fields the engine "
        "happens to read -- proven by probing every position in the document, so a "
        "field added in a later round is covered the day it exists."
    ),
    "F5": (
        "Determinism. The same plan version and the same stay produce the same fee "
        "AND the same breakdown, always, on any machine and at any wall-clock time."
    ),
    "F6": (
        "The test function IS the production path. `/v1/quote` and the CLI return the "
        "same bytes for the same request, from one code path and one serializer."
    ),
    "F7": (
        "Registering a new rule type changes no existing plan's answer -- fee and "
        "breakdown byte-identical."
    ),
    "F8": (
        "The fee is the sum of the breakdown's deltas, by construction. There is no "
        "second route to the total."
    ),
    "F8b": (
        "A rule's only channel to the fee is a list of Lines. A malformed return is "
        "REFUSED by name, not left to crash inside the ledger."
    ),
    "F11": (
        "Two rules qualifying at one pipeline stage are REFUSED and both named, with "
        "the plan's stated resolution mode quoted back. A1 detects; it does not resolve."
    ),
    "F10": (
        "Plan selection is never ambiguous. Two versions in force at the same instant "
        "are REFUSED and both named, never resolved by the order of the caller's list."
    ),
    "F15": (
        "`increment.rounding` is CONSULTED by the applier, which refuses a mode it "
        "does not implement rather than pricing the stay under a different one. The "
        "applier checks what it implements, never what the loader accepts."
    ),
    "F12": (
        "`validate-plan` separates the findings an owner has still to look at from the "
        "ones they have recorded a decision for. Every finding is reported either way."
    ),
    "F9": (
        "The published contract is DERIVED, never transcribed. Every generated block "
        "matches the code, and every block that ASSERTS something about its values is "
        "proven to move when those values contradict it."
    ),
    "F13": (
        "The fixture corpus holds a case either side of every threshold the rules "
        "branch on, read out of the plans rather than from a list -- so no guarantee "
        "is proven against a corpus that could only ever exercise one branch."
    ),
    "F14": (
        "A registered guarantee whose test stops running turns the build RED, "
        "including when its module fails to import; and a test module that plants a "
        "defect but registers no guarantee is refused."
    ),
    "F16": (
        "Every refusal reaches the caller AS a refusal. A malformed number anywhere "
        "in a plan comes back as a named 400 naming the field, and a malformed rule "
        "return as a named 422 -- never as an exception escaping the quote contract, "
        "and never as a dropped connection."
    ),
    "F17": (
        "A rendered amount uses its own currency's ISO 4217 minor-unit exponent, "
        "never an assumed two decimal places -- and a code whose exponent this "
        "module does not know is REFUSED at load rather than rendered on a guess."
    ),
    "F17b": (
        "That refusal is at LOAD, so an unrenderable currency never reaches the "
        "renderer at all -- the membership check and the exponent read one table."
    ),
    "F18": (
        "A wall-clock limit is compared at the granularity it is written and "
        "rendered in: the stay is truncated to the minute, so no breakdown line can "
        "say a time is after itself."
    ),
    "F18b": (
        "And the LIMIT is refused rather than truncated. A plan may state 'HH:MM'; "
        "anything finer is rejected at load, because rounding it would silently "
        "discard a pricing decision the operator wrote."
    ),
    "F19": (
        "`validate-plan` probes every boundary the plan DECLARES -- entry limits and "
        "exit limits as well as durations, each side of each -- so a conflict the "
        "engine would refuse is one the owner was shown before the plan went live."
    ),
    "F20": (
        "There are TWO time roundings and both are declared: a part-minute is a whole "
        "minute (assumed, module-wide) and minutes into periods is stated per rule. "
        "Every comparison against a duration reads the same rounded value."
    ),
    "F12b": (
        "A decision is an ACKNOWLEDGEMENT, not a price. A stay hitting a SETTLED gap is "
        "refused exactly as one hitting an outstanding gap is; no entry in `decisions[]` "
        "can cause a fee to be produced."
    ),
}

#: Environment variable naming ids this job cannot run. Exact ids, comma
#: separated. Empty everywhere in CI on purpose.
ALLOW_ENV = "RATE_ENGINE_ALLOW_UNRUN"
