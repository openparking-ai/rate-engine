"""OP-6-5 -- a slow caller holds an HTTP thread for a bounded time, and the
threads are bounded.

The service gave every connection a thread of its own, with no limit, and
timed out a connection only when ONE read waited longer than 30 s. A caller
that sends a byte every few seconds never waits that long, so it held its
thread for as long as it liked -- and enough of them held every thread the
machine would give.

Now the whole request must arrive within `REQUEST_DEADLINE_SECONDS`, and at
most `MAX_CONNECTIONS` connections are served at once; one more is answered 503
straight away and closed.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from rate_engine import service


def _serve(monkeypatch, **limits):
    for name, value in limits.items():
        monkeypatch.setattr(service, name, value, raising=False)
    server = service.make_server(port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _closed_within(connection: socket.socket, trickle: bytes, seconds: float) -> float | None:
    """Send `trickle` a byte every 0.1 s; how long until the server closed the
    connection, or None if it was still open after `seconds`."""
    connection.settimeout(0.1)
    started = time.monotonic()
    for byte in (trickle[i:i + 1] for i in range(len(trickle))):
        if time.monotonic() - started > seconds:
            return None
        try:
            connection.sendall(byte)
            if connection.recv(4096) == b"":
                return time.monotonic() - started
        except TimeoutError:
            continue
        except OSError:  # reset or broken pipe: closed
            return time.monotonic() - started
    return None


TRICKLE = {
    "headers": b"POST /v1/quote HTTP/1.0\r\nX-Slow: " + b"a" * 1000,
    "body": b"POST /v1/quote HTTP/1.0\r\nContent-Length: 1000\r\n\r\n" + b" " * 1000,
}


@pytest.mark.guarantee("F69")
@pytest.mark.parametrize("part", sorted(TRICKLE))
def test_a_request_trickled_a_byte_at_a_time_is_closed_at_its_deadline(monkeypatch, part):
    server = _serve(monkeypatch, REQUEST_DEADLINE_SECONDS=1.0)
    try:
        with socket.create_connection(server.server_address[:2], timeout=5) as connection:
            closed = _closed_within(connection, TRICKLE[part], seconds=4.0)
        assert closed is not None, "still open after 4 s of trickling"
        assert closed < 2.5, f"closed after {closed:.1f} s"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.guarantee("F69")
def test_one_connection_more_than_the_limit_is_answered_503_at_once(monkeypatch):
    server = _serve(monkeypatch, MAX_CONNECTIONS=2)
    address = server.server_address[:2]
    try:
        idle = [socket.create_connection(address, timeout=5) for _ in range(2)]
        for connection in idle:  # each now holds a thread, waiting for its request
            connection.sendall(b"GET ")
        time.sleep(0.3)

        with socket.create_connection(address, timeout=5) as third:
            started = time.monotonic()
            third.sendall(b"GET /v1/health HTTP/1.0\r\n\r\n")
            answer = b""
            while chunk := third.recv(4096):
                answer += chunk
        assert answer.startswith(b"HTTP/1.0 503 "), answer[:200]
        assert time.monotonic() - started < 1.0
        assert "try again" in json.loads(answer.split(b"\r\n\r\n", 1)[1])["error"]

        for connection in idle:
            connection.close()
        time.sleep(0.3)
        with socket.create_connection(address, timeout=5) as fourth:
            fourth.sendall(b"GET /v1/health HTTP/1.0\r\n\r\n")
            assert fourth.recv(4096).startswith(b"HTTP/1.0 200 ")
    finally:
        server.shutdown()
        server.server_close()


def test_a_caller_within_its_deadline_is_answered_as_before(monkeypatch):
    server = _serve(monkeypatch, REQUEST_DEADLINE_SECONDS=5.0)
    try:
        with socket.create_connection(server.server_address[:2], timeout=5) as connection:
            connection.sendall(b"GET /v1/health HTTP/1.0\r\n\r\n")
            assert connection.recv(4096).startswith(b"HTTP/1.0 200 ")
    finally:
        server.shutdown()
        server.server_close()
