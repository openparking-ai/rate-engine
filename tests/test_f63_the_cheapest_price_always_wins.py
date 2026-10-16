"""F63 -- the cheapest price always wins.

Gokhan, 2026-10-16: **when more than one price could apply to the same time, the
car pays the cheapest.** His example: "a $50 Friday-to-Sunday flat special with a
$30 daily max pays the cheaper of the two" -- 30.00. Until this, a flat special
was one price for the stay with no day it was charged in, capped at the max
times the days the car was in: 90.00 for those three days, so the 50.00 stood.

Every place the engine chooses between prices for the same time was audited.
Three were not the cheapest, and this file pins each:

* **A flat special against a daily or weekly max.** A flat price is owed in full
  from the minute the car comes in, so the caps find it on the day of entry and
  cap it there. Of every way to put a flat price into days, all of it on one is
  the cheapest, for every cap at once -- each day pays at most the max, so no
  split comes to less than the price capped once.
* **Two specials, or two time-based rates, for one stay.** They were compared on
  what the RULES charged, and only the special that won was compared with the
  time-based rate on the fee. A cap can make the rule that charges more the
  cheaper stay. Every way is now priced through the whole pipeline and the
  lowest FEE charged; the losing rule's line says what the stay comes to by
  each, where the rules' own prices do not say why it lost.
* **`stated_order`.** The plan's order chose outright, so a dearer special
  replaced a cheaper one, and the time-based rate, whatever the driver paid.
  The cheapest is charged under either mode; the order names one of two ways
  that charge the same (F36).

And what is NOT a choice stays as it was: a surcharge and a fixed increase are
added; the caps already leave the lowest ceiling standing; the discounts apply
in the plan's stated order. Both halves are pinned below, and a sweep checks the
rule itself: the fee is the least of the fees each way charges on its own.

`scripts/fail_controls.py` puts back the flat price capped at the max times the
days, the rules' own charges deciding, the stated order deciding, the losing
line without the whole stay, and a tie named by id alone, and requires this file
to go red each time.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.contract import run_quote
from rate_engine.plan import parse_instant

EVERY_DAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard", "vip"], "first_period_minutes": 60,
    "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}


def _daily(max_minor: int = 3000, boundary: str = "calendar_day") -> dict:
    return {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
            "space_classes": ["standard", "vip"], "max_minor": max_minor,
            "day_boundary": boundary}


def _weekly(max_minor: int = 10000) -> dict:
    return {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
            "space_classes": ["standard", "vip"], "max_minor": max_minor,
            "week_boundary": "calendar_week", "week_starts_on": "mon"}


def _window(rule_id: str, label: str, days: list[str], effect: dict, **times) -> dict:
    return {
        "id": rule_id, "type": "time_window", "stage": "QUALIFY",
        "space_classes": ["standard", "vip"], "label": label,
        "applies_on": {"kind": "days_of_week", "days": days},
        "enter_from": times.get("enter_from", "00:00"),
        "enter_by": times.get("enter_by", "23:59"),
        "exit_by": times.get("exit_by", "23:59"),
        "day_span": times.get("day_span", "any_span"),
        "effect": effect,
    }


def _flat(price_minor: int) -> dict:
    return {"kind": "flat", "price_minor": price_minor}


def _rate(per_hour_minor: int, first_minor: int | None = None) -> dict:
    return {"kind": "rate", "first_period_minutes": 60,
            "first_period_minor": per_hour_minor if first_minor is None else first_minor,
            "repeat_period_minutes": 60, "repeat_period_minor": per_hour_minor,
            "rounding": "ceil", "max_duration_minutes": None}


#: The decision's own special: a flat 50.00 for a car in on a Friday evening.
WEEKEND_FLAT = _window("weekend-flat", "Weekend flat", ["fri"], _flat(5000),
                       enter_from="17:00")


def _plan(*rules: dict, resolution: dict | None = None, adjust_order=None) -> dict:
    return {
        "plan_version": "cheapest-2026-10",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard", "vip"],
        "resolution": resolution or {"QUALIFY": {"mode": "cheapest_wins"},
                                     "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": adjust_order,
        "rules": [copy.deepcopy(r) for r in rules],
        "decisions": [],
    }


def _quote(plan: dict, entry: str, exit_: str, space_class: str = "standard") -> dict:
    status, body = run_quote(
        {"plans": [copy.deepcopy(plan)], "entry_at": entry, "exit_at": exit_,
         "space_class": space_class, "currency": "USD"}
    )
    assert status == 200, body
    return body


def _line(body: dict, rule_id: str, code: str | None = None) -> dict:
    return next(
        ln for ln in body["breakdown"]
        if ln["rule_id"] == rule_id and (code is None or ln["code"] == code)
    )


def _applied(body: dict) -> list[str]:
    return [ln["rule_id"] for ln in body["breakdown"] if ln["code"] == "time_window.applied"]


# Friday 10 April 2026, 18:00, to Sunday 12 April, 20:00: three calendar days.
FRIDAY_1800, SUNDAY_2000 = "2026-04-10T18:00:00-04:00", "2026-04-12T20:00:00-04:00"


# --- a flat special against the caps ------------------------------------------


@pytest.mark.guarantee("F63")
def test_a_50_friday_to_sunday_flat_with_a_30_daily_max_pays_30():
    """The decision's own example. The flat 50.00 is owed when the car comes in,
    so Friday holds all of it and pays the 30.00 max; Saturday and Sunday hold
    nothing. It was the max times the three days, 90.00, and the 50.00 stood."""
    body = _quote(_plan(WEEKEND_FLAT, _daily()), FRIDAY_1800, SUNDAY_2000)
    assert body["fee_minor"] == 3000
    cap = _line(body, "cap-daily")
    assert cap["code"] == "daily_max.applied"
    assert "50.00 USD reduced to 30.00 USD" in cap["text"], cap["text"]
    assert "(30.00 USD + 2 x 0.00 USD: each day is capped on its own)" in cap["text"]


@pytest.mark.guarantee("F63")
def test_beside_the_hourly_rate_the_capped_flat_is_still_the_cheaper_way():
    """By the hour the same stay is 28.00 + 30.00 + 30.00 = 88.00 at the cap; the
    flat, capped, is 30.00 -- charged, and the line says what the hour was."""
    body = _quote(_plan(WEEKEND_FLAT, HOURLY, _daily()), FRIDAY_1800, SUNDAY_2000)
    assert body["fee_minor"] == 3000
    used = _line(body, "weekend-flat", "special_used")
    assert used["compared_minor"] == 8800, used


@pytest.mark.guarantee("F63")
def test_a_flat_under_the_max_is_charged_as_it_is():
    """The cap is a ceiling, never a price: a 20.00 flat over the same three
    days is 20.00, and the cap was not reached."""
    flat = copy.deepcopy(WEEKEND_FLAT)
    flat["effect"]["price_minor"] = 2000
    body = _quote(_plan(flat, _daily()), FRIDAY_1800, SUNDAY_2000)
    assert body["fee_minor"] == 2000
    assert _line(body, "cap-daily")["code"] == "daily_max.not_reached"


@pytest.mark.guarantee("F63")
def test_a_rolling_day_caps_the_flat_the_same_way():
    body = _quote(_plan(WEEKEND_FLAT, _daily(boundary="rolling_24h")), FRIDAY_1800,
                  SUNDAY_2000)
    assert body["fee_minor"] == 3000


@pytest.mark.guarantee("F63")
def test_a_weekly_max_caps_a_flat_on_the_week_of_entry():
    """A 150.00 flat from Friday to the Sunday nine days later touches two Monday
    weeks. A weekly max of 100.00 alone: 100.00, where the max times the two
    weeks, 200.00, let the 150.00 stand. With the 30.00 daily max too: 30.00."""
    flat = copy.deepcopy(WEEKEND_FLAT)
    flat["effect"]["price_minor"] = 15000
    exit_ = "2026-04-19T20:00:00-04:00"
    assert _quote(_plan(flat, _weekly()), FRIDAY_1800, exit_)["fee_minor"] == 10000
    assert _quote(_plan(flat, _daily(), _weekly()), FRIDAY_1800, exit_)["fee_minor"] == 3000


# --- two ways of pricing the time, compared on the whole fee ------------------

#: A Saturday event at a flat 100.00, and a weekend rate of 1.00 an hour.
EVENT = _window("event", "Event rate", ["sat"], _flat(10000))
WEEKEND_RATE = _window("weekend", "Weekend rate", ["sat"], _rate(100))
SATURDAY, MONDAY_AFTER = "2026-04-11T00:00:00-04:00", "2026-04-13T00:00:00-04:00"


@pytest.mark.guarantee("F63")
def test_two_specials_are_compared_on_the_WHOLE_FEE_not_on_what_they_charge():
    """Saturday and Sunday, 48 hours. The weekend rate charges 48.00 and the
    event 100.00 -- and with 30.00 a day the event's stay comes to 30.00 (all of
    it on Saturday, capped) and the weekend rate's to 24.00 + 24.00 = 48.00. The
    event is charged. Compared on what the rules charge, it was 48.00."""
    body = _quote(_plan(EVENT, WEEKEND_RATE, _daily()), SATURDAY, MONDAY_AFTER)
    assert body["fee_minor"] == 3000
    assert _applied(body) == ["event"]
    lost = _line(body, "weekend", "resolved")
    assert lost["text"] == (
        "Weekend rate qualified at 48.00 USD -- Event rate 100.00 USD applied instead: "
        "with the rest of the plan this stay comes to 30.00 USD by Event rate and "
        "48.00 USD by Weekend rate (plan resolves QUALIFY by cheapest_wins)"
    ), lost["text"]


@pytest.mark.guarantee("F63")
def test_without_the_cap_the_rule_that_charges_less_is_the_cheaper_stay():
    """The control on the item above: nothing between the rules and the fee, so
    the weekend rate's 48.00 is the cheaper stay, and its line needs no more
    than the two prices."""
    body = _quote(_plan(EVENT, WEEKEND_RATE), SATURDAY, MONDAY_AFTER)
    assert body["fee_minor"] == 4800
    lost = _line(body, "event", "resolved")
    assert lost["text"] == (
        "Event rate qualified at 100.00 USD -- Weekend rate 48.00 USD applied instead "
        "(plan resolves QUALIFY by cheapest_wins)"
    ), lost["text"]


#: Two time-based rates: 100.00 for the first hour and 0.50 an hour after, and
#: 2.00 an hour throughout. Over two days the first charges 123.50 and the
#: second 96.00.
FRONT_LOADED = {**HOURLY, "id": "front-loaded", "first_period_minor": 10000,
                "repeat_period_minor": 50}
EVEN = {**HOURLY, "id": "even", "first_period_minor": 200, "repeat_period_minor": 200}
MONDAY, WEDNESDAY = "2026-04-06T00:00:00-04:00", "2026-04-08T00:00:00-04:00"


@pytest.mark.guarantee("F63")
def test_two_time_based_rates_are_compared_on_the_whole_fee_too():
    """At 30.00 a day the front-loaded rate's Monday is 111.50 and pays 30.00,
    and its Tuesday 12.00: 42.00. The even rate pays 30.00 both days: 60.00.
    Compared on what the rules charge, 96.00 against 123.50, it was 60.00."""
    body = _quote(_plan(FRONT_LOADED, EVEN, _daily()), MONDAY, WEDNESDAY)
    assert body["fee_minor"] == 4200
    lost = _line(body, "even", "resolved")
    assert lost["text"] == (
        "even qualified at 96.00 USD -- front-loaded 123.50 USD applied instead: with "
        "the rest of the plan this stay comes to 42.00 USD by front-loaded and 60.00 USD "
        "by even (plan resolves ACCUMULATE by cheapest_wins)"
    ), lost["text"]
    # The control: with no cap, the rate that charges less is the cheaper stay.
    assert _quote(_plan(FRONT_LOADED, EVEN), MONDAY, WEDNESDAY)["fee_minor"] == 9600


@pytest.mark.guarantee("F63")
def test_a_stated_order_does_not_charge_the_dearer_way():
    """The plan names the weekend rate first. It used to be charged, 48.00; the
    event's stay is 30.00, and that is charged."""
    stated = {"QUALIFY": {"mode": "stated_order", "order": ["weekend", "event"]},
              "ACCUMULATE": {"mode": "cheapest_wins"}}
    body = _quote(_plan(WEEKEND_RATE, EVENT, _daily(), resolution=stated),
                  SATURDAY, MONDAY_AFTER)
    assert body["fee_minor"] == 3000
    assert _applied(body) == ["event"]


