"""The guard on the guarantees, and the control that proves the guard works.

conftest.py fails the run when a registered guarantee did not run and pass. That
guard is itself a piece of evidence, so it needs the same treatment as everything
else: shown failing, on a run where a guarantee is genuinely missing.

The control runs pytest in a subprocess against a temporary suite -- a copy of the
registry with one extra id nothing proves. The run must go RED and must name the
missing id. Without this, "CI fails when a guarantee stops running" is a sentence
that has never been tested, which is the exact defect the guard exists for.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _guarantees import ALLOW_ENV, GUARANTEES
from plant import ROOT

CONFTEST = (ROOT / "tests" / "conftest.py").read_text()


def _mini_suite(tmp_path: Path, registry_body: str, test_body: str) -> Path:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "_guarantees.py").write_text(registry_body)
    (tests / "conftest.py").write_text(CONFTEST)
    (tests / "test_thing.py").write_text(test_body)
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntestpaths = tests\npythonpath = tests\n"
        "markers =\n    guarantee(id): proves a registered guarantee\n"
    )
    return tmp_path


def _run(cwd: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


REGISTRY = (
    'GUARANTEES = {"G1": "proved", "G2": "NOT proved by anything"}\n'
    f'ALLOW_ENV = "{ALLOW_ENV}"\n'
)
ONE_TEST = (
    "import pytest\n\n\n"
    '@pytest.mark.guarantee("G1")\n'
    "def test_one():\n    assert True\n"
)


def test_a_guarantee_that_never_runs_turns_the_run_red(tmp_path):
    """The control. G2 is registered and nothing proves it."""
    result = _run(_mini_suite(tmp_path, REGISTRY, ONE_TEST))
    assert result.returncode != 0, (
        "a registered guarantee with no test at all left the run GREEN; the guard is "
        "not doing the one thing it exists for"
    )
    assert "G2" in result.stdout
    assert "REGISTERED GUARANTEES THAT DID NOT RUN AND PASS" in result.stdout


def test_a_guarantee_whose_module_fails_to_import_is_caught(tmp_path):
    """The half a per-test hook structurally cannot see.

    A module that raises at import time produces no test items, so a guard that
    only inspects the items it was handed never learns the tests existed. This is
    how another repo in this project lost eight wiring guarantees while its build
    stayed green.
    """
    body = (
        "import pytest\n"
        "raise ImportError('this module cannot load')\n\n\n"
        '@pytest.mark.guarantee("G1")\n'
        "def test_one():\n    assert True\n"
    )
    registry = (
        'GUARANTEES = {"G1": "proved by a module that will not import"}\n'
        f'ALLOW_ENV = "{ALLOW_ENV}"\n'
    )
    result = _run(_mini_suite(tmp_path, registry, body))
    assert result.returncode != 0
    assert "G1" in result.stdout


def test_a_failing_guarantee_does_not_count_as_run(tmp_path):
    """Collected and executed is not enough -- it has to PASS."""
    body = (
        "import pytest\n\n\n"
        '@pytest.mark.guarantee("G1")\n'
        "def test_one():\n    assert False\n"
    )
    registry = f'GUARANTEES = {{"G1": "proved"}}\nALLOW_ENV = "{ALLOW_ENV}"\n'
    result = _run(_mini_suite(tmp_path, registry, body))
    assert result.returncode != 0
    assert "G1" in result.stdout


def test_an_explicit_allowance_is_honoured_and_is_matched_exactly(tmp_path):
    """The escape hatch is an exact id, never a substring of a skip reason.

    A substring match is not a structural guarantee anywhere in this project: it
    lets an unrelated skip reason silently satisfy an allowance somebody wrote for
    a different one.
    """
    suite = _mini_suite(tmp_path, REGISTRY, ONE_TEST)
    assert _run(suite, {ALLOW_ENV: "G2"}).returncode == 0
    # A near-miss is not a match.
    assert _run(suite, {ALLOW_ENV: "G"}).returncode != 0
    assert _run(suite, {ALLOW_ENV: "G22"}).returncode != 0


def test_a_mark_naming_an_unregistered_id_is_rejected(tmp_path):
    """The reverse defect: a test claiming a guarantee the contract never publishes."""
    body = (
        "import pytest\n\n\n"
        '@pytest.mark.guarantee("NOT_IN_THE_REGISTRY")\n'
        "def test_one():\n    assert True\n"
    )
    registry = f'GUARANTEES = {{"G1": "x"}}\nALLOW_ENV = "{ALLOW_ENV}"\n'
    result = _run(_mini_suite(tmp_path, registry, body))
    assert result.returncode != 0
    assert "NOT_IN_THE_REGISTRY" in result.stdout + result.stderr


def test_this_suite_registers_a_control_for_every_guarantee():
    """Every registered guarantee has an entry in scripts/fail_controls.py.

    Derived from both registries, not from a list here -- so a guarantee added
    without a fail-control fails this immediately rather than shipping as an
    unproven promise.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from fail_controls import CONTROLS

    assert set(CONTROLS) == set(GUARANTEES), (
        f"guarantees with no fail-control: {sorted(set(GUARANTEES) - set(CONTROLS))}; "
        f"controls with no guarantee: {sorted(set(CONTROLS) - set(GUARANTEES))}"
    )
