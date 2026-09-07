"""F17 -- the rendered amount matches the currency, not the number 100.

The defect, measured at 75c385b: a JPY plan returned `fee_minor` 800 -- correct,
800 yen -- and the breakdown said "8.00 JPY". The arithmetic was right and the
sentence a hundred times wrong, in the one artefact this module exists to make
trustworthy. `ZZZ` was accepted at the same time, by a check whose own diagnostic
claimed ISO 4217 and tested only shape.

Those were one defect and this is one guarantee: the module knows the currency,
or it refuses to price in it.

**The structural tests below are here because the table is TRANSCRIBED.** There
is no dependency to read the ISO register from, so `currency.py` is the only
typed table in this repo. These assert what can be asserted without a network --
that every exponent is a real ISO value, that the groups are disjoint, that no
code is malformed -- and the loader's refusal makes an OMISSION fail loudly
rather than render wrongly. What they cannot prove is completeness; the module
docstring says so, and the receipt names it.
"""

from __future__ import annotations

import copy
import json

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import run_quote
from rate_engine.currency import (
    FOUR_DECIMAL,
    MINOR_UNIT_DIGITS,
    THREE_DECIMAL,
    ZERO_DECIMAL,
    minor_unit_digits,
)
from rate_engine.money import format_minor

#: (currency, minor units, the text a breakdown must show). One case per exponent
#: the table actually contains, derived below so a new exponent group cannot be
#: added without a rendering case.
RENDERINGS = (
    ("JPY", 800, "800 JPY"),
    ("JPY", 0, "0 JPY"),
    ("JPY", -1400, "-1400 JPY"),
    ("USD", 800, "8.00 USD"),
    ("USD", -1400, "-14.00 USD"),
    ("KWD", 800, "0.800 KWD"),
    ("CLF", 800, "0.0800 CLF"),
)


@pytest.mark.guarantee("F17")
@pytest.mark.parametrize("currency,minor,expected", RENDERINGS)
def test_an_amount_renders_on_its_own_currencys_exponent(currency, minor, expected):
    assert format_minor(minor, currency) == expected


@pytest.mark.guarantee("F17")
def test_every_exponent_group_in_the_table_has_a_rendering_case():
    """Derived from the table, never a written list -- §6's enumeration rule.

    A fifth exponent group added to currency.py with no rendering case here fails
    this, rather than shipping a group nothing ever rendered.
    """
    covered = {minor_unit_digits(c) for c, _m, _e in RENDERINGS}
    present = set(MINOR_UNIT_DIGITS.values())
    assert present <= covered, (
        f"exponent group(s) with no rendering case: {sorted(present - covered)}"
    )


@pytest.mark.guarantee("F17")
def test_a_zero_decimal_currency_prices_END_TO_END_with_no_decimal_point():
    """The exact stay the L3 measured, through the production path."""
    document = copy.deepcopy(DOWNTOWN_V2)
    document["currency"] = "JPY"
    status, body = run_quote(
        {
            "plans": [document],
            "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T09:50:00-05:00",
            "space_class": "standard",
            "currency": "JPY",
        }
    )
    assert status == 200
    assert body["fee_minor"] == 800
    rendered = [line["text"] for line in body["breakdown"] if "first" in line["code"]][0]
    assert "800 JPY" in rendered, rendered
    assert "8.00" not in rendered, (
        f"the fee is 800 yen and the breakdown says: {rendered}"
    )


@pytest.mark.guarantee("F17", "F17b")
@pytest.mark.parametrize("code", ["ZZZ", "QQQ", "AAA", "XXX", "XTS", "XAU", "XDR"])
def test_a_code_this_module_cannot_render_is_REFUSED_at_load(code):
    """Including the ISO placeholders and the codes with no minor unit at all.

    `XXX` is "no currency" and `XTS` is reserved for testing: both are real ISO
    codes and neither is money to price a garage in. The metals and fund codes
    have no minor unit defined, so they cannot be expressed in the only money
    type this module has.
    """
    document = copy.deepcopy(DOWNTOWN_V2)
    document["currency"] = code
    status, body = run_quote(
        {
            "plans": [document],
            "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T09:50:00-05:00",
            "space_class": "standard",
            "currency": code,
        }
    )
    assert status == 400, f"{code} was accepted"
    assert code in body["error"] and "ISO 4217" in body["error"]


@pytest.mark.guarantee("F17")
def test_the_shipped_currency_still_prices():
    """The control on the item above: the refusal must not have banned real money."""
    document = copy.deepcopy(DOWNTOWN_V2)
    status, _body = run_quote(
        {
            "plans": [document],
            "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T09:50:00-05:00",
            "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 200


def test_the_table_is_structurally_sound():
    """What can be checked about a transcribed table without a network.

    Not completeness -- nothing offline can prove that. This catches the errors a
    transcription actually makes: a malformed code, an exponent that is not an
    ISO value, a code in two groups at once.
    """
    assert MINOR_UNIT_DIGITS, "the table is empty"
    for code, digits in MINOR_UNIT_DIGITS.items():
        assert isinstance(code, str) and len(code) == 3 and code.isupper() and code.isalpha(), code
        assert digits in (0, 2, 3, 4), f"{code} has exponent {digits}, which ISO 4217 does not use"

    groups = (ZERO_DECIMAL, THREE_DECIMAL, FOUR_DECIMAL)
    for i, first in enumerate(groups):
        for second in groups[i + 1:]:
            assert not (first & second), f"in two exponent groups at once: {sorted(first & second)}"

    for codes, digits in ((ZERO_DECIMAL, 0), (THREE_DECIMAL, 3), (FOUR_DECIMAL, 4)):
        for code in codes:
            assert MINOR_UNIT_DIGITS[code] == digits, code

    for excluded in ("XXX", "XTS", "XAU", "XAG", "XPT", "XPD", "XDR", "XBA", "XSU", "XUA"):
        assert excluded not in MINOR_UNIT_DIGITS, (
            f"{excluded} has no minor unit in ISO 4217 and cannot be rendered"
        )


def test_the_json_payload_carries_the_currency_so_a_client_can_render_it_itself():
    """An integrator rendering its own receipt needs the code, not only our text."""
    document = copy.deepcopy(DOWNTOWN_V2)
    document["currency"] = "JPY"
    _status, body = run_quote(
        {
            "plans": [document],
            "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T09:50:00-05:00",
            "space_class": "standard",
            "currency": "JPY",
        }
    )
    assert body["currency"] == "JPY"
    assert isinstance(body["fee_minor"], int)
    json.dumps(body)