@pytest.mark.guarantee("F63")
def test_two_ways_at_one_fee_name_the_one_that_charges_less_itself():
    """A 40.00 and a 50.00 flat over the same Saturday and Sunday, at 30.00 a
    day: both stays come to 30.00. The 40.00 is named -- its own price is lower
    -- though the 50.00 has the lower rule id, and the 50.00's line says the
    40.00 applied instead."""
    forty = _window("zz-forty", "Forty", ["sat"], _flat(4000))
    fifty = _window("aa-fifty", "Fifty", ["sat"], _flat(5000))
    body = _quote(_plan(forty, fifty, _daily()), SATURDAY, MONDAY_AFTER)
    assert body["fee_minor"] == 3000
    assert _applied(body) == ["zz-forty"]
    lost = _line(body, "aa-fifty", "resolved")
    assert "Forty 40.00 USD applied instead" in lost["text"], lost["text"]


# --- what is not a choice stays as it was -------------------------------------


@pytest.mark.guarantee("F63")
def test_a_surcharge_and_a_fixed_increase_are_still_added_in_full():
    """Additive rules are not made a choice. In a VIP space the decision's stay
    is the capped 30.00 and the 5.00 VIP extra; with a 4.00 event fee, 4.00 more."""
    vip = {"id": "vip-extra", "type": "space_surcharge", "stage": "SURCHARGE",
           "space_classes": ["vip"], "surcharge_minor": 500}
    fee = {**_window("event-fee", "Event fee", EVERY_DAY,
                     {"kind": "adjust", "direction": "increase",
                      "amount": {"kind": "fixed", "minor": 400}, "rounding": "up"}),
           "stage": "ADJUST"}
    assert _quote(_plan(WEEKEND_FLAT, _daily(), vip), FRIDAY_1800, SUNDAY_2000,
                  "vip")["fee_minor"] == 3500
    assert _quote(_plan(WEEKEND_FLAT, _daily(), vip, fee), FRIDAY_1800, SUNDAY_2000,
                  "vip")["fee_minor"] == 3900


