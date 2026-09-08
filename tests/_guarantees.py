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
        "A special rate is all-conditions-or-nothing: miss one condition by a minute "
        "and it does not apply at all -- no pro-rating and no partial credit. "
        "Enforced per rule type; `time_window` is the only special this module "
        "ships, so the property is proven of it rather than of a populated stage."
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
        "The test function IS the production path. `/v1/quote` and the CLI emit the "
        "same response bytes for the same request, from one code path and one "
        "encoder; the CLI's terminal newline is written outside the payload."
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
        "An ambiguity the PLAN cannot settle is REFUSED and both rules named, with "
        "the stated mode quoted back and the refusal saying what would settle it. "
        "Since the modes act, that means a TIE: two rules qualifying at one stage "
        "and charging the same amount, which `cheapest_wins` cannot separate."
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
    "F21": (
        "A refusal's CODE names the cause that actually occurred. A negative total "
        "is CONFLICT_NEGATIVE_TOTAL, not the multi-rule conflict code it borrowed."
    ),
    "F6b": (
        "And there is exactly ONE encoder. No surface re-implements the response "
        "bytes, so the two doors cannot drift the way they silently did."
    ),
    "F6c": (
        "The CLI's payload is the route's payload BYTE FOR BYTE, with any terminal "
        "newline written outside it -- compared as bytes, never as decoded objects."
    ),
    "F22": (
        "Whether a non-qualifying rule appears in the breakdown depends on its STAGE: "
        "a QUALIFY rule always speaks, at delta zero; a rule at another stage that "
        "does not cover the stay is silent."
    ),
    "F22b": (
        "And the stage is not the whole answer. A rule TYPE may declare that it "
        "speaks when it did not qualify, so a weekend discount declining because it "
        "is a Tuesday says so on the receipt -- while a rule that was never about "
        "this space stays silent whatever it declared."
    ),
    "F23": (
        "The production invariant that the fee IS the ledger's sum is itself "
        "guarded: deleting it, no-opping it or unwiring it from the pricing path "
        "turns the suite red."
    ),
    "F24": (
        "A zero-length stay pays the first period -- a decision, published in the "
        "contract with the divergence it was disclosed with, not left for an "
        "integrator to discover as an anomaly."
    ),
    "F25": (
        "Whether a time window may run past midnight is stated by the PLAN, in "
        "`day_span`, with no default -- the engine holds no day condition of its own."
    ),
    "F26": (
        "A window applies on the days the PLAN states -- weekday names, or the "
        "garage's own dates for a holiday or an event -- matched against the "
        "ENTRY's local date, and a window that did not match names the day that "
        "failed and the days it wanted. There is no built-in calendar and no "
        "preset: 'weekend' means different days in different countries."
    ),
    "F27": (
        "`enter_from` is CONSULTED, not merely validated and stored. A window "
        "states BOTH ends of its entry range, which is what makes an evening rate "
        "expressible, and a stay arriving one minute before it opens does not "
        "qualify."
    ),
    "F28": (
        "`day_span` `next_day` is BOUNDED: an exit on the following local day "
        "qualifies and one the day after that does not, where `any_span` accepts "
        "both. Proven on one stay, so the three spans are an axis rather than "
        "three unrelated scenarios."
    ),
    "F29": (
        "A `rate` effect is priced by `increment`'s own builder and applier, not "
        "by a copy of them: identical parameters produce identical lines on the "
        "same stay, and a change to `increment`'s period counting moves the "
        "window's lines with it."
    ),
    "F30": (
        "An `adjust` effect applies to the fee AFTER the caps and the surcharges. "
        "A percentage taken any earlier is a percentage of a number the customer "
        "is not being charged."
    ),
    "F31": (
        "An `adjust` percentage is integer basis points and its `rounding` is "
        "CONSULTED: the same stay under `up` and under `down` differs by one minor "
        "unit, and the breakdown line says which way it went."
    ),
    "F32": (
        "`grace` is TERMINAL, and free means free: a stay at or under the stated "
        "minutes costs zero and picks up no surcharge, no cap and no adjustment. "
        "Terminality is DECLARED by the rule type at registration -- the engine "
        "never knows its name -- and a special it beat says so on the receipt."
    ),
    "F33": (
        "Two caps on one stay leave the LOWER ceiling standing, the total after CAP "
        "is the same in both application orders, and the breakdown names both. Caps "
        "COMPOSE; two of them are not a conflict."
    ),
    "F34": (
        "More than one rule qualifying at one stage means three different things, "
        "and the stage's category decides which: RESOLVING is a conflict, COMPOSING "
        "order-independent is not reported at all, and COMPOSING order-dependent is "
        "refused unless the plan states the order."
    ),
    "F35": (
        "Two qualifying ADJUST rules with no stated `adjust_order` are REFUSED "
        "naming both; with an order they produce that order's total, and the two "
        "orders genuinely differ -- 20% off then a fixed amount is not the same fee "
        "as the fixed amount then 20% off."
    ),
    "F36": (
        "The resolution modes DECIDE. Two windows qualifying on one stay resolve to "
        "the cheaper under `cheapest_wins` and to the stated one under "
        "`stated_order`, on the SAME stay -- and the rules that lost still appear, "
        "each naming the winner, both prices and the mode that chose."
    ),
    "F38": (
        "Every identifier the published documents name in backticks is one the "
        "code actually holds -- rule types, stages, finding codes, plan and rule "
        "fields, stated values, traits and guarantee ids -- and every file path "
        "they point at exists. Derived from both documents rather than from a "
        "list of the sentences somebody remembered to check."
    ),
    "F37": (
        "A `stated_order` must name every rule at its stage EXACTLY ONCE, and one "
        "that does not is refused at LOAD, naming what is missing. A rule left out "
        "would take a silent position, and array position deciding money is what "
        "this module refuses everywhere else."
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
