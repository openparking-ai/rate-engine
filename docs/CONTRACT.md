# The rate engine contract

Version 1. One contract, three surfaces: `POST /v1/quote`, `POST
/v1/validate-plan`, and the `rate-engine` CLI. Our own platform is an ordinary
client of it — there is no private path and no in-process shortcut, so if this
interface is inadequate we find out before an integrator does.

**This module calculates. It takes no payment, holds no card, and stores
nothing.** A plan arrives on the call and is gone when the response is written.

<!--gen:schema_version-->
`schema_version` **1**
<!--/gen:schema_version-->

## Versioning, and the unknown key

This contract is versioned on the assumption that it will **gain fields**. A
commercial module's contract moves because businesses change, so consumers must
tolerate new fields appearing in a response.

The rule runs the other way for requests, and it is what makes the assumption
safe: **a key this engine does not understand is REJECTED and named, never
ignored.** An operator who adds `weekend_rate` to a plan running on a version
with no weekend rule would otherwise have a garage pricing weekends wrong and a
document saying it does not.

## Money

Money is an **integer of minor units** — 800 means 8.00. No float, no `Decimal`,
no string, at any depth of a plan, including in fields this version does not
read. A rate that cannot be expressed in minor units is a rate this module
refuses, and it refuses it at load rather than at the point the arithmetic goes
wrong. JSON exponent form (`8e2`) parses to a float and is refused with the rest.

## Time

Every plan names an **IANA timezone**, and entry and exit arrive as offset-aware
ISO 8601. A naive timestamp is refused: it would be read in whatever zone the
server happens to run in, which is a different fee on a different machine.

This is not incidental. `early_bird` speaks of "enter by 09:00" and `daily_max`
speaks of a day; both are wall-clock ideas, and a local day is 23 or 25 hours
across a daylight-saving transition. `daily_max` therefore requires the plan to
state whether a day means a local `calendar_day` or a `rolling_24h` window,
because those price a Friday-night-to-Saturday-morning stay differently and the
answer is the owner's to give.

## The pipeline

<!--gen:stages-->
**QUALIFY** → **ACCUMULATE** → **CAP** → **SURCHARGE** → **ADJUST**
<!--/gen:stages-->

The order is load-bearing: a cap that ran before the surcharge would cap a number
the customer is not being charged, and a surcharge applied after the cap is a
surcharge that survives it.

<!--gen:rule_types-->
| rule type | stage |
| --- | --- |
| `daily_max` | CAP |
| `early_bird` | QUALIFY |
| `increment` | ACCUMULATE |
| `space_surcharge` | SURCHARGE |

Stages with no rule type in this version: ADJUST.
<!--/gen:rule_types-->

## The plan document

Data, validated on load, never code. Every field is required and **there is no
default anywhere**, because a default is a pricing decision made by whoever wrote
the engine and applied to a garage whose owner never saw it. Where a plan is
silent, the engine refuses and names the field.

A plan states a resolution mode per stage, from: <!--gen:resolution-->
`cheapest_wins`, `stated_order`
<!--/gen:resolution-->. This
version validates that field and does not act on it — see "What this version does
not do".

## Gaps, conflicts, and the refusal

A **gap** is a stay the plan cannot price. A **conflict** is two rules qualifying
at one stage whose resolution the plan does not settle. One mechanism serves both
places it is needed: `validate-plan` reports them all so an owner can decide, and
at quote time an unresolved gap is a **refusal that names what is missing**.

**The engine never returns a number it had to guess.** That is this project's
standing acceptance, and in this module it is also the entire commercial
argument: a system that refuses when it is unsure can be trusted by someone who
cannot check its work.

<!--gen:findings-->
| code | kind |
| --- | --- |
| `GAP_UNDECLARED_SPACE_CLASS` | gap |
| `GAP_NO_ACCUMULATE_RULE` | gap |
| `GAP_STAY_EXCEEDS_MAX_DURATION` | gap |
| `GAP_NO_PLAN_IN_FORCE_AT_ENTRY` | gap |
| `CONFLICT_MULTIPLE_RULES_AT_STAGE` | conflict |
<!--/gen:findings-->

## A worked example

<!--gen:example-->
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
      is after the 17:00 limit. All of its conditions must hold, so the stay
      prices on the time-based rate                                                          --
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

<!--gen:guarantees-->
| id | what it proves |
| --- | --- |
| **F1** | The engine never guesses. A stay the plan cannot price is REFUSED, naming the gap, and no number is returned. |
| **F2** | A special rate is all-conditions-or-nothing. Miss one condition by a minute and it does not apply at all -- no pro-rating and no partial credit. |
| **F3** | The plan version in force at ENTRY prices the whole stay. A rate change mid-stay never splits it. |
| **F4** | Money is an integer of minor units. A float, a bool or a Decimal anywhere in a plan is refused at load. |
| **F5** | Determinism. The same plan version and the same stay produce the same fee AND the same breakdown, always, on any machine and at any wall-clock time. |
| **F6** | The test function IS the production path. `/v1/quote` and the CLI return the same bytes for the same request, from one code path and one serializer. |
| **F7** | Registering a new rule type changes no existing plan's answer -- fee and breakdown byte-identical. |
| **F8** | The fee is the sum of the breakdown's deltas, by construction. There is no second route to the total. |
<!--/gen:guarantees-->

## What this version does not do

Named here so nobody adds them helpfully:

- **No resolution of conflicts.** The modes are recorded and not applied. Two
  rules qualifying at one stage is a refusal in this version, because resolving
  it honestly needs two rule types that can qualify at once, which is round A2.
- **No weekend, holiday, event, weekly-max or occupancy rules.** Round A2.
- **No plan storage, no draft/approve workflow, no change log.** Round B. A plan
  arrives on the call.
- **No forecast and no competitor comparison.** Round C.
- **No rate import from a photograph.** Round D, and it will only ever produce a
  draft.
- **No grace period.** Deliberately absent: inventing a free interval is
  inventing a pricing decision nobody made. An operator who wants the first
  fifteen minutes free writes a first period of 15 minutes priced at 0, visibly,
  in the plan.
- **No validations, no monthly parkers, no payments, no card, no tax.**

## The occupancy multiplier, and why money stays an integer

Round A2's occupancy rule is a multiplier, and a multiplier is fractional. It
will be expressed as a **rational** — a numerator and a denominator, both whole —
with the rounding direction stated in the plan, exactly as `increment.rounding`
already is. It will not introduce a float, and it will not change what any plan
written against this version answers.

---

Built by 72 Knots Method by 72Knots.ai
