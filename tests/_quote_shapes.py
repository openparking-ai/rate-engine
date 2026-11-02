"""Plan shapes for measuring what a quote costs (F67), shared by the timing tests.

A shape says which kind of rule is multiplied -- the ways a stay can be priced
(flat specials, specials with a time-based `rate` effect, time-based rates) or
the padding every pass walks (discounts, surcharges, specials that do not
qualify) -- beside which caps, on which length of stay. `plan(shape, n)` is
that shape with `n` of its multiplied rule; the timing tests search for the
largest `n` the quote budget still lets through and time that quote.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

EVERY_DAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEK_START = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

#: A Monday 09:00, and the stay lengths a shape may name, in minutes.
ENTRY = "2026-04-06T09:00:00-04:00"
STAYS = {"2h": 120, "1d": 24 * 60, "7d": 7 * 24 * 60, "90d": 90 * 24 * 60}

HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 60,
    "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}


def _window(rule_id: str, stage: str, effect: dict, days=EVERY_DAY) -> dict:
    return {
        "id": rule_id, "type": "time_window", "stage": stage,
        "space_classes": ["standard"], "label": rule_id,
        "applies_on": {"kind": "days_of_week", "days": list(days)},
        "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
        "day_span": "any_span", "effect": effect,
    }


def flat(i: int) -> dict:
    return _window(f"flat-{i:04d}", "QUALIFY", {"kind": "flat", "price_minor": 100_000 + i})


def unqualified(i: int) -> dict:
    """A weekend special: a Monday stay does not qualify for it."""
    return _window(f"weekend-{i:04d}", "QUALIFY",
                   {"kind": "flat", "price_minor": 100_000 + i}, days=["sat", "sun"])


def rate_special(i: int) -> dict:
    """A special that prices the time on a rate of its own, by the minute."""
    return _window(f"rate-special-{i:04d}", "QUALIFY", {
        "kind": "rate", "first_period_minutes": 1, "first_period_minor": 10 + i,
        "repeat_period_minutes": 1, "repeat_period_minor": 10 + i, "rounding": "ceil",
        "max_duration_minutes": None,
    })


def rate(i: int) -> dict:
    return dict(copy.deepcopy(HOURLY), id=f"rate-{i:04d}",
                first_period_minor=900 + i, repeat_period_minor=450 + i)


def discount(i: int) -> dict:
    return _window(f"off-{i:04d}", "ADJUST", {
        "kind": "adjust", "direction": "discount",
        "amount": {"kind": "fixed", "minor": 1}, "rounding": "down",
    })


def surcharge(i: int) -> dict:
    return {"id": f"extra-{i:04d}", "type": "space_surcharge", "stage": "SURCHARGE",
            "space_classes": ["standard"], "surcharge_minor": 1}


FILL = {
    "id": "busy", "type": "fill_level", "stage": "ADJUST", "space_classes": ["standard"],
    "threshold_bp": 8000, "percent_bp": 2000, "rounding": "up",
    "raises_specials": "yes", "raises_vip_extra": "no",
}

#: What a shape may multiply, and the rule each one builds.
MULTIPLIED = {
    "flat": flat, "rate_special": rate_special, "rate": rate,
    "discount": discount, "surcharge": surcharge, "unqualified": unqualified,
}


@dataclass(frozen=True)
class Shape:
    multiplied: str
    stay: str = "2h"
    daily: int = 0
    weekly: int = 0
    #: How many flat specials beside the multiplied rule, so a plan of padding
    #: still has ways to price it again and again.
    ways: int = 0
    fill: bool = False

    def __str__(self) -> str:
        parts = [self.multiplied, self.stay]
        if self.daily or self.weekly:
            parts.append(f"{self.daily}d+{self.weekly}w")
        if self.ways:
            parts.append(f"{self.ways} ways")
        if self.fill:
            parts.append("fill")
        return "/".join(parts)


def caps(daily: int, weekly: int) -> list[dict]:
    rules = [
        {"id": f"daily-{i}", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 3000 + i, "day_boundary": "calendar_day"}
        for i in range(daily)
    ]
    rules += [
        {"id": f"weekly-{i}", "type": "weekly_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 10_000 + i,
         "week_boundary": "calendar_week", "week_starts_on": WEEK_START[i % 7]}
        for i in range(weekly)
    ]
    return rules


def plan(shape: Shape, n: int) -> dict:
    """The shape with `n` of its multiplied rule, as a plan document."""
    rules = [copy.deepcopy(HOURLY)] + caps(shape.daily, shape.weekly)
    rules += [flat(10_000 + i) for i in range(shape.ways)]
    rules += [MULTIPLIED[shape.multiplied](i) for i in range(n)]
    if shape.fill:
        rules.append(copy.deepcopy(FILL))
    adjust = [r["id"] for r in rules if r["stage"] == "ADJUST"]
    fills = [r["id"] for r in rules if r["type"] == "fill_level"]
    order = [i for i in adjust if i not in fills] + fills
    return {
        "plan_version": f"shape-{shape}", "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York", "currency": "USD", "space_classes": ["standard"],
        "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                       "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": order if len(order) > 1 else None,
        "rules": rules, "decisions": [],
    }


def stay(shape: Shape):
    from datetime import timedelta

    from rate_engine.engine import make_stay
    from rate_engine.plan import parse_instant

    entry = parse_instant(ENTRY, "entry")
    return make_stay(entry, entry + timedelta(minutes=STAYS[shape.stay]), "standard",
                     9000 if shape.fill else None)


def grid() -> list[Shape]:
    """The generated search (F67): every way kind on every stay beside nine cap
    mixes, every padding kind beside one to a thousand ways on a short and a long
    stay, and the fill rule beside discounts. 156 shapes."""
    from itertools import product

    cap_mixes = [(0, 0), (1, 0), (0, 1), (1, 1), (8, 8), (1, 15), (16, 0), (0, 16), (4, 4)]
    shapes = [
        Shape(kind, length, daily, weekly)
        for kind, length, (daily, weekly) in product(
            ("flat", "rate", "rate_special"), STAYS, cap_mixes)
    ]
    shapes += [
        Shape(kind, length, daily, weekly, ways=ways)
        for kind, ways, length, (daily, weekly) in product(
            ("discount", "surcharge", "unqualified"), (1, 50, 400, 1000), ("2h", "90d"),
            ((0, 0), (1, 1)))
    ]
    shapes += [Shape("discount", "2h", ways=ways, fill=True) for ways in (1, 50, 400)]
    return shapes


def largest_inside_the_budget(shape: Shape):
    """The plan of this shape with the most of its multiplied rule whose quote
    the budget still lets through, and the same plan with one more -- or None,
    None when even none of them fits."""
    from rate_engine import limits
    from rate_engine.engine import _Qualified, quote_work
    from rate_engine.plan import load_plan

    the_stay = stay(shape)

    def work(n):
        loaded = load_plan(plan(shape, n))
        return quote_work(loaded, the_stay, _Qualified(loaded, the_stay)), loaded

    if work(0)[0] > limits.MAX_QUOTE_WORK:
        return None, None
    fixed = 1 + shape.daily + shape.weekly + shape.ways + (1 if shape.fill else 0)
    low, high = 0, limits.MAX_RULES_PER_PLAN - fixed - 1
    while low < high:
        mid = (low + high + 1) // 2
        if work(mid)[0] <= limits.MAX_QUOTE_WORK:
            low = mid
        else:
            high = mid - 1
    return work(low)[1], work(low + 1)[1]