# --- the rule itself, swept ---------------------------------------------------

#: A plan with every kind of competing way: four specials (flat and rate, same
#: day, next day, any span), two time-based rates, both caps, a VIP extra and a
#: discount on every stay.
SWEPT = _plan(
    _window("early-bird", "Early bird", ["mon", "tue", "wed", "thu", "fri"], _flat(1100),
            enter_from="06:00", enter_by="09:00", exit_by="18:00", day_span="same_day"),
    _window("overnight", "Overnight", EVERY_DAY, _flat(1800), enter_from="17:00",
            exit_by="10:00", day_span="next_day"),
    _window("weekend-rate", "Weekend rate", ["sat", "sun"], _rate(150)),
    _window("event", "Event", ["sat"], _flat(9000)),
    {**HOURLY, "id": "hourly", "first_period_minor": 300, "repeat_period_minor": 250},
    {**HOURLY, "id": "short-stay", "first_period_minutes": 180, "first_period_minor": 1200,
     "repeat_period_minor": 100},
    _daily(2500),
    _weekly(12000),
    {"id": "vip-extra", "type": "space_surcharge", "stage": "SURCHARGE",
     "space_classes": ["vip"], "surcharge_minor": 500},
    {**_window("members", "Members", EVERY_DAY,
               {"kind": "adjust", "direction": "discount",
                "amount": {"kind": "percent", "percent_bp": 1000}, "rounding": "down"}),
     "stage": "ADJUST"},
)

