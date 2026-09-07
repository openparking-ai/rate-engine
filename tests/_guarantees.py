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
    "F10": (
        "Plan selection is never ambiguous. Two versions in force at the same instant "
        "are REFUSED and both named, never resolved by the order of the caller's list."
    ),
}

#: Environment variable naming ids this job cannot run. Exact ids, comma
#: separated. Empty everywhere in CI on purpose.
ALLOW_ENV = "RATE_ENGINE_ALLOW_UNRUN"
