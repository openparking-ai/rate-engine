"""The pipeline's stages, in order, and what each one is for.

Settled in OPENPARKING_SETTLED §8. Several rates can be live on one stay at
once, so this is not "pick one" -- a stay runs through every stage and each may
add lines to the ledger.

    QUALIFY    which base applies: increments, or a special that beats them
    ACCUMULATE the time-based charge itself
    CAP        daily and weekly maxima
    SURCHARGE  a space class costing more than the base (VIP, reserved)
    ADJUST     occupancy-driven multipliers

The order is load-bearing and is not a detail of this implementation: a cap that
ran before the surcharge would cap a number the customer is not being charged,
and a surcharge applied before the cap would be silently capped away.

A1 ships one rule type per stage except ADJUST, which ships none. That is
deliberate -- see docs/CONTRACT.md, "What this version does not do".
"""

from __future__ import annotations

QUALIFY = "QUALIFY"
ACCUMULATE = "ACCUMULATE"
CAP = "CAP"
SURCHARGE = "SURCHARGE"
ADJUST = "ADJUST"

#: Iteration order IS the pipeline order. Nothing sorts this at runtime.
STAGES: tuple[str, ...] = (QUALIFY, ACCUMULATE, CAP, SURCHARGE, ADJUST)
