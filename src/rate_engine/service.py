"""The HTTP surface. Two routes, both thin, both over the one code path.

    POST /v1/quote           plans + a stay -> the fee and the breakdown
    POST /v1/validate-plan   a plan -> its gaps and conflicts
    GET  /v1/health          schema version, registered rule types

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

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .contract import SCHEMA_VERSION, run_quote, run_validate
from .rules import RULE_TYPES

#: Refuse a body larger than this rather than reading it into memory. A plan is
#: a few kilobytes; anything at this size is a mistake or an attempt.
MAX_BODY_BYTES = 1 << 20


class Handler(BaseHTTPRequestHandler):
    server_version = "openparking-rate-engine"
    sys_version = ""

    def _send(self, status: int, body: dict) -> None:
        payload = json.dumps(body, indent=2, sort_keys=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
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

    def do_POST(self) -> None:  # noqa: N802
        route = self.path.split("?")[0]
        runner = {"/v1/quote": run_quote, "/v1/validate-plan": run_validate}.get(route)
        if runner is None:
            self._send(404, {"error": "no such route"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, {"error": "unreadable Content-Length"})
            return
        if length > MAX_BODY_BYTES:
            self._send(413, {"error": f"body larger than {MAX_BODY_BYTES} bytes"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            document = json.loads(raw or b"null")
        except json.JSONDecodeError as exc:
            self._send(400, {"error": f"body is not JSON: {exc}"})
            return
        status, body = runner(document)
        self._send(status, body)

    def log_message(self, fmt: str, *args) -> None:
        """Quiet by default. A pricing request carries a garage's rate card."""


def make_server(host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:  # pragma: no cover - a loop
    server = make_server(host, port)
    print(f"rate-engine listening on http://{host}:{port} (schema v{SCHEMA_VERSION})")
    server.serve_forever()