#: The rules that can price the time: each is a way.
WAYS = ("early-bird", "overnight", "weekend-rate", "event", "hourly", "short-stay")


def _only(way: str) -> dict:
    """SWEPT with every other way taken out: the stay priced by `way` alone."""
    document = copy.deepcopy(SWEPT)
    document["rules"] = [r for r in document["rules"] if r["id"] == way or r["id"] not in WAYS]
    return document


@pytest.mark.guarantee("F63")
def test_the_fee_is_the_least_of_the_fees_each_way_charges_on_its_own():
    """Over entries on a weekday, a Friday and a Saturday at four times of day,
    stays from an hour to nine days, both space classes: the fee is the lowest of
    the fees the plan charges with each way alone -- a way that does not price
    the stay alone takes no part. Some stays here are ones a cap reverses, and
    the sweep requires that it saw them."""
    days = ("2026-04-07", "2026-04-10", "2026-04-11")
    times = ("05:30", "07:30", "17:30", "22:00")
    minutes = (60, 150, 600, 900, 1500, 2880, 4400, 12960)
    checked = reversed_by_a_cap = 0
    for day in days:
        for at in times:
            entry = f"{day}T{at}:00-04:00"
            for length in minutes:
                exit_ = (parse_instant(entry, "e") + timedelta(minutes=length)).isoformat()
                for space_class in ("standard", "vip"):
                    request = {"entry_at": entry, "exit_at": exit_,
                               "space_class": space_class, "currency": "USD"}
                    status, whole = run_quote({"plans": [copy.deepcopy(SWEPT)], **request})
                    assert status == 200, whole
                    alone = {}
                    for way in WAYS:
                        status, body = run_quote({"plans": [_only(way)], **request})
                        if status == 200:
                            alone[way] = body["fee_minor"]
                    assert whole["fee_minor"] == min(alone.values()), (entry, length, alone)
                    checked += 1
                    special = [w for w in alone if w in WAYS[:4]]
                    if len(special) > 1:
                        reversed_by_a_cap += _a_cap_reverses(special, request, alone)
    assert checked == len(days) * len(times) * len(minutes) * 2
    assert reversed_by_a_cap > 0, "the sweep never met a stay a cap reverses"


def _a_cap_reverses(ways: list[str], request: dict, alone: dict) -> int:
    """1 when the special that charges least ITSELF is not the cheapest stay --
    the case the old comparison of the rules' own charges got wrong."""
    own = {}
    for way in ways:
        _s, body = run_quote({"plans": [_only(way)], **request})
        # A flat's price is on its applied line; a rate's on its period lines.
        own[way] = sum(
            ln["delta_minor"] for ln in body["breakdown"]
            if ln["rule_id"] == way
            and (ln["code"] == "time_window.applied" or ln["code"].startswith("increment."))
        )
    by_own = min(ways, key=lambda w: (own[w], w))
    return int(alone[by_own] > min(alone[w] for w in ways))
