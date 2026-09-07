#!/usr/bin/env python3
"""Every guarantee, proven able to FAIL.

A test that has never failed is a decoration. For each registered guarantee this
script breaks the thing the guarantee guards, runs that guarantee's tests in a
fresh interpreter, and requires them to go RED. If a test stays green with its
subject broken, it was not measuring its subject and this script says so.

    python scripts/fail_controls.py            # every control
    python scripts/fail_controls.py F3 F8      # a subset
    python scripts/fail_controls.py --anchors  # anchors only, in a second

**The anchor pre-flight.** `--anchors` counts every plant's `from` string in its
file without running a single test. An anchor is a string in a source file, and
editing the line it sits on silently retires the control that depends on it --
five of another repo's ten dead controls were killed exactly that way, by a fix
round that edited the anchor lines. The pre-flight answers that whole failure
mode in a second where the full run takes a minute, and run against an older tree
it is its own positive control.

**Restores are written back, never `git checkout`.** Each plant is a context
manager whose `finally` writes the original bytes and verifies them. `checkout`
has been broken twice on this project and would take a co-resident session's
uncommitted work with it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from _guarantees import GUARANTEES  # noqa: E402
from plant import planted, resolve  # noqa: E402

#: guarantee id -> (test target, source file, anchor, replacement, what breaks)
CONTROLS: dict[str, tuple[str, str, str, str, str]] = {
    "F1": (
        "tests/test_f1_never_guesses.py",
        "rules/increment.py",
        "    return ceiling is None or stay.duration_minutes <= ceiling",
        "    return True  # PLANTED: the rule's stated ceiling is ignored",
        "the stated maximum duration stops being checked, so a stay nothing prices "
        "comes back as a NUMBER instead of a refusal",
    ),
    "F2": (
        "tests/test_f2_all_conditions.py",
        "rules/early_bird.py",
        '    elif exit_local.time() > rule.params["exit_by"]:',
        "    elif False:  # PLANTED: the exit condition can no longer fail",
        "the early-bird exit condition is relaxed, so a stay that left after the "
        "limit is given the cheap rate anyway -- partial credit, which §8 forbids",
    ),
    "F3": (
        "tests/test_f3_entry_time_governs.py",
        "engine.py",
        "    in_force = [p for p in plans if p.effective_from <= stay.entry_at]",
        "    in_force = [p for p in plans if p.effective_from <= stay.exit_at]  # PLANTED",
        "the plan version is selected on EXIT time, so a car that parked under one "
        "rate card is billed under a newer one",
    ),
    "F4": (
        "tests/test_f4_integer_minor_units.py",
        "money.py",
        "    if isinstance(node, float):\n        raise NotMinorUnits(",
        "    if False:  # PLANTED: the plan-wide float walk no longer refuses\n"
        "        raise NotMinorUnits(",
        "a float anywhere in a plan is accepted at load, including in a field this "
        "version does not yet read",
    ),
    # P3. The plant removes the plan-wide walk entirely -- "remove the check and
    # require red". `as_minor` still guards the fields that ASK for money, so what
    # this exposes is precisely the gap the sentence was false about: the leaves
    # nothing else types.
    "F4b": (
        "tests/test_f4_integer_minor_units.py",
        "plan.py",
        "    refuse_non_integer_money(document, where)",
        "    pass  # PLANTED: the plan-wide walk no longer runs",
        "a float, a bool or a Decimal in a plan field this version does not read is "
        "accepted at load, so the sentence published at four sites is false again",
    ),
    "F5": (
        "tests/test_f5_determinism.py",
        "rules/early_bird.py",
        # Re-anchored when X5 moved the comparison onto wallclock.local_minute.
        # The PLANTED DEFECT IS UNCHANGED -- the plan's zone is swapped for the
        # server's -- because re-pointing an anchor must not quietly weaken what
        # the control proves.
        "    entry_local = local_minute(stay.entry_at, plan.timezone)\n"
        "    exit_local = local_minute(stay.exit_at, plan.timezone)",
        "    entry_local = local_minute(stay.entry_at, None)  # PLANTED: the SERVER's zone\n"
        "    exit_local = local_minute(stay.exit_at, None)  # PLANTED: the SERVER's zone",
        "the engine reads the SERVER's timezone instead of the plan's, so the same "
        "garage bills two different amounts depending on which machine answered",
    ),
    "F6": (
        "tests/test_f6_one_code_path.py",
        "service.py",
        "        status, body = runner(document)",
        "        status, body = runner(document)\n"
        "        body = dict(body, fee_minor=body.get('fee_minor'))  # PLANTED\n"
        "        body.pop('breakdown', None)  # PLANTED: the route drops the breakdown",
        "the HTTP route answers differently from the pricing path -- the exact shape "
        "of a test function that lies to an operator",
    ),
    # The FIRST plant written for F7 was a dead control and this script said so:
    # it re-sorted each stage's rules by type, which changes nothing when no plan
    # has two rules at one stage -- and none does, because A1 refuses that as a
    # conflict. A control whose fixture cannot reach it reports green from an
    # unmodified measurement. This one plants what F7 actually guards: the
    # REGISTRY leaking into a plan that never named the new type.
    "F7": (
        "tests/test_f7_new_rule_type.py",
        "engine.py",
        "    qualified_at_qualify = _qualifying(plan, stay, QUALIFY)",
        "    for _registered in sorted(RULE_APPLIERS):  # PLANTED: the registry leaks\n"
        "        ledger.add(\n"
        "            Line(code='registry.note', rule_id=None,\n"
        "                 text=f'rule type available: {_registered}', delta_minor=0)\n"
        "        )\n"
        "    qualified_at_qualify = _qualifying(plan, stay, QUALIFY)",
        "the engine mentions every REGISTERED rule type in the breakdown, so "
        "registering a new one rewrites the explanation an existing plan produces",
    ),
    "F11": (
        "tests/test_f11_conflicts_are_refused.py",
        "engine.py",
        "        if len(qualifying) > 1:",
        "        if False:  # PLANTED: a conflict is no longer detected",
        "two rules qualifying at one stage stop being refused, so the pipeline "
        "silently applies both and the plan's resolution mode is never consulted",
    ),
    "F10": (
        "tests/test_f10_unambiguous_plan_selection.py",
        "engine.py",
        "    if len(tied) > 1:",
        "    if False:  # PLANTED: an ambiguous selection is resolved by list order again",
        "two plan versions sharing an effective date stop being refused, so the fee "
        "goes back to depending on which one the caller put first in the array",
    ),
    # K3's half of F8, with its own plant: the amendment's "refused at
    # registration" reduced, on execution, to the one shape that was actually
    # broken -- a malformed return reaching Ledger.add and dying there.
    "F8b": (
        "tests/test_f8_breakdown_adds_up.py",
        "engine.py",
        "        if not isinstance(item, Line):",
        "        if False:  # PLANTED: a non-Line return is no longer refused",
        "a rule returning something that is not a Line stops being refused by "
        "name, and dies inside the ledger with a stack trace naming neither the "
        "rule nor its type",
    ),
    # P2's three. F9 and F13 guard files that carried NO mark at all until this
    # round; F14 guards the guard, and its plant is the first one in this project
    # that lands outside src/ -- `tests/conftest.py` IS the mechanism, and no
    # plant in the engine can reach it. See plant.ROOT_RELATIVE_PREFIXES.
    "F9": (
        "tests/test_contract_is_generated.py",
        "contract.py",
        "SCHEMA_VERSION = 1",
        "SCHEMA_VERSION = 2  # PLANTED: the published schema version moves",
        "the code answers with a schema version the committed contract does not "
        "publish, so docs/CONTRACT.md stops being a reading of the code",
    ),
    "F13": (
        "tests/test_fixture_axes.py",
        "rules/daily_max.py",
        "    if running_total_minor <= ceiling:",
        "    if True:  # PLANTED: the cap never applies to anything",
        "no fixture in the corpus can reach the daily max any more, so the capping "
        "branch every cap guarantee is proven against stops being exercised at all",
    ),
    "F14": (
        "tests/test_guarantee_guard.py",
        "tests/conftest.py",
        "    unaccounted = sorted(set(GUARANTEES) - _ran - allowed)",
        "    unaccounted = []  # PLANTED: nothing is ever unaccounted for",
        "the guard stops failing a run in which a registered guarantee never ran, "
        "which is the exact way another repo lost eight wiring guarantees while "
        "its build stayed green",
    ),
    # P4. "make apply() ignore the field and require red" -- the plant restores
    # exactly the shipped behaviour: the counter is chosen without ever looking
    # at what the plan asked for.
    "F15": (
        "tests/test_f15_rounding_is_consulted.py",
        "rules/increment.py",
        "    count_periods = PERIOD_COUNTERS.get(rounding)",
        "    count_periods = _ceil_periods  # PLANTED: the field is ignored again",
        "the applier stops reading `rounding` and always rounds up, so a plan "
        "stating a mode this version does not implement is priced as ceil instead "
        "of refused -- a wrong fee behind a plan that reads correctly",
    ),
    # P1's two arms. F12 is the split an owner reads; F12b is the line that stops
    # the split from turning into "settled means priced" the first time somebody
    # tidies it. The F12b plant is the whole defect in three lines -- a decision
    # suppressing a blocking finding -- and it is the reason the two are separate
    # ids: a single control could only ever plant one of them.
    "F12": (
        "tests/test_f12_a_decision_is_not_a_price.py",
        "contract.py",
        "    outstanding_codes = {f.code for f in undecided(plan)}",
        "    outstanding_codes = {f.code for f in validate_plan(plan)}  # PLANTED",
        "the split collapses -- every finding reports as outstanding whatever the "
        "owner recorded, so decisions[] is write-only again and `undecided()` is "
        "back to being called by nothing",
    ),
    "F12b": (
        "tests/test_f12_a_decision_is_not_a_price.py",
        "engine.py",
        "    blocking = find_gaps(plan, stay) + find_conflicts(plan, stay)",
        "    _decided = {d['code'] for d in plan.decisions}  # PLANTED\n"
        "    blocking = [\n"
        "        f\n"
        "        for f in find_gaps(plan, stay) + find_conflicts(plan, stay)\n"
        "        if f.code not in _decided\n"
        "    ]  # PLANTED: a free-text note now prices a stay",
        "an entry in decisions[] suppresses the finding it names, so a gap an owner "
        "merely ACKNOWLEDGED starts coming back as a number -- the module inventing "
        "money from prose, which is the failure it exists to prevent",
    ),
    # X1. The plant restores the exact escape the L3 measured: NotMinorUnits is a
    # TypeError, so dropping it from the clause sends a plan float straight past
    # run_quote again and the HTTP route dies without answering.
    "F16": (
        "tests/test_f16_refusals_reach_the_caller.py",
        "contract.py",
        "        plans, stay = parse_quote_request(document)\n"
        "    except (InvalidPlan, NotMinorUnits, ValueError) as exc:",
        "        plans, stay = parse_quote_request(document)\n"
        "    except (InvalidPlan, ValueError) as exc:  # PLANTED: NotMinorUnits escapes again",
        "a plain JSON float in a plan escapes run_quote instead of becoming a named "
        "400, and the HTTP route drops the connection with no response at all",
    ),
    # X3, two arms, because the item was two defects sharing a cause: the
    # rendering assumed an exponent, and the loader assumed anything shaped like a
    # code was one. Breaking either must go red on its own.
    "F17": (
        "tests/test_f17_currency_is_rendered_by_its_exponent.py",
        "money.py",
        "    digits = minor_unit_digits(currency)",
        "    digits = 2  # PLANTED: every currency is assumed to have two decimals again",
        "a zero-decimal currency renders a hundred times too small -- 800 yen shown "
        "as 8.00 JPY -- while the numeric fee stays correct",
    ),
    "F17b": (
        "tests/test_f17_currency_is_rendered_by_its_exponent.py",
        "plan.py",
        "    if not is_known(currency):",
        "    if False:  # PLANTED: an unrenderable currency code loads again",
        "a code with no known exponent -- ZZZ, or XXX which means 'no currency' -- "
        "is accepted at load and reaches the renderer",
    ),
    # X5, two arms. The first restores the raw comparison the L3 measured; the
    # second restores the truncation-of-the-limit that the brief's first draft
    # called for and amendment A3 reversed -- so the reversal itself has a control.
    "F18": (
        "tests/test_f18_wall_clock_is_minute_granular.py",
        "rules/early_bird.py",
        "    entry_local = local_minute(stay.entry_at, plan.timezone)",
        "    entry_local = stay.entry_at.astimezone(plan.timezone)  # PLANTED: raw precision",
        "an entry one microsecond past the limit fails again, and the breakdown "
        "renders 'entry 09:00 is after the 09:00 entry limit'",
    ),
    "F18b": (
        "tests/test_f18_wall_clock_is_minute_granular.py",
        "wallclock.py",
        "    if parsed.second or parsed.microsecond:",
        "    if False:  # PLANTED: a sub-minute limit is silently accepted again",
        "a plan stating enter_by 09:00:30 loads, so a limit the breakdown cannot "
        "render decides the fee -- the engine keeping a decision it cannot explain",
    ),
    # X2. The plant collapses the entry axis back to the single fixed reference,
    # which is exactly the shipped defect: probes vary duration only.
    "F19": (
        "tests/test_f19_validator_probes_declared_boundaries.py",
        "validator.py",
        "    marks = {DEFAULT_PROBE_ENTRY_MINUTE, 0}  # the original reference, and midnight",
        "    return {DEFAULT_PROBE_ENTRY_MINUTE}  # PLANTED: every probe enters at 07:00\n"
        "    marks = {DEFAULT_PROBE_ENTRY_MINUTE, 0}",
        "every probe enters at one fixed time again, so two rules that both qualify "
        "only for an early entry never collide and validate-plan reports the plan "
        "clean while the engine refuses a real stay",
    ),
    # X6. A4 established the "two comparisons" half of this item did not exist --
    # both already read the rounded value. So the control plants what IS real: the
    # ceiling reading raw seconds instead, which pulls the refusal edge away from
    # the pricing edge.
    "F20": (
        "tests/test_f20_time_rounding_is_declared.py",
        "rules/increment.py",
        "    return ceiling is None or stay.duration_minutes <= ceiling",
        # NOTE: the obvious plant here -- comparing raw elapsed minutes -- is a
        # behavioural NO-OP, because ceil(x) > n is equivalent to x > n for an
        # integer n. fail_controls.py reported it GREEN and it was replaced rather
        # than argued with. FLOOR genuinely separates the two: a stay one
        # millisecond past the ceiling floors back INSIDE it and gets priced.
        "    return ceiling is None or int((stay.exit_at - stay.entry_at).total_seconds() // 60)"
        " <= ceiling  # PLANTED: the ceiling floors raw time, the rules ceil minutes",
        "the stated ceiling is compared against raw elapsed time while the rules "
        "price on rounded minutes, so a stay past the ceiling is priced anyway and "
        "the refusal edge no longer matches the pricing edge",
    ),
    # X7. The plant restores the borrowed code exactly as it shipped.
    "F21": (
        "tests/test_f21_a_refusal_names_its_own_cause.py",
        "engine.py",
        "                    code=CONFLICT_NEGATIVE_TOTAL,",
        "                    code=CONFLICT_MULTIPLE_RULES_AT_STAGE,  # PLANTED: borrowed again",
        "a negative total is refused under the code documented for two rules "
        "qualifying at one stage, so a consumer routing on the code is told to "
        "settle a resolution order that was never the problem",
    ),
    # X8, and the three ids guard three DIFFERENT properties -- writing one plant
    # for all of them was how the original F6 ended up unable to see the defect
    # that actually shipped.
    #
    # NOTE, recorded so it is not re-attempted: changing `contract.encode` to
    # indent=4/sort_keys=True is NOT a usable plant any more. Both surfaces read
    # that one function, so they move together and stay equal -- which is the fix
    # working, not a control failing. fail_controls.py reported it GREEN and the
    # plant was replaced rather than argued with.
    "F6b": (
        "tests/test_f6_one_code_path.py",
        "service.py",
        "        payload = encode(body)",
        "        payload = json.dumps(body, indent=2).encode()  # PLANTED: a second encoder",
        "the route encodes its own response again instead of calling the one "
        "encoder, which is the arrangement that let the two doors' bytes diverge "
        "while the contract claimed one serializer",
    ),
    "F6c": (
        "tests/test_f6_one_code_path.py",
        "cli.py",
        "    stream.write(payload)",
        "    stream.write(payload + b' ')  # PLANTED: a byte the route does not send",
        "the CLI writes a byte inside the payload that the route does not send -- "
        "the exact shape of the defect that shipped, print() appending a newline, "
        "and the one the old decoded comparison could not see",
    ),
    # X9. The plant makes every stage behave the way the framework contract used
    # to CLAIM they all did -- non-qualifying rules everywhere emitting zero lines.
    "F22": (
        "tests/test_f22_the_silence_rule_is_per_stage.py",
        "engine.py",
        "            if not QUALIFIERS[rule.type](rule, stay, plan):\n                continue",
        "            if not QUALIFIERS[rule.type](rule, stay, plan):\n"
        "                ledger.add(Line(code=f'{rule.type}.not_applied', rule_id=rule.id,\n"
        "                                text='PLANTED', delta_minor=0))\n"
        "                continue",
        "every non-qualifying rule at every stage emits an explanatory zero line, so "
        "a standard-space receipt lists VIP tiers that were never about that space",
    ),
    # X10. The plant is the L3's own probe: no-op the production invariant. Before
    # this control existed the WHOLE SUITE stayed green under it -- 97 passed.
    "F23": (
        "tests/test_f23_the_production_invariant_is_guarded.py",
        "engine.py",
        "    summed = sum(line.delta_minor for line in ledger.lines)",
        "    return  # PLANTED: the production invariant is a no-op\n"
        "    summed = sum(line.delta_minor for line in ledger.lines)",
        "the invariant that makes the breakdown the product rather than a report "
        "stops reacting at all -- the exact deletion that left all 97 tests green "
        "when the outside pass measured it",
    ),
    # X11. The plant makes a zero-length stay free -- the behaviour Grok proposed
    # and Gokhan has not overruled. The control exists so the DECISION cannot be
    # changed by accident; changing it on purpose is a brief.
    "F24": (
        "tests/test_f24_a_zero_length_stay_is_priced.py",
        "rules/increment.py",
        "    if minutes <= first_len:",
        "    if minutes == 0:  # PLANTED: a zero-length stay silently becomes free\n"
        "        return []\n"
        "    if minutes <= first_len:",
        "a stay of zero minutes stops paying the first period, which is a pricing "
        "decision being changed with nothing said -- and it is the exact behaviour "
        "an outside reviewer asked for and the owner has not agreed to",
    ),
    "F8": (
        "tests/test_f8_breakdown_adds_up.py",
        "engine.py",
        "    fee = ledger.total_minor\n    _assert_ledger_is_the_fee(fee, ledger)",
        "    fee = ledger.total_minor - 1  # PLANTED: a second route to the total\n"
        "    _assert_ledger_is_the_fee(fee, ledger)",
        "the fee is reached by a route other than adding a Line, which is the defect "
        "the ledger exists to make impossible",
    ),
}


def check_anchors() -> int:
    """Count every anchor. Zero or two is a dead control, and it is silent."""
    bad = 0
    for gid, (_target, path, anchor, _to, _why) in sorted(CONTROLS.items()):
        source = resolve(path).read_text()
        count = source.count(anchor)
        status = "ok" if count == 1 else "DEAD"
        if count != 1:
            bad += 1
        print(f"  {status:4}  {gid}  {path}  anchor appears {count}x")
    if bad:
        print(
            f"\n{bad} control(s) have no live anchor. An anchor that matches zero times "
            "plants nothing, and the control then reports green against unmodified "
            "source. Fix the anchors before trusting any result from this script."
        )
        return 1
    print(f"\nall {len(CONTROLS)} anchors live.")
    return 0


def run_control(gid: str) -> bool:
    target, path, anchor, replacement, why = CONTROLS[gid]
    print(f"\n=== {gid} — {GUARANTEES[gid]}")
    print(f"    plant: {path}")
    print(f"    breaks: {why}")

    green = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if green.returncode != 0:
        print(f"    UNMEASURED: {target} is already failing before anything was planted.")
        print(green.stdout[-1500:])
        return False

    with planted(path, anchor, replacement):
        red = subprocess.run(
            [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    tail = [ln for ln in red.stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))]
    summary = red.stdout.strip().splitlines()[-1] if red.stdout.strip() else ""
    if red.returncode == 0:
        print(f"    NOT A CONTROL: {target} stayed GREEN with its subject broken.")
        return False
    print(f"    RED, as required — {summary}")
    for line in tail[:6]:
        print(f"      {line}")
    return True


def main(argv: list[str]) -> int:
    if "--anchors" in argv:
        return check_anchors()

    wanted = [a for a in argv if a in CONTROLS] or sorted(CONTROLS)
    unknown = [a for a in argv if a not in CONTROLS and not a.startswith("-")]
    if unknown:
        print(f"no such control: {', '.join(unknown)}")
        return 2

    missing = sorted(set(GUARANTEES) - set(CONTROLS))
    if missing:
        print(
            f"registered guarantees with no fail-control: {', '.join(missing)}. "
            "Every guarantee is proven able to fail, or it is not a guarantee."
        )
        return 1

    if check_anchors():
        return 1

    results = {gid: run_control(gid) for gid in wanted}
    dead = [gid for gid, ok in results.items() if not ok]
    print(f"\n{len(results) - len(dead)}/{len(results)} controls fired.")
    if dead:
        print(f"DEAD CONTROLS: {', '.join(dead)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
