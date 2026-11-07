"""Plans and quotes for the real-rate-option tests (F72 and after).

One small helper so each guarantee's file reads as the listing it models. Every
price here is an EXAMPLE chosen to make the arithmetic easy to check by hand. It is
not a rate from any real garage; the listings only showed HOW a garage words a
price, and these tests copy the wording and none of the numbers.
"""

from __future__ import annotations

from datetime import timedelta

from rate_engine.contract import run_quote
from rate_engine.plan import parse_instant

EVERY_DAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]

#: 8.00 the first hour, 4.00 each hour after. An example, not a real rate.
HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 60,
    "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}

#: Tue 2026-03-03, a weekday.
TUESDAY_9AM = "2026-03-03T09:00:00-05:00"
TUESDAY_8AM = "2026-03-03T08:00:00-05:00"


def flat(rule_id: str, price_minor: int, *, days=None, enter_from="00:00", enter_by="23:59",
         exit_by="23:59", day_span="next_day", charged=None, **limits) -> dict:
    """A flat special, with the stay limits (`stay_at_least_minutes`, `stay_at_most_minutes`)
    passed through as given. Every day, any entry time, unless said otherwise."""
    effect = {"kind": "flat", "price_minor": price_minor}
    if charged is not None:
        effect["charged"] = charged
    return {
        "id": rule_id, "type": "time_window", "stage": "QUALIFY",
        "space_classes": ["standard"], "label": rule_id,
        "applies_on": {"kind": "days_of_week", "days": days or EVERY_DAY},
        "enter_from": enter_from, "enter_by": enter_by, "exit_by": exit_by,
        "day_span": day_span,
        "effect": effect,
        **limits,
    }


def plan(*rules: dict, decisions=()) -> dict:
    return {
        "plan_version": "options-2026-11",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                       "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": None,
        "rules": list(rules),
        "decisions": list(decisions),
    }


def quote(document: dict, entry: str, minutes: int = 0, *, seconds: int = 0,
          space_class: str = "standard"):
    """(status, body) through the production door, for a stay of that real length."""
    entry_at = parse_instant(entry, "entry")
    exit_at = entry_at + timedelta(minutes=minutes, seconds=seconds)
    return run_quote({
        "plans": [document], "entry_at": entry_at.isoformat(),
        "exit_at": exit_at.isoformat(), "space_class": space_class, "currency": "USD",
    })


def fee(document: dict, entry: str, minutes: int = 0, **kwargs) -> int:
    status, body = quote(document, entry, minutes, **kwargs)
    assert status == 200, body
    return body["fee_minor"]


def texts(document: dict, entry: str, minutes: int = 0, **kwargs) -> list[str]:
    status, body = quote(document, entry, minutes, **kwargs)
    assert status == 200, body
    return [line["text"] for line in body["breakdown"]]
