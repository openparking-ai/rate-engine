# The rate engine contract

Version 2. One contract, three surfaces: `POST /v1/quote`, `POST
/v1/validate-plan`, and the `rate-engine` CLI. Our own platform is an ordinary
client of it — there is no private path and no in-process shortcut, so if this
interface is inadequate we find out before an integrator does.

**This module calculates. It takes no payment, holds no card, and stores
nothing.** A plan arrives on the call and is gone when the response is written.

<!--gen:schema_version kind=1-->
`schema_version` **2**
<!--/gen:schema_version-->

## Versioning, and the unknown key

This contract is versioned on the assumption that it will **gain fields**. A
commercial module's contract moves because businesses change, so consumers must
tolerate new fields appearing in a response.

The rule runs the other way for requests, and it is what makes the assumption
safe: **a key this engine does not understand is REJECTED and named, never
ignored.** An operator who adds a key to a plan running on a version that has no
rule for it would otherwise have a garage pricing something wrong and a document
saying it does not.

### What changed in version 2

**A rule type was REMOVED, and that is why the number moved.** `early_bird` is
gone. It was a time window with its days hardcoded to every day and its effect
hardcoded to a flat price, and it is now expressible — with the days and the
effect stated — as a `time_window`. A plan written for version 1 does not load on
version 2: an unknown rule type is rejected rather than skipped, which is the
same rule that protects an unknown key.

No operator plans exist in the wild today, so removing a rule type costs nothing
now and could not be done quietly later. It is recorded here rather than left for
somebody to discover from a refusal.

**The other changes are additions.** `time_window` carries an `effect` that is a
flat price, a completely different time-based rate, or an adjustment up or down
on the whole fee — and the third of those brought the ADJUST stage live, so a
rule type now runs at a stage that depends on the rule rather than only on its
type. The stage is still stated in every plan, and the engine refuses a plan
whose stated stage disagrees with the one the rule's own shape implies.

Two rule types arrived with it: `grace`, and `weekly_max`. And two plan fields:
every plan now states `adjust_order`, null included, and `resolution` changed
shape.

**`resolution` is keyed by the RESOLVING stages only, and its values are
objects.** It used to require an entry for all five stages, as a bare mode
string, and to be acted on by nothing. It now decides which of several qualifying
rules applies — and the three stages it could never act on are refused as keys
this version does not understand, because a mode stated for CAP cannot choose
between two caps when both of them apply.

**Two classes of plan that used to be REFUSED now price, and that is a behaviour
change rather than a bug fix nobody notices.**

More than one rule qualifying at one stage was treated as a conflict at EVERY
stage. That is right where rules compete and wrong where they compose, and it was
harmless only while no second rule type existed at a composing stage.
`weekly_max` is that second type: without the fix, every plan carrying a daily
AND a weekly cap would have refused every stay in the garage.

And at a resolving stage, two rules at different prices are now settled by the
plan's mode instead of refused. `CONFLICT_MULTIPLE_RULES_AT_STAGE` therefore
means something narrower than it did: a TIE, which no mode can settle. The code
is unchanged and still reachable; what changed is how much it covers.

**A window that would have to wrap past midnight is REFUSED, and that is a stated
gap.** `enter_from` later than `enter_by` — "enter between 22:00 and 02:00" — is
not expressible as one rule. It is refused at load, naming the field, and the
message says to write it as two rules: one running to 23:59 and one starting at
00:00, each stating its own days. The engine will not split it, because which
days each half applies on is a pricing decision.

## Money

Money is an **integer of minor units** — 800 means 8.00. A float, a bool or a
`Decimal` is refused at **any depth of a plan**, including in fields this version
does not read; and a string where money is expected is refused with them. A rate
that cannot be expressed in minor units is a rate this module refuses, and it
refuses it at load rather than at the point the arithmetic goes wrong. JSON
exponent form (`8e2`) parses to a float and is refused with the rest.

## Time

Every plan names an **IANA timezone**, and entry and exit arrive as offset-aware
ISO 8601. A naive timestamp is refused: it would be read in whatever zone the
server happens to run in, which is a different fee on a different machine.

