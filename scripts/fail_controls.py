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
from plant import SRC, planted  # noqa: E402

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
    "F5": (
        "tests/test_f5_determinism.py",
        "rules/early_bird.py",
        "    entry_local = stay.entry_at.astimezone(plan.timezone)\n"
        "    exit_local = stay.exit_at.astimezone(plan.timezone)",
        "    entry_local = stay.entry_at.astimezone()  # PLANTED: the SERVER's zone\n"
        "    exit_local = stay.exit_at.astimezone()  # PLANTED: the SERVER's zone",
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
        source = (SRC / path).read_text()
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
