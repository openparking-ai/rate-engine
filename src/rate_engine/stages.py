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

Every stage now carries at least one rule type. ADJUST was empty in A1 and went
live in A2 with `time_window`'s `adjust` effect -- a percentage or an amount, up
or down, on the whole fee. It runs LAST, which is the same argument the order
above rests on: an adjustment applied before the cap and the surcharge would take
a percentage of a number the customer is not being charged.
"""

from __future__ import annotations

QUALIFY = "QUALIFY"
ACCUMULATE = "ACCUMULATE"
CAP = "CAP"
SURCHARGE = "SURCHARGE"
ADJUST = "ADJUST"

#: Iteration order IS the pipeline order. Nothing sorts this at runtime.
STAGES: tuple[str, ...] = (QUALIFY, ACCUMULATE, CAP, SURCHARGE, ADJUST)