This is not incidental. `time_window` speaks of "enter by 09:00" and `daily_max`
speaks of a day; both are wall-clock ideas, and a local day is 23 or 25 hours
across a daylight-saving transition. `daily_max` therefore requires the plan to
state whether a day means a local `calendar_day` or a `rolling_24h` window,
because those price a Friday-night-to-Saturday-morning stay differently and the
answer is the owner's to give.

## The pipeline

<!--gen:stages kind=1-->
**QUALIFY** → **ACCUMULATE** → **CAP** → **SURCHARGE** → **ADJUST**
<!--/gen:stages-->

The order is load-bearing: a cap that ran before the surcharge would cap a number
the customer is not being charged, and a surcharge applied after the cap is a
surcharge that survives it.

<!--gen:rule_types kind=2-->
| rule type | stage |
| --- | --- |
| `daily_max` | CAP |
| `grace` | QUALIFY |
| `increment` | ACCUMULATE |
| `space_surcharge` | SURCHARGE |
| `time_window` | QUALIFY or ADJUST |
| `weekly_max` | CAP |

Every stage has at least one rule type in this version.
<!--/gen:rule_types-->

## The plan document

Data, validated on load, never code. Every field is required and **there is no
default anywhere**, because a default is a pricing decision made by whoever wrote
the engine and applied to a garage whose owner never saw it. Where a plan is
silent, the engine refuses and names the field.

A plan states a resolution mode for each stage that can RESOLVE — QUALIFY and
ACCUMULATE — from: <!--gen:resolution kind=1-->
`cheapest_wins`, `stated_order`
<!--/gen:resolution-->. A mode stated for any other stage is
refused by name: CAP, SURCHARGE and ADJUST compose, so a mode there could never
choose anything, and a field that cannot change an answer is a decision the owner
made and the software ignored.

- `{"mode": "cheapest_wins"}` — the **lowest fee for the customer** wins.
- `{"mode": "stated_order", "order": [...]}` — the plan names the rule ids and
  the first that qualifies wins. It must name every rule at that stage **exactly
  once**; a rule left out would take a silent position in the order.

**What `cheapest_wins` compares, stated because it is a limit.** It compares what
the competing rules themselves charge for the stay — not the final fee. A cap or
an adjustment downstream applies to whichever rule wins and could in principle
bring two different bases to the same number; comparing final fees would mean
running the whole pipeline once per candidate, and would still not be "the
customer's fee" for the rules that lost. Two rules charging the SAME amount
cannot be separated by it and are refused, naming both.

`adjust_order` is a different thing and is stated separately: a list of rule ids,
or null, giving the sequence the ADJUST rules run in. **An order is not a
choice**, which is why it does not live in `resolution`. It is
required-and-nullable like `max_duration_minutes` and `week_starts_on` — a field
that may simply be absent is one somebody forgets while believing they set it —
and when it is stated it must name every ADJUST rule exactly once, because a rule
left out would take a silent position in the sequence.

## Gaps, conflicts, and the refusal

A **gap** is a stay the plan cannot price. A **conflict** is two rules qualifying
at one stage whose resolution the plan does not settle. One mechanism serves both
places it is needed: `validate-plan` reports them so an owner can decide, and at
quote time a gap is a **refusal that names what is missing**.

**More than one rule qualifying at one stage means three different things, and
the stage decides which.** This used to be one answer for all five stages, and it
was wrong in a way that only a second rule type could expose:

- **QUALIFY and ACCUMULATE resolve.** Two rules are a genuine either/or -- only
  one of them can be the price -- so it is a conflict and the plan settles it.
- **CAP and SURCHARGE compose, in any order.** Two caps are not a contradiction;
  they are two ceilings, and the lower one wins whichever ran first. Nothing is
  reported, because there is nothing for an owner to decide. Their lines are
  emitted in ascending rule id, never in the order the caller's array happened to
  carry them.
- **ADJUST composes, and the order changes the money.** Twenty per cent off then
  five dollars off is not five dollars off then twenty per cent off, so two
  qualifying adjustments with no stated `adjust_order` are REFUSED under their
  own code -- a different question from "which of these is the price", and a
  consumer routing on codes can tell them apart.

**A TERMINAL rule is not a conflict either.** It wins outright by what its type
is, rather than by anything the plan says, so a grace period beating a weekend
rate is settled and the beaten rule gets a line saying so.

