"""The HTTP surface. Four routes, all thin, all over the one code path.

    POST /v1/quote               plans + a stay -> the fee and the breakdown
    POST /v1/validate-plan       a plan -> its gaps and conflicts
    POST /v1/validate-tax-sets   a garage's tax sets -> loaded, or refused by name
    POST /v1/tax                 tax sets + a subtotal at an instant -> the tax lines
    GET  /v1/health              schema version, registered rule types

Written on `http.server` rather than a framework, for the same reason
`vehicle-id` was: this module is arithmetic on integers with a door on it, and a
dependency here becomes a dependency in every integrator's build. §1 says any
software company can integrate with this module; the cheapest way to mean it is
to need nothing installed.

**No in-process shortcut.** Our own platform is an ordinary client of this door
(§1). There is no private path reserved for it, so if the public interface is
inadequate we feel it first -- which is the point of the rule.

This service TAKES NO MONEY and stores nothing. Calculation only, the same
standing rule the estate's other fee code keeps: no card, no payment, no
persistence. A plan arrives on the call and is gone when the response is written.
"""

from __future__ import annotations

import io
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .contract import (
    RETRY_AFTER_SECONDS,
    SCHEMA_VERSION,
    busy_response,
    encode,
    run_quote,
    run_tax,
    run_validate,
    run_validate_tax_sets,
)
from .limits import (
    MAX_CONCURRENT_VALIDATIONS,
    MAX_CONNECTIONS,
    REQUEST_DEADLINE_SECONDS,
)
from .rules import RULE_TYPES

#: Refuse a body larger than this rather than reading it into memory. A plan is
#: a few kilobytes; anything at this size is a mistake or an attempt.
MAX_BODY_BYTES = 1 << 20

#: Seconds a connection may wait on one read or write before it is closed. A
#: caller that stops sending part-way through a body would otherwise hold its
#: thread for as long as it keeps the connection open. A caller that keeps
#: sending, slowly, is bounded by `REQUEST_DEADLINE_SECONDS` for the whole
#: request instead.
SOCKET_TIMEOUT_SECONDS = 30


#: The validations running now, across every connection. Taken without waiting:
#: a caller over the limit is told so at once rather than queued behind work that
#: slows every quote in the process.
_VALIDATIONS = threading.BoundedSemaphore(MAX_CONCURRENT_VALIDATIONS)


class _ReadByDeadline(io.RawIOBase):
    """The connection's reads, each allowed only the time left before `deadline`.

    A per-read timeout restarts with every byte, so a caller trickling its
    request a byte at a time held its thread indefinitely. Here every read waits
    at most what is left of the request's whole allowance, and none once it is
    spent; the `TimeoutError` ends the request and closes the connection, as a
    per-read timeout always did (`BaseHTTPRequestHandler.handle_one_request`).
    """

    def __init__(self, connection: socket.socket, deadline: float, per_read: float) -> None:
        self._connection = connection
        self._deadline = deadline
        self._per_read = per_read

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        left = self._deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the request was not sent within its deadline")
        self._connection.settimeout(min(left, self._per_read))
        return self._connection.recv_into(buffer)


