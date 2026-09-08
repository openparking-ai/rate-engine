# Open Parking AI — rate engine

Price a parking stay, and **explain every line of the answer**.

Rates are where parking software confuses people. Every state handles them
differently, an operator changes them more often than anything else in the
system, and when a customer disputes a fee at the counter the attendant has a
number and no explanation. So this module does not return a fee. It returns the
fee and the plain-English reason for every part of it — **including the specials
that did not apply, and why**.

```
$ rate-engine quote --plan downtown.json \
    --entry 2026-03-03T09:14:00-05:00 --exit 2026-03-03T18:40:00-05:00 \
    --space-class standard --currency USD

  plan downtown-2026-02
  Entered 09:14 Tue 03 Mar, 566 minutes, space class 'standard', plan
      downtown-2026-02                                                                       --
  Early bird NOT applied: entry 09:14 is after the 09:00 entry limit; exit 18:40
      is after the 17:00 limit. All of its conditions must hold, so the stay
      prices on the time-based rate                                                          --
  Time-based: first hour 8.00 USD                                                      8.00 USD
  Time-based: 9 additional hours at 4.00 USD = 36.00 USD                              36.00 USD
  Daily max 30.00 USD (calendar_day) applied over the day: 44.00 USD reduced to
      30.00 USD                                                                      -14.00 USD

  FEE  30.00 USD
```

Those lines add up to the fee. That is not a check performed afterwards — **the
fee IS the running total of the breakdown**, and there is no other way for a rule
to change it.

## The engine never guesses

A rate plan that cannot price a stay produces a **refusal that names what is
missing**, never a number somebody would have had to invent:

```
  REFUSED -- nothing was guessed.

    [gap] GAP_NO_ACCUMULATE_RULE
      nothing prices the time for a 'reserved' space: no time-based rule covers
      that class and no special rate qualified
```

`rate-engine validate-plan` probes **every boundary the plan itself declares** —
every day a rule names, every entry limit at both ends, every exit limit, every
period length and stated ceiling, each side of each, across every space class —
and reports the gaps and conflicts it finds **before** a plan goes live, so the
owner decides rather than the software. That is the same mechanism in both
places, not two implementations that agree today: a gap the validator reports and
a gap a quote refuses on are the same object with the same identifier.

**What it does not claim.** It is not a search over all possible stays, and no
bounded probe set could be. Those boundaries are where a rule starts or stops
qualifying, so a conflict a rule can currently express is one this finds — but a
future rule type that qualifies on something it does not DECLARE as a day, a time
or a duration would need its own probe axis, and adding one is part of adding the
rule type. **That is not a hypothetical and it has been paid twice.** The first
time, every probe entered at 07:00, so two rules that both qualified only for an
early entry never overlapped in any probe and a plan reported clean would then
refuse a real stay. The second time, every probe entered on the same Tuesday: the
day became a thing a rule could qualify on, so the day became an axis in the same
round rather than in the outside pass after it.

## Install and run

No dependencies. Python 3.11 or newer.

```
pip install -e .
rate-engine validate-plan --plan your-plan.json
rate-engine quote --plan your-plan.json --entry ... --exit ... \
    --space-class standard --currency USD
```

Or over HTTP — `POST /v1/quote`, `POST /v1/validate-plan`:

```
python -c "from rate_engine.service import serve; serve()"
```

There is no simulation mode: the function an operator types entry and exit into
**is** the production pricing path, reached through one code path and one
encoder. Exactly what is byte-identical between the two doors, and where the
CLI's terminal newline sits, is stated once -- in `docs/CONTRACT.md`, guarantees
F6, F6b and F6c, generated from the tests that measure them. This page does not
restate it, because the hand-written second copy of a claim is the one that
drifts.

## What it does

- **Time-based increments** with a configurable first period and repeating
  period — "first 20 min, then each additional 20 min" and "first hour, then each
  additional hour" are one rule with different numbers.
- **One special rate, not seven.** Weekday, weekend, evening, morning, holiday,
  event and early bird differ in *which days* they apply on and *what hours* are
  typed into them, so they are one `time_window` rule with two fields rather than
  seven rule types. The window says WHEN — the days, both ends of the entry
  range, the exit limit, and how far past midnight it may run. **The engine never
  stores the word "weekend"**: it means Friday-to-Monday in one country and
  Saturday-to-Sunday in another, so a plan states the actual days. A holiday or
  an event states its own dates; there is no built-in calendar, because one would
  be right for a single country and wrong for every other.
- **And the effect says WHAT.** A window can be a flat price, *a completely
  different time-based rate* — the weekend priced in twenty-minute periods where
  the weekday is hourly, using the same period code so the two cannot drift — or
  an adjustment up or down on the whole fee. An adjustment runs **last**, after
  the caps and the surcharges, because a percentage taken any earlier is a
  percentage of a number the customer is not being charged. Percentages are
  integer basis points and the plan states which way a fraction of a cent goes.
- **A window is all-conditions-or-nothing.** Miss the exit time by a minute and
  the rate does not apply at all — no pro-rating, no partial credit, and not the
  cheaper of the two. The breakdown still carries a line saying which condition
  failed, because that is the question an attendant is actually asked.
- **Daily and weekly maximums**, each stating what a day or a week means — a
  local calendar day or a rolling 24 hours; a calendar week starting on the day
  the plan names, or a rolling seven days. Those price a Friday-night stay
  differently and the answer is the operator's, not ours: there is no universal
  first day of the week. **Two caps are not a conflict** — they are two ceilings,
  and the lower one wins whichever is applied first.
- **A grace period, if the plan declares one.** A stay at or under the stated
  minutes is free, and free means free: no surcharge, no cap, no adjustment. One
  minute over and it prices from entry on the ordinary rate. There is no default
  — "usually ten minutes" is an observation about other people's garages.
- **Space-class surcharges.** This module prices a *space*, not a garage: a VIP
  area and a reserved spot are the same mechanism.
- **The plan in force at entry prices the whole stay.** A rate change never
  splits a stay or reaches back into a car that is already parked.
- **When two rules qualify at once, what that MEANS depends on the stage.** Two
  specials competing to be the price is a conflict the plan settles. Two caps
  compose and nothing is reported. Two adjustments compose but the order changes
  the money, so the plan states the order and a plan that has not is refused.

Money is an integer of minor units everywhere. No float, no bool, no `Decimal`,
at any depth — a plan carrying one does not load, whether or not the field is one
this version reads.

See [docs/CONTRACT.md](docs/CONTRACT.md) for the full contract, and for what this
version deliberately does **not** do.

## Standalone, or integrated

One versioned contract, and everything is a client of it — including our own
platform, which gets no private path and no in-process shortcut. Any software
company can integrate with this module to calculate parking fees, whether or not
they run anything else of ours.

**Calculation only. No card, no payment, ever.** This module stores nothing: a
plan arrives on the call and is gone when the response is written.

## How it is verified

Every guarantee has a test **proven able to fail**, by breaking the thing it
guards and watching it go red:

```
python scripts/fail_controls.py            # each one planted, run, and restored
python scripts/fail_controls.py --anchors  # are the plants still wired? (1 second)
```

A test that has never failed is a decoration. CI runs the suite, then the
fail-controls, then regenerates `docs/CONTRACT.md` and fails if a published
number or sentence has drifted from the code it describes.

## Licence

AGPL-3.0-or-later. Contributions welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md); a signed [CLA](CLA.md) is required.

Built by 72 Knots Method by 72Knots.ai