**And at a resolving stage the plan's MODE settles it**, so two windows at
different prices are priced rather than refused. What is left is the case no mode
can settle: two rules that qualify and charge the SAME amount under
`cheapest_wins`. There is nothing to be cheapest about, the engine will not pick,
and the refusal names both and says that stating an order would settle it.

**Every rule that lost is still on the receipt**, naming the winner, both prices
and the mode that chose — a breakdown that silently omitted a rate the customer
nearly got could not answer the question an attendant is actually asked.

`validate-plan` probes every boundary the plan DECLARES -- each entry limit, each
exit limit, each period length and stated ceiling, either side of each, across
every space class -- rather than a written list of scenarios or a search over all
stays. That is exhaustive over what a rule can express today and is not a claim
about every possible stay; the probe axes are derived from the rules, so a rule
type qualifying on something new brings its own axis.

**Deciding a finding does not resolve it.** `decisions[]` records that an owner
has seen a gap — `validate-plan` reports it as SETTLED rather than OUTSTANDING,
so a list can be worked through — and that is all it does. A decision carries a
code and a free-text note, and a note cannot price a stay; a stay hitting a
settled gap is refused exactly as one hitting an outstanding gap is. The way to
make a gap priceable is to add a **rule** that covers it, which is a visible plan
change. See F12 and F12b.

**The engine never returns a number it had to guess.** That is this project's
standing acceptance, and in this module it is also the entire commercial
argument: a system that refuses when it is unsure can be trusted by someone who
cannot check its work.

<!--gen:findings kind=2-->
| code | kind |
| --- | --- |
| `GAP_UNDECLARED_SPACE_CLASS` | gap |
| `GAP_NO_ACCUMULATE_RULE` | gap |
| `GAP_STAY_EXCEEDS_MAX_DURATION` | gap |
| `GAP_NO_PLAN_IN_FORCE_AT_ENTRY` | gap |
| `CONFLICT_MULTIPLE_RULES_AT_STAGE` | conflict |
| `CONFLICT_AMBIGUOUS_PLAN_SELECTION` | conflict |
| `CONFLICT_NEGATIVE_TOTAL` | conflict |
| `CONFLICT_UNORDERED_ADJUSTMENTS` | conflict |
| `FAULT_RULE_RETURNED_NOT_LINES` | fault |
<!--/gen:findings-->

## A worked example

<!--gen:example kind=2-->
```
POST /v1/quote
{
  "plans": [
    "<the plan document>"
  ],
  "entry_at": "2026-03-03T09:14:00-05:00",
  "exit_at": "2026-03-03T18:40:00-05:00",
  "space_class": "standard",
  "currency": "USD"
}
```

```
  Entered 09:14 Tue 03 Mar, 566 minutes, space class 'standard', plan
      downtown-2026-02                                                                       --
  Early bird NOT applied: entry 09:14 is after the 09:00 entry limit; exit 18:40
      on Tue 03 Mar is after the 17:00 limit on Tue 03 Mar. All of its
      conditions must hold, so the stay prices on the time-based rate                        --
  Time-based: first hour 8.00 USD                                                      8.00 USD
  Time-based: 9 additional hours at 4.00 USD = 36.00 USD                              36.00 USD
  Daily max 30.00 USD (calendar_day) applied over the day: 44.00 USD reduced to
      30.00 USD                                                                      -14.00 USD

  FEE  3000 minor units (USD)
```

The lines above sum to 3000, which is the fee. That is not a coincidence and not a check performed afterwards: the fee IS the running total of the breakdown, and the engine asserts it on every quote.
<!--/gen:example-->

## The guarantees

Each of these has a test proven able to fail, by planting the defect it guards
against and requiring red — `python scripts/fail_controls.py`. A test that has
never failed is a decoration.

