"""Planting a defect in the source, and putting it back.

Every guarantee is proven able to fail by breaking the thing it guards and
watching it go red. The restore writes back the exact bytes that were there, in a
`finally`, and verifies them -- **never `git checkout`**, which has been broken
twice on this project and would take a co-resident session's uncommitted work
with it.

**The plant runs the test in a SUBPROCESS, and this is the second design.** The
first reloaded the planted module in-process with `importlib.reload`, and it was
quietly broken in a way worth recording here, because it is the shape of defect
this project keeps finding: a reload REBINDS a module's exception classes, so the
`NotMinorUnits` a reloaded module raises is a different class object from the
`NotMinorUnits` the test file imported at collection time. `pytest.raises` then
does not catch it, the control fails for a reason unrelated to the defect it
planted, and -- the part that matters -- a control written slightly differently
would instead have PASSED for a reason unrelated to the defect. A fresh
interpreter has no identity problem to get wrong.

Two guards on the plant itself:

* **The anchor must appear EXACTLY ONCE.** Zero matches plants nothing and the
  control then reports red from unmodified source. Two matches lands in the wrong
  place. Both are checked before a byte is written.
* **The restore is verified, not assumed.** A restore that silently failed leaves
  a planted defect in the working tree for everything that runs after it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "rate_engine"


@contextmanager
def planted(relative_path: str, frm: str, to: str):
    path = SRC / relative_path
    original = path.read_text()

    occurrences = original.count(frm)
    if occurrences != 1:
        raise AssertionError(
            f"the anchor for this fail-control appears {occurrences} times in "
            f"{relative_path}, not once. A plant that cannot find its anchor proves "
            "nothing; one that finds two lands in the wrong place. Fix the anchor "
            "before trusting anything this control reports."
        )

    try:
        _write(path, original.replace(frm, to))
        yield
    finally:
        _write(path, original)
        if path.read_text() != original:
            raise AssertionError(
                f"{relative_path} was NOT restored -- a planted defect is still in "
                "the working tree. Restore it by hand before running anything else."
            )


#: Every write through this helper gets a distinct modification time. See _write.
_writes = 0


def _write(path: Path, text: str) -> None:
    """Write, and make sure Python cannot serve the PREVIOUS bytecode for it.

    CPython validates a cached `.pyc` against the source's (mtime IN WHOLE
    SECONDS, size). A plant that changes a file without changing its SIZE, inside
    the same second as the last write, is therefore invisible to any subprocess:
    it imports the stale bytecode, behaves exactly as if nothing was planted, and
    the control reports GREEN against a defect that was never actually loaded.

    This is not hypothetical -- it happened here. The control for the findings
    table moves one line out of `GAP_CODES` and the identical line into
    `CONFLICT_CODES`, so the file came out byte-for-byte the same LENGTH, and the
    rendered document came back unplanted. The failure mode is the worst kind
    this project catalogues: a check shaped like evidence that cannot produce a
    negative result, and one that would have looked like a REAL finding ("the
    prose does not follow the registry") rather than like a broken test.

    No existing control was affected -- all ten change the file's length -- but
    that was luck, and the next plant somebody writes should not have to depend
    on it. So the mtime is advanced past any cached entry on every write.
    """
    global _writes
    _writes += 1
    path.write_text(text)
    stamp = time.time() + _writes
    os.utime(path, (stamp, stamp))


def run_tests(target: str) -> subprocess.CompletedProcess:
    """Run one test target in a fresh interpreter and return the result."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
