"""Money is a Python ``int`` of minor units. Nothing else is money here.

No float, no ``Decimal``, no string, at any depth of a plan or a rule. A rate
that cannot be expressed in minor units is a rate this module refuses, and it
refuses it at load rather than at the point the arithmetic goes wrong.

Three traps this file exists to close, all of them things that pass a naive
``isinstance(value, int)``:

* **``bool`` is a subclass of ``int`` in Python.** ``isinstance(True, int)`` is
  ``True``, so ``True`` sails through an integer check and then prices a stay at
  one minor unit. It is rejected explicitly, first, before the int check.
* **JSON exponent form parses to a float.** ``json.loads("1e2")`` is ``100.0``,
  not ``100`` -- a plan author writing ``1e2`` for a dollar rate produces a float
  that happens to be integral. ``float`` is rejected whatever its value, so
  ``100.0`` is refused exactly as ``100.5`` is. There is no "but it is a whole
  number" branch, because that branch is how floats get in.
* **``Decimal`` looks like the safe choice and is not, here.** It is refused too.
  Not because it is inaccurate -- it is not -- but because two money types in
  one codebase means every function has to handle both, and the one that
  eventually forgets is the one that ships. One type, all the way down.

Nothing in this module rounds money. The only rounding in the engine is
TIME into periods, it is stated per rule rather than assumed, and it happens
before any amount is touched. See ``rules/increment.py``.
"""

from __future__ import annotations

from typing import Any


class NotMinorUnits(TypeError):
    """A value that was supposed to be money is not an integer of minor units."""


def as_minor(value: Any, label: str) -> int:
    """Return ``value`` as minor units, or refuse and say which field was wrong.

    The label is the plan's own path to the field (``rules[2].first_period_minor``),
    because a refusal that does not say where to look is a refusal the operator
    cannot act on.
    """
    if isinstance(value, bool):
        raise NotMinorUnits(
            f"{label} is a boolean ({value!r}). Money is an integer of minor units; "
            "`bool` is an `int` subclass in Python and would otherwise price this "
            "at 0 or 1 without complaint."
        )
    if isinstance(value, float):
        raise NotMinorUnits(
            f"{label} is a float ({value!r}). Money is an integer of minor units -- "
            "800 means 8.00, not 8.0. Note that JSON exponent form (1e2) parses as a "
            "float even though it looks whole."
        )
    if not isinstance(value, int):
        raise NotMinorUnits(
            f"{label} is {type(value).__name__} ({value!r}). Money is an integer of "
            "minor units. Decimal and str are refused deliberately: one money type, "
            "all the way down."
        )
    return value


def as_non_negative_minor(value: Any, label: str) -> int:
    minor = as_minor(value, label)
    if minor < 0:
        raise NotMinorUnits(f"{label} is negative ({minor}). A price is not negative.")
    return minor


def refuse_floats(node: Any, path: str = "plan") -> None:
    """Walk a loaded plan and refuse a float or a Decimal ANYWHERE in it.

    ``as_minor`` guards the fields the engine reads. This guards the fields it
    does not -- a float sitting in a rule parameter the current version ignores
    is a float that starts being read the round somebody adds the rule type that
    reads it, and by then it is in a plan an operator believes is live.

    The check is on the type, not on the value: ``3.0`` is refused. A plan is
    data an integrator wrote, and the moment this makes an exception for a float
    that happens to be whole, every float becomes one bug away from whole.
    """
    if isinstance(node, bool):
        return
    if isinstance(node, float):
        raise NotMinorUnits(
            f"{path} is a float ({node!r}). No float appears anywhere in a plan, at any "
            "depth -- not in a field this version reads, and not in one it ignores."
        )
    if isinstance(node, dict):
        for key, value in node.items():
            refuse_floats(value, f"{path}.{key}")
        return
    if isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            refuse_floats(value, f"{path}[{index}]")
        return
    # Anything that is not a container, a float or a bool: `as_minor` decides
    # whether it is money when a field actually asks for money. Decimal lands
    # here, and is caught there rather than by this walk, so the refusal names
    # the field instead of a path.


def format_minor(minor: int, currency: str) -> str:
    """For a breakdown line's text. Never feed the result back into arithmetic."""
    sign = "-" if minor < 0 else ""
    whole, part = divmod(abs(minor), 100)
    return f"{sign}{whole}.{part:02d} {currency}"
