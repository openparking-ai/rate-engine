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
import subprocess
import sys
import threading
import urllib.request

import pytest

from fixtures import CORPUS, DOWNTOWN_V2
from rate_engine.contract import encode, run_quote
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


def _over_http(url: str, path: str, body: dict) -> tuple[int, bytes]:
    """The RAW BYTES the route wrote, never a decode.

    This used to return `json.loads(response.read())`, which is what made the
    byte-equality assertions below unable to fail: decoding both sides destroys
    exactly the formatting difference the guarantee is about. Measured -- with
    the decode in place, re-serializing the CLI with `indent=4, sort_keys=True`
    left the whole file green.
    """
    request = urllib.request.Request(
        url + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@pytest.mark.guarantee("F6", "F6c")
def test_http_and_the_in_process_path_return_identical_bytes(base_url):
    """Every fixture, priced and refused, over both doors -- compared as BYTES."""
    for name, s in CORPUS.items():
        body = _request(s)
        direct_status, direct_body = run_quote(body)
        http_status, http_bytes = _over_http(base_url, "/v1/quote", body)
        assert http_status == direct_status, name
        assert http_bytes == encode(direct_body), (
            f"{name}: the HTTP route and the pricing path disagree BYTE FOR BYTE"
        )


@pytest.mark.guarantee("F6", "F6c")
def test_the_cli_writes_exactly_the_bytes_the_route_returns(tmp_path):
    """`--json` IS the route's bytes, not a rendering of them.

    Run as a SUBPROCESS and compared on stdout's raw bytes. In-process with
    `capsys` this cannot be measured honestly: pytest replaces stdout with a text
    stream, so the very byte at issue -- the trailing newline `print` used to add
    inside the payload -- is the one an in-process capture is least able to see.
    """
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(DOWNTOWN_V2))

    for name, s in CORPUS.items():
        _, expected = run_quote(_request(s))
        result = subprocess.run(
            [
                sys.executable, "-m", "rate_engine.cli", "quote",
                "--plan", str(plan_file),
                "--entry", s.entry_at.isoformat(),
                "--exit", s.exit_at.isoformat(),
                "--space-class", s.space_class,
                "--currency", "USD",
                "--json",
            ],
            capture_output=True,
        )
        payload = encode(expected)
        assert result.stdout == payload + b"\n", (
            f"{name}: the CLI's bytes are not the route's bytes plus one newline "
            f"outside the payload ({len(result.stdout)} vs {len(payload) + 1})"
        )
        # And the payload itself, with the terminal's newline stripped, is exact.
        assert result.stdout[:-1] == payload, name


@pytest.mark.guarantee("F6")
def test_a_refusal_reaches_both_surfaces_as_a_refusal(base_url):
    """Not a 500, not a zero fee -- the same named gap through either door."""
    body = _request(CORPUS["ceiling_over"])
    status, raw = _over_http(base_url, "/v1/quote", body)
    payload = json.loads(raw)
    assert status == 422
    assert payload["refused"] is True
    assert payload["findings"][0]["code"] == "GAP_STAY_EXCEEDS_MAX_DURATION"

    direct_status, direct_payload = run_quote(body)
    assert direct_status == status
    assert raw == encode(direct_payload), "a refusal differs between the two doors"


@pytest.mark.guarantee("F6")
def test_validate_plan_agrees_across_both_surfaces(base_url):
    from rate_engine.contract import run_validate

    body = {"plan": DOWNTOWN_V2}
    status, raw = _over_http(base_url, "/v1/validate-plan", body)
    direct_status, direct_body = run_validate(body)
    assert (status, raw) == (direct_status, encode(direct_body))


@pytest.mark.guarantee("F6b")
def test_THERE_IS_ONE_ENCODER_and_no_surface_re_implements_it():
    """The structural half, and the one that would have caught this at birth.

    The claim is "one code path and one serializer". It was false while three
    `json.dumps` call sites encoded a response with two different argument lists,
    and nothing measured that -- byte-equality was asserted over decoded objects.
    A second encode site added anywhere in the package fails this the day it
    appears, rather than the round somebody's bytes diverge.

    **Walks the AST, not the text.** The first version of this grepped for
    `json.dumps` and went red on its own docstring -- the sentences in cli.py
    explaining the defect matched the search for the defect. A check that matches
    WORDS confirms only that a word was written; this one matches a CALL.
    """
    import ast
    import pathlib

    import rate_engine

    package = pathlib.Path(rate_engine.__file__).parent
    offenders: dict[str, list[int]] = {}
    for source in sorted(package.rglob("*.py")):
        if source.name == "contract.py":
            continue  # the one encoder lives here
        tree = ast.parse(source.read_text())
        hits = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
        ]
        if hits:
            offenders[source.name] = hits
    assert offenders == {}, (
        f"a response is encoded outside contract.encode: {offenders}. The published "
        "guarantee is one serializer; a second one is how the bytes diverged before."
    )


def test_the_corpus_contains_both_a_priced_stay_and_a_refusal():
    """The control: F6 over an all-priced corpus never exercises the refusal path."""
    statuses = {run_quote(_request(s))[0] for s in CORPUS.values()}
    assert 200 in statuses and 422 in statuses, (
        f"the corpus produced only {statuses}; one of the two branches is unmeasured"
    )
