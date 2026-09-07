"""F6 -- the test function IS the production path.

"We need a test function. They type entry and exit we display the fee." That
function is `/v1/quote` called with typed times, and the CLI is the same call
without an HTTP client in the way. There is no simulation mode and there is no
second implementation.

**This is the control that matters most in this module.** A test function that
answers differently from the production path tells an operator their garage will
charge something it will not, and they find out at the counter. So the test is
not "both surfaces changed when the engine changed" -- that proves they MOVE, not
that they AGREE. It is byte-equality of the JSON, from one serializer, over the
whole fixture corpus including the refusals.
"""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from fixtures import CORPUS, DOWNTOWN_V2
from rate_engine.cli import main as cli_main
from rate_engine.contract import run_quote
from rate_engine.service import make_server


def _request(s) -> dict:
    return {
        "plans": [DOWNTOWN_V2],
        "entry_at": s.entry_at.isoformat(),
        "exit_at": s.exit_at.isoformat(),
        "space_class": s.space_class,
        "currency": "USD",
    }


@pytest.fixture(scope="module")
def base_url():
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _over_http(url: str, path: str, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


@pytest.mark.guarantee("F6")
def test_http_and_the_in_process_path_return_identical_bytes(base_url):
    """Every fixture, priced and refused, over both doors."""
    for name, s in CORPUS.items():
        body = _request(s)
        direct_status, direct_body = run_quote(body)
        http_status, http_body = _over_http(base_url, "/v1/quote", body)
        assert http_status == direct_status, name
        assert json.dumps(http_body) == json.dumps(direct_body), (
            f"{name}: the HTTP route and the pricing path disagree"
        )


@pytest.mark.guarantee("F6")
def test_the_cli_prints_exactly_what_the_route_returns(capsys, tmp_path):
    """`--json` is the route's bytes, not a rendering of them."""
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(DOWNTOWN_V2))

    for name, s in CORPUS.items():
        _, expected = run_quote(_request(s))
        cli_main(
            [
                "quote",
                "--plan",
                str(plan_file),
                "--entry",
                s.entry_at.isoformat(),
                "--exit",
                s.exit_at.isoformat(),
                "--space-class",
                s.space_class,
                "--currency",
                "USD",
                "--json",
            ]
        )
        printed = json.loads(capsys.readouterr().out)
        assert printed == expected, f"{name}: the CLI and the route disagree"


@pytest.mark.guarantee("F6")
def test_a_refusal_reaches_both_surfaces_as_a_refusal(base_url):
    """Not a 500, not a zero fee -- the same named gap through either door."""
    body = _request(CORPUS["ceiling_over"])
    status, payload = _over_http(base_url, "/v1/quote", body)
    assert status == 422
    assert payload["refused"] is True
    assert payload["findings"][0]["code"] == "GAP_STAY_EXCEEDS_MAX_DURATION"

    direct_status, direct_payload = run_quote(body)
    assert (direct_status, direct_payload) == (status, payload)


@pytest.mark.guarantee("F6")
def test_validate_plan_agrees_across_both_surfaces(base_url):
    from rate_engine.contract import run_validate

    body = {"plan": DOWNTOWN_V2}
    assert _over_http(base_url, "/v1/validate-plan", body) == run_validate(body)


def test_the_corpus_contains_both_a_priced_stay_and_a_refusal():
    """The control: F6 over an all-priced corpus never exercises the refusal path."""
    statuses = {run_quote(_request(s))[0] for s in CORPUS.values()}
    assert 200 in statuses and 422 in statuses, (
        f"the corpus produced only {statuses}; one of the two branches is unmeasured"
    )
