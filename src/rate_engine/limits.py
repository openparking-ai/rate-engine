"""How big a request may be, stated once.

Every number here is far above any plan or tax statement a garage writes -- the
largest real plan this repository carries has a handful of rules and three space
classes -- and each exists because the work the engine does grows with it. A
document over one of them is REFUSED with a sentence naming the limit, never
priced by a truncated reading of it: dropping the rules past the limit would be
a price nobody stated.

`docs/CONTRACT.md` publishes these values, generated from this file.
"""

from __future__ import annotations

#: The most rules one plan may hold. The work of a quote grows with the ways a
#: plan offers times its rules (F64), and the longest stress plan the tests price
#: holds 803.
MAX_RULES_PER_PLAN = 2000

#: The most space classes one plan may name. `validate-plan` probes every class.
MAX_SPACE_CLASSES = 64

#: The most dates one rule's `applies_on` may list, and the most across a plan.
#: A year of event days is 366; every date a plan names is a day it is probed on.
MAX_DATES_PER_RULE = 400
MAX_DATES_PER_PLAN = 2000

#: How much work one `validate-plan` may do, counted before any probe is built:
#: probe stays times the plan's rules, since every probe asks every rule. The
#: largest plan the tests validate does 5,550.
MAX_VALIDATION_WORK = 200_000

#: Wall-clock seconds a validation may run before it is abandoned. A backstop
#: under `MAX_VALIDATION_WORK`, which is what a plan is judged by; this only
#: fires on a machine far slower than the one the budget was measured on.
VALIDATION_DEADLINE_SECONDS = 10.0

#: Validations the HTTP service runs at once. A validation is CPU work that every
#: quote in the process shares, so a few at a time keeps an exit close's quote
#: answering while a rate setup checks a plan; one more is answered 503 at once.
MAX_CONCURRENT_VALIDATIONS = 2
