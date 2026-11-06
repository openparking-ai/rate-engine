"""F78 -- real garage listings, written as plans, are priced as the listing says.

Gokhan, 2026-11-07: test with the real rates found online, **"as many as you can.
Not some imaginary only created rates."** `tests/plans/real/` holds one plan per
real listing and a `.listing.json` beside it carrying where it came from, the
listing's own words, and the stays to price with what the listing says they cost.

Rules this file keeps:

* **The expected number comes from the listing's words**, never from the engine: the
  stated price, the cheapest of the prices that apply (Gokhan: the cheapest wins for
  the customer), a started block counted whole, a minimum or maximum stay or an
  entry/exit limit at its own edge, one minute either side.
* **Where a listing states no price for a stay, the engine must refuse it**
  (`GAP_NO_ACCUMULATE_RULE`) and not invent one. Listings are often partial; the
  refusal is the engine saying so.
* **Where the listing does not say which side an edge is on** (exactly 2.0 hours in a
  table of ranges), nothing is asserted there.
* **These are third-party, mostly undated listings. They are not current prices**
  and the files say so. No price here goes into any customer-facing place.

`scripts/fail_controls.py` makes the engine ignore a minimum stay and requires this
file to go red.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rate_engine.contract import run_quote
from rate_engine.plan import load_plan
from rate_engine.validator import validate_plan

REAL = Path(__file__).parent / "plans" / "real"
LISTINGS = sorted(REAL.glob("*.listing.json"))


def _pair(path: Path):
    plan_path = path.with_name(path.name.replace(".listing.json", ".json"))
    return json.loads(plan_path.read_text()), json.loads(path.read_text())


def _cases():
    for path in LISTINGS:
        _plan, listing = _pair(path)
        for case in listing["cases"]:
            name = path.name.removesuffix(".listing.json")
            yield pytest.param(path, case, id=f"{name}::{case['name']}")


@pytest.mark.guarantee("F78")
def test_there_are_many_real_listings_and_each_names_its_source_and_says_it_is_not_current():
    assert len(LISTINGS) >= 25, f"only {len(LISTINGS)} listings"
    for path in LISTINGS:
        _plan, listing = _pair(path)
        assert listing["source_url"].startswith("http"), path.name
        assert listing["date_seen"] == "2026-11-07", path.name
        assert listing["verbatim_rows"], path.name
        assert "Not a current price" in listing["NOT_CURRENT_PRICES"], path.name
        assert listing["cases"], path.name
    assert len({p.name for p in LISTINGS}) == len(LISTINGS)


@pytest.mark.guarantee("F78")
@pytest.mark.parametrize("path", LISTINGS, ids=lambda p: p.name.removesuffix(".listing.json"))
def test_each_real_plan_loads_and_validates_without_a_conflict(path):
    document, _listing = _pair(path)
    findings = validate_plan(load_plan(document))
    # A partial listing has gaps (a stay it states no price for); a conflict would be
    # two rules the engine had to choose between without being told how.
    assert not [f for f in findings if f.code.startswith("CONFLICT")], findings


@pytest.mark.guarantee("F78")
@pytest.mark.parametrize("path,case", list(_cases()))
def test_the_engine_prices_the_stay_as_the_listing_says(path, case):
    document, listing = _pair(path)
    zone = ZoneInfo(document["timezone"])
    entry = datetime.fromisoformat(case["entry"]).replace(tzinfo=zone)
    exit_at = (entry.astimezone(zone) + timedelta(minutes=case["minutes"]))
    # Wall-clock arithmetic is wrong across a clock change; the dates used avoid one,
    # and this checks that they do.
    assert entry.utcoffset() == exit_at.replace(tzinfo=zone).utcoffset()
    status, body = run_quote({
        "plans": [document], "entry_at": entry.isoformat(),
        "exit_at": exit_at.replace(tzinfo=zone).isoformat(),
        "space_class": "standard", "currency": "USD",
    })
    why = f"{listing['garage']}: {case['name']} -- {case['basis']}"
    if "expect_refusal" in case:
        assert status == 422, (
            f"{why}: priced {body.get('fee_minor')} where the listing states nothing"
        )
        assert any(f["code"] == case["expect_refusal"] for f in body["findings"]), (why, body)
    else:
        assert status == 200, f"{why}: {body}"
        assert body["fee_minor"] == case["expect_fee_minor"], (
            f"{why}: engine {body['fee_minor']}, listing words imply {case['expect_fee_minor']}"
        )
