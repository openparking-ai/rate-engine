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
every entry limit, every exit limit, every period length and stated ceiling, each
side of each, across every space class — and reports the gaps and conflicts it
finds **before** a plan goes live, so the owner decides rather than the software.
That is the same mechanism in both places, not two implementations that agree
today: a gap the validator reports and a gap a quote refuses on are the same
object with the same identifier.

**What it does not claim.** It is not a search over all possible stays, and no
bounded probe set could be. Those boundaries are where a rule starts or stops
qualifying, so a conflict a rule can currently express is one this finds — but a
future rule type that qualifies on something it does not DECLARE as a time or a
duration would need its own probe axis, and adding one is part of adding the rule
type. **This sentence used to say it reported every conflict, full stop, and that
was false:** every probe entered at 07:00, so two rules that both qualified only
for an early entry never overlapped in any probe, and a plan reported clean would
then refuse a real stay.

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

The CLI and the HTTP route are the same code path and return the same bytes.
There is no simulation mode: the function an operator types entry and exit into
**is** the production pricing path, and a test proves it by requiring the two to
be byte-identical over every fixture.

## What it does

- **Time-based increments** with a configurable first period and repeating
  period — "first 20 min, then each additional 20 min" and "first hour, then each
  additional hour" are one rule with different numbers.
- **Early bird**, and every special rate, is **all-conditions-or-nothing**. Miss
  the exit time by a minute and the rate does not apply at all.
- **Daily maximum**, stating whether a day means a local calendar day or a
  rolling 24 hours — because those price a Friday-night stay differently and the
  answer is the operator's.
- **Space-class surcharges.** This module prices a *space*, not a garage: a VIP
  area and a reserved spot are the same mechanism.
- **The plan in force at entry prices the whole stay.** A rate change never
  splits a stay or reaches back into a car that is already parked.

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
python scripts/fail_controls.py            # all eight, each planted and restored
python scripts/fail_controls.py --anchors  # are the plants still wired? (1 second)
```

A test that has never failed is a decoration. CI runs the suite, then the
fail-controls, then regenerates `docs/CONTRACT.md` and fails if a published
number or sentence has drifted from the code it describes.

## Licence

AGPL-3.0-or-later. Contributions welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md); a signed [CLA](CLA.md) is required.

Built by 72 Knots Method by 72Knots.ai
