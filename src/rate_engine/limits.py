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

#: The most CAP rules (daily and weekly maximums) one plan may hold. Every cap
#: walks the stay a day at a time on every way it is priced, and a weekly cap
#: walks each daily cap's days again inside each week. Real plans hold one or two.
MAX_CAP_RULES_PER_PLAN = 16

#: How much work one quote may do, counted before any way is priced: the ways
#: plus one, times the plan's rules plus the days of the stay times the caps
#: that walk them (a weekly cap walking each daily cap's days). The largest
#: stress plan the tests price, 400 specials beside 400 that do not on a 90-day
#: stay with a daily and a weekly cap, comes to about 430,000.
MAX_QUOTE_WORK = 2_000_000

#: The most tax sets one statement may hold, and the most rules in one set. A
#: garage states a new set each time a tax changes, a handful a decade, and a set
#: holds its few taxes and fees.
MAX_TAX_SETS = 500
MAX_TAX_RULES_PER_SET = 64

#: Seconds a caller has to send its whole request, from the moment the HTTP
#: service accepts the connection. The per-read timeout alone let a caller that
#: sends one byte every few seconds hold a thread for as long as it liked.
REQUEST_DEADLINE_SECONDS = 30.0

#: Connections the HTTP service handles at once, each on its own thread. One more
#: is answered 503 at once and closed, rather than given a thread of its own.
MAX_CONNECTIONS = 64

#: The calendar years a stay may be priced in, and a special's dates named in.
#: Pricing works out local days and weeks around the stay, and near the ends of
#: the calendar -- year 1 and year 9999 -- that arithmetic runs off them. A stay
#: or a date outside is refused with a 400, never left to crash the request.
EARLIEST_YEAR = 1000
LATEST_YEAR = 9000