<!--gen:guarantees kind=1-->
| id | what it proves |
| --- | --- |
| **F1** | The engine never guesses. A stay the plan cannot price is REFUSED, naming the gap, and no number is returned. |
| **F10** | Plan selection is never ambiguous. Two versions in force at the same instant are REFUSED and both named, never resolved by the order of the caller's list. |
| **F11** | An ambiguity the PLAN cannot settle is REFUSED and both rules named, with the stated mode quoted back and the refusal saying what would settle it. Since the modes act, that means a TIE: two rules qualifying at one stage and charging the same amount, which `cheapest_wins` cannot separate. |
| **F12** | `validate-plan` separates the findings an owner has still to look at from the ones they have recorded a decision for. Every finding is reported either way. |
| **F12b** | A decision is an ACKNOWLEDGEMENT, not a price. A stay hitting a SETTLED gap is refused exactly as one hitting an outstanding gap is; no entry in `decisions[]` can cause a fee to be produced. |
| **F13** | The fixture corpus holds a case either side of every threshold the rules branch on, read out of the plans rather than from a list -- so no guarantee is proven against a corpus that could only ever exercise one branch. |
| **F14** | A registered guarantee whose test stops running turns the build RED, including when its module fails to import; and a test module that plants a defect but registers no guarantee is refused. |
| **F15** | `increment.rounding` is CONSULTED by the applier, which refuses a mode it does not implement rather than pricing the stay under a different one. The applier checks what it implements, never what the loader accepts. |
| **F16** | Every refusal reaches the caller AS a refusal. A malformed number anywhere in a plan comes back as a named 400 naming the field, and a malformed rule return as a named 422 -- never as an exception escaping the quote contract, and never as a dropped connection. |
| **F17** | A rendered amount uses its own currency's ISO 4217 minor-unit exponent, never an assumed two decimal places -- and a code whose exponent this module does not know is REFUSED at load rather than rendered on a guess. |
| **F17b** | That refusal is at LOAD, so an unrenderable currency never reaches the renderer at all -- the membership check and the exponent read one table. |
| **F18** | A wall-clock limit is compared at the granularity it is written and rendered in: the stay is truncated to the minute, so no breakdown line can say a time is after itself. |
| **F18b** | And the LIMIT is refused rather than truncated. A plan may state 'HH:MM'; anything finer is rejected at load, because rounding it would silently discard a pricing decision the operator wrote. |
| **F19** | `validate-plan` probes every boundary the plan DECLARES -- entry limits and exit limits as well as durations, each side of each -- so a conflict the engine would refuse is one the owner was shown before the plan went live. |
| **F2** | A special rate is all-conditions-or-nothing: miss one condition by a minute and it does not apply at all -- no pro-rating and no partial credit. Enforced per rule type; `time_window` is the only special this module ships, so the property is proven of it rather than of a populated stage. |
| **F20** | There are TWO time roundings and both are declared: a part-minute is a whole minute (assumed, module-wide) and minutes into periods is stated per rule. Every comparison against a duration reads the same rounded value. |
| **F21** | A refusal's CODE names the cause that actually occurred. A negative total is CONFLICT_NEGATIVE_TOTAL, not the multi-rule conflict code it borrowed. |
| **F22** | Whether a non-qualifying rule appears in the breakdown depends on its STAGE: a QUALIFY rule always speaks, at delta zero; a rule at another stage that does not cover the stay is silent. |
| **F22b** | And the stage is not the whole answer. A rule TYPE may declare that it speaks when it did not qualify, so a weekend discount declining because it is a Tuesday says so on the receipt -- while a rule that was never about this space stays silent whatever it declared. |
| **F23** | The production invariant that the fee IS the ledger's sum is itself guarded: deleting it, no-opping it or unwiring it from the pricing path turns the suite red. |
| **F24** | A zero-length stay pays the first period -- a decision, published in the contract with the divergence it was disclosed with, not left for an integrator to discover as an anomaly. |
| **F25** | Whether a time window may run past midnight is stated by the PLAN, in `day_span`, with no default -- the engine holds no day condition of its own. `day_span` also says WHERE the exit limit falls: under a bounded span it is `exit_by` on the entry date plus the span, so a limit past midnight is a moment rather than a clock reading. `any_span` names no last day and keeps the clock reading. |
| **F26** | A window applies on the days the PLAN states -- weekday names, or the garage's own dates for a holiday or an event -- matched against the ENTRY's local date, and a window that did not match names the day that failed and the days it wanted. There is no built-in calendar and no preset: 'weekend' means different days in different countries. |
| **F27** | `enter_from` is CONSULTED, not merely validated and stored. A window states BOTH ends of its entry range, which is what makes an evening rate expressible, and a stay arriving one minute before it opens does not qualify. |
| **F28** | `day_span` `next_day` is BOUNDED: an exit on the following local day qualifies and one the day after that does not, where `any_span` accepts both. Proven on one stay, so the three spans are an axis rather than three unrelated scenarios. |
| **F29** | A `rate` effect is priced by `increment`'s own builder and applier, not by a copy of them: identical parameters produce identical lines on the same stay, and a change to `increment`'s period counting moves the window's lines with it. |
| **F3** | The plan version in force at ENTRY prices the whole stay. A rate change mid-stay never splits it. |
| **F30** | An `adjust` effect applies to the fee AFTER the caps and the surcharges. A percentage taken any earlier is a percentage of a number the customer is not being charged. |
| **F31** | An `adjust` percentage is integer basis points and its `rounding` is CONSULTED: the same stay under `up` and under `down` differs by one minor unit, and the breakdown line says which way it went. |
| **F32** | `grace` is TERMINAL, and free means free: a stay at or under the stated minutes costs zero and picks up no surcharge, no cap and no adjustment. Terminality is DECLARED by the rule type at registration -- the engine never knows its name -- and a special it beat says so on the receipt. |
| **F33** | Two caps on one stay leave the LOWER ceiling standing, the total after CAP is the same in both application orders, and the breakdown names both. Caps COMPOSE; two of them are not a conflict. |
| **F34** | More than one rule qualifying at one stage means three different things, and the stage's category decides which: RESOLVING is a conflict, COMPOSING order-independent is not reported at all, and COMPOSING order-dependent is refused unless the plan states the order. |
| **F35** | Two qualifying ADJUST rules with no stated `adjust_order` are REFUSED naming both; with an order they produce that order's total, and the two orders genuinely differ -- 20% off then a fixed amount is not the same fee as the fixed amount then 20% off. |
| **F36** | The resolution modes DECIDE. Two windows qualifying on one stay resolve to the cheaper under `cheapest_wins` and to the stated one under `stated_order`, on the SAME stay -- and the rules that lost still appear, each naming the winner, both prices and the mode that chose. |
| **F37** | A `stated_order` must name every rule at its stage EXACTLY ONCE, and one that does not is refused at LOAD, naming what is missing. A rule left out would take a silent position, and array position deciding money is what this module refuses everywhere else. |
| **F38** | Every identifier the published documents name in backticks is one the code actually holds -- rule types, stages, finding codes, plan and rule fields, stated values, traits and guarantee ids -- and every file path they point at exists. Derived from both documents rather than from a list of the sentences somebody remembered to check. |
| **F39** | A window's exit limit runs to the day its `day_span` allows. Under a bounded span the limit is `exit_by` on the entry date plus the span, so an evening window with an after-midnight limit applies to the car that leaves the SAME evening as well as the one that leaves after midnight. A limit that would have to WRAP to be reached is refused at load under `same_day` and `any_span`, neither of which can say what day it falls on. |
| **F4** | Money is an integer of minor units. A float, a bool or a Decimal anywhere in a plan is refused at load. |
| **F4b** | That sentence is true at EVERY leaf of a plan, not at the fields the engine happens to read -- proven by probing every position in the document, so a field added in a later round is covered the day it exists. |
| **F5** | Determinism. The same plan version and the same stay produce the same fee AND the same breakdown, always, on any machine and at any wall-clock time. |
| **F6** | The test function IS the production path. `/v1/quote` and the CLI emit the same response bytes for the same request, from one code path and one encoder; the CLI's terminal newline is written outside the payload. |
| **F6b** | And there is exactly ONE encoder. No surface re-implements the response bytes, so the two doors cannot drift the way they silently did. |
| **F6c** | The CLI's payload is the route's payload BYTE FOR BYTE, with any terminal newline written outside it -- compared as bytes, never as decoded objects. |
| **F7** | Registering a new rule type changes no existing plan's answer -- fee and breakdown byte-identical. |
| **F8** | The fee is the sum of the breakdown's deltas, by construction. There is no second route to the total. |
| **F8b** | A rule's only channel to the fee is a list of Lines. A malformed return is REFUSED by name, not left to crash inside the ledger. |
| **F9** | The published contract is DERIVED, never transcribed. Every generated block matches the code, and every block that ASSERTS something about its values is proven to move when those values contradict it. |
<!--/gen:guarantees-->

