"""OP-6-6 -- every request is answered: no input drops the connection.

Three inputs crashed a request with no answer at all. A short stay at the end
of the calendar (year 9999) raised `OverflowError` from the day arithmetic; a
special dated 9999-12-31, or a ceiling of billions of minutes, did the same in
`validate-plan`; and a body nested deeper than the JSON parser recurses, well
inside the 1 MiB bound, raised `RecursionError`. None was caught, so the HTTP
door closed the connection unanswered -- and so did any bug.

Now a stay outside `EARLIEST_YEAR`..`LATEST_YEAR` and a special dated outside
them are a 400 naming the field; `RecursionError` and `OverflowError` are a 400
on every door; and over HTTP anything else is a 500 that says only that nothing
was priced.
"""

from __future__ import annotations

import copy
import json
import threading
import urllib.error
import urllib.request

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine import service
from rate_engine.contract import run_quote, run_validate
from rate_engine.plan import InvalidPlan, load_plan


def _quote(entry: str, exit_: str) -> dict:
    return {"plans": [copy.deepcopy(DOWNTOWN_V2)], "entry_at": entry, "exit_at": exit_,
            "space_class": "standard", "currency": "USD"}


@pytest.fixture
def url():
    server = service.make_server(port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _post(url: str, route: str, body: bytes) -> tuple[int, dict]:
    request = urllib.request.Request(url + route, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as answered:
        return answered.code, json.loads(answered.read())


@pytest.mark.guarantee("F70")
def test_a_short_stay_at_the_end_of_the_calendar_is_a_named_400():
    status, body = run_quote(_quote("9999-12-31T20:00:00-05:00", "9999-12-31T20:30:00-05:00"))
    assert status == 400, body
    assert "entry_at" in body["error"] and "9000" in body["error"]


def test_a_stay_from_year_one_to_9999_is_still_refused_for_its_length():
    status, body = run_quote(_quote("0001-01-01T12:00:00+00:00", "9999-12-31T12:00:00+00:00"))
    assert status == 422, body
    assert body["findings"][0]["code"] == "GAP_STAY_LONGER_THAN_MAX_STAY"


def test_a_special_dated_at_the_end_of_the_calendar_does_not_load():
    plan = copy.deepcopy(DOWNTOWN_V2)
    window = next(r for r in plan["rules"] if r["type"] == "time_window")
    window["applies_on"] = {"kind": "dates", "dates": ["9999-12-31"]}
    with pytest.raises(InvalidPlan, match="9999-12-31"):
        load_plan(plan)


@pytest.mark.guarantee("F70")
def test_a_length_too_long_to_compute_with_is_a_400_not_a_crash():
    plan = copy.deepcopy(DOWNTOWN_V2)
    for rule in plan["rules"]:
        if rule["type"] == "increment":
            rule["max_duration_minutes"] = 10**10  # nineteen thousand years
    status, body = run_validate({"plan": plan})
    assert status == 400, body
    assert "too far" in body["error"]


@pytest.mark.guarantee("F70")
def test_a_body_nested_too_deeply_is_answered_400(url):
    status, body = _post(url, "/v1/validate-plan", b"[" * 200_000 + b"]" * 200_000)
    assert status == 400, body
    assert "nested too deeply" in body["error"]


@pytest.mark.guarantee("F70")
def test_a_stay_at_the_end_of_the_calendar_is_answered_over_http(url):
    request = _quote("9999-12-31T20:00:00-05:00", "9999-12-31T20:30:00-05:00")
    status, body = _post(url, "/v1/quote", json.dumps(request).encode())
    assert status == 400, body


@pytest.mark.guarantee("F70")
def test_a_bug_is_a_500_that_carries_nothing_of_the_request(url, monkeypatch):
    def broken(document):
        raise RuntimeError(f"secret rate card: {document}")

    monkeypatch.setattr(service, "run_tax", broken)
    status, body = _post(url, "/v1/tax", json.dumps({"rate": "secret"}).encode())
    assert status == 500, body
    assert "secret" not in json.dumps(body)
    assert "nothing was priced" in body["error"]