def _one_of_few_validations(document: object) -> tuple[int, dict]:
    """`run_validate`, unless `MAX_CONCURRENT_VALIDATIONS` are running already:
    then a 503 at once, and nothing run."""
    if not _VALIDATIONS.acquire(blocking=False):
        return 503, busy_response(RuntimeError(
            f"{MAX_CONCURRENT_VALIDATIONS} plans are being validated already; "
            "try again in a moment."
        ))
    try:
        return run_validate(document)
    finally:
        _VALIDATIONS.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "openparking-rate-engine"
    sys_version = ""
    #: `StreamRequestHandler.setup` sets this on the connection's socket. A read
    #: that times out ends the request and closes the connection.
    timeout = SOCKET_TIMEOUT_SECONDS

    def setup(self) -> None:
        super().setup()
        # The whole request, not each read, is what the caller is allowed.
        deadline = time.monotonic() + REQUEST_DEADLINE_SECONDS
        self.rfile = io.BufferedReader(_ReadByDeadline(self.connection, deadline, self.timeout))

    def _send(self, status: int, body: dict) -> None:
        # contract.encode is THE encoder. This used to call json.dumps itself,
        # one of three sites with two argument lists, which is how the published
        # byte-equality claim became false without anything going red.
        payload = encode(body)
        self._answered = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if status == 503:
            # Busy, not refused: the same request may be sent again (F67).
            self.send_header("Retry-After", str(RETRY_AFTER_SECONDS))
        self.end_headers()
        self.wfile.write(payload)

    def _answering(self, handle) -> None:
        """Run `handle`; if it raises, answer 500 rather than drop the connection.

        A refusal is never a 500: every one this module makes is a 400 or a 422
        with its sentence, and those return. This is for a bug, and it says no
        more than that -- a traceback would carry a garage's rate card into a
        response. A failed read or write is left to close the connection, and so
        is a failure after the answer began, which could not be told apart.
        """
        self._answered = False
        try:
            handle()
        except OSError:
            raise
        except Exception:
            if self._answered:
                raise
            self._send(500, {
                "schema_version": SCHEMA_VERSION,
                "error": "the engine failed on this request; nothing was priced.",
            })

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        self._answering(self._get)

    def do_POST(self) -> None:  # noqa: N802
        self._answering(self._post)

    def _get(self) -> None:
        if self.path.split("?")[0] != "/v1/health":
            self._send(404, {"error": "no such route"})
            return
        self._send(
            200,
            {
                "schema_version": SCHEMA_VERSION,
                "rule_types": sorted(RULE_TYPES),
                "takes_payment": False,
            },
        )

    def _post(self) -> None:
        route = self.path.split("?")[0]
        runner = {
            "/v1/quote": run_quote,
            "/v1/validate-plan": run_validate,
            "/v1/validate-tax-sets": run_validate_tax_sets,
            "/v1/tax": run_tax,
        }.get(route)
        if runner is None:
            self._send(404, {"error": "no such route"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, {"error": "unreadable Content-Length"})
            return
        if length < 0:
            # `rfile.read` with a negative size reads to the end of the
            # connection, with no bound at all.
            self._send(400, {"error": "Content-Length is negative"})
            return
        if length > MAX_BODY_BYTES:
            self._send(413, {"error": f"body larger than {MAX_BODY_BYTES} bytes"})
            return
        raw = self.rfile.read(length) if length else b""
        # DECODED HERE, STRICTLY, and only then parsed. `json.loads` handed BYTES
        # runs its own encoding detection: a UTF-16 or UTF-32 body, a UTF-8 body
        # behind a byte-order mark, and surrogates encoded as bytes were all
        # decoded and answered 200, while a malformed byte raised a
        # `UnicodeDecodeError` nothing caught and the connection dropped with no
        # answer at all. JSON over HTTP is UTF-8 (RFC 8259), and a caller that
        # decodes one set of bytes differently from this engine is judged on text
        # it never sent. An empty body is still `null`, and still refused by the
        # request's own sentence rather than by this one.
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._send(400, {"error": f"body is not UTF-8: {exc}"})
            return
        try:
            document = json.loads(text or "null")
        except json.JSONDecodeError as exc:
            self._send(400, {"error": f"body is not JSON: {exc}"})
            return
        except RecursionError:
            # Inside the 1 MiB bound a body can nest deeper than the parser
            # recurses; that crashed the request and nothing was answered.
            self._send(400, {"error": "body is nested too deeply to read."})
            return
        if runner is run_validate:
            runner = _one_of_few_validations
        status, body = runner(document)
        self._send(status, body)

    def log_message(self, fmt: str, *args) -> None:
        """Quiet by default. A pricing request carries a garage's rate card."""


class _BoundedServer(ThreadingHTTPServer):
    """A thread per connection, up to `MAX_CONNECTIONS` at once.

    Past that, the connection is answered 503 straight from the accepting
    thread and closed: a caller is told to come back rather than queued, and no
    number of idle or slow connections can take more threads than this.
    """

    #: Connections the kernel holds waiting to be accepted. The default, 5, made
    #: opening 64 at once take seconds, though every one is accepted at once.
    request_queue_size = 128

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request, client_address) -> None:
        if not self._slots.acquire(blocking=False):
            _answer_busy(request)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def _answer_busy(request: socket.socket) -> None:
    """A 503 written without a thread, through the one encoder. Best effort: a
    caller that cannot take a few hundred bytes at once is simply closed."""
    payload = encode(busy_response(RuntimeError(
        f"{MAX_CONNECTIONS} connections are being served already; try again in a moment."
    )))
    head = (
        "HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\nRetry-After: {RETRY_AFTER_SECONDS}\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    try:
        request.settimeout(1.0)
        request.sendall(head + payload)
    except OSError:
        pass


def make_server(host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    return _BoundedServer((host, port), Handler)


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:  # pragma: no cover - a loop
    server = make_server(host, port)
    print(f"rate-engine listening on http://{host}:{port} (schema v{SCHEMA_VERSION})")
    server.serve_forever()