## What this version does not do

Named here so nobody adds them helpfully:

- **No occupancy-driven rule.** Not in this version.
- **No plan storage, no draft/approve workflow, no change log.** Round B. A plan
  arrives on the call.
- **No forecast and no competitor comparison.** Round C.
- **No rate import from a photograph.** Round D, and it will only ever produce a
  draft.

## Grace, and what "free" means

A plan may declare a grace period: `minutes`, a positive whole number, with **no
default and no grace unless the plan states the rule.** "Usually ten minutes" is
an observation about other people's garages, not a value to assume.

**A stay at or under that many minutes costs nothing, and nothing means nothing.**
Grace is TERMINAL: the pipeline stops after QUALIFY, so a graced stay in a VIP
space does not pick up the surcharge, does not reach a cap, and is not adjusted.
A receipt for a graced stay carries the grace line and nothing else. It also
beats any other special that qualified — and that special is not dropped
silently; it gets a line naming the rule that superseded it.

**All-or-nothing.** One minute over a ten-minute grace and the stay prices from
ENTRY on the ordinary rate, not from minute ten. That is the ordinary garage
convention and it is the same all-conditions rule every special here keeps.

**A grace of ten minutes covers 600.000 seconds and not 600.001.** Durations are
whole minutes rounded UP, module-wide, before any rule sees a stay — so a stay of
ten minutes and one millisecond is eleven minutes and misses a ten-minute grace.
That is coherent with every other duration comparison here, including the stated
ceiling on a time-based rule, and it is recorded rather than adjusted.

## A stay of zero length pays the first period

**Entry and exit at the same instant is priced, not free, and not refused.** The
first period covers `[0, first_period_minutes]`, so a car that enters and leaves
without stopping pays `first_period_minor` -- the same as a car that stayed one
minute or fifty-nine.

It is a DECISION, and it is published here because an integrator cannot otherwise
learn it: the number is correct under the rule as written, and it is the kind of
edge a garage owner will be asked about at the counter.

**It diverges from the platform's own older fee code, which returns zero for the
same stay.** That divergence is known and is a later round's to reconcile; it is
recorded rather than left for whoever notices the two answering differently.

A negative stay -- exit before entry -- is a different thing and is REFUSED as a
caller bug rather than priced at zero, because pricing it would hide it.

**And this paragraph now describes only a plan that declares NO grace.** A garage
that declares one makes a zero-length stay free by the grace rule, because zero
is at or under any positive number of minutes. Both behaviours are deliberate,
both are tested, and which one a garage gets is stated in its own plan rather
than assumed here.
- **No validations, no monthly parkers, no payments, no card, no tax.**

## The first money rounding, and why money stays an integer

**A percentage adjustment is the first thing in this module that rounds MONEY,
and it arrives with the version bump §2 says a commercial contract makes.** Every
rule before it was an integer add or an integer replace, and `money.py` said in
as many words that this module rounds no money anywhere. That sentence is now
qualified rather than deleted: it rounds money in exactly one place, the place is
named, and the direction is the plan's to state.

**A percentage is INTEGER BASIS POINTS.** 20% is `2000`; 12.5% is `1250`. Not a
decimal, because a float anywhere in a plan is refused at load — so a percent
field that could hold `20.5` would either be rejected or would put a float into
the pricing path through a field nobody was watching. The arithmetic is
`total * percent_bp // 10000` with the division rounded the way the rule says,
and no float is constructed at any point.

**`rounding` is stated per rule with no default**, because a percentage of a fee
lands on a fraction of a minor unit and who keeps that fraction is the owner's
decision. The breakdown line says which way it went and by how much, so a
customer disputing a cent can be shown the answer rather than told it.

**That rounding is not the rounding this module already had.**
`increment.rounding` rounds TIME into whole periods: it decides that a 61-minute
stay is two hours. **The applier reads that field and refuses a mode it does not
implement**, so adding a mode to the ones a plan may state is a real change
rather than a plan that quietly keeps pricing as `ceil` (F15). The two roundings
share a word and nothing else.

**One wart, recorded rather than hidden:** `rounding` is required on every
`adjust` effect, and a `fixed` amount has nothing to round — on that shape the
field is stated and never read. It is written down here rather than left for a
reader to notice.

Money stays an integer of minor units at every depth. Nothing here introduces a
float, and nothing here changes what a plan written against the previous version
answers, because such a plan no longer loads at all — see "What changed in
version 2".

---

Built by 72 Knots Method by 72Knots.ai
