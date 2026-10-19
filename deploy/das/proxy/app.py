"""Private-network HTTP facade for bounded, read-only DAS pattern queries."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from das_client import DasQueryRunner, QueryFailure

MAX_BODY_BYTES = 64 * 1024


class QueryApplication:
    def __init__(self, runner: Any) -> None:
        self.runner = runner
        self.max_answers = int(os.getenv("PROXY_MAX_ANSWERS", "100"))
        self.max_tokens = int(os.getenv("PROXY_MAX_QUERY_TOKENS", "256"))
        self.timeout = float(os.getenv("PROXY_QUERY_TIMEOUT_SECONDS", "30"))

    def handle(self, payload: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(payload, dict) or set(payload) - {"tokens", "max_answers"}:
            return 400, {"error": "body must contain only tokens and optional max_answers"}
        tokens = payload.get("tokens")
        if not isinstance(tokens, list) or not tokens or len(tokens) > self.max_tokens:
            return 400, {"error": f"tokens must be a non-empty array of at most {self.max_tokens} strings"}
        if any(not isinstance(token, str) or not token or len(token) > 1024 for token in tokens):
            return 400, {"error": "each token must be a non-empty string of at most 1024 characters"}
        max_answers = payload.get("max_answers", min(10, self.max_answers))
        if isinstance(max_answers, bool) or not isinstance(max_answers, int) or not 1 <= max_answers <= self.max_answers:
            return 400, {"error": f"max_answers must be an integer from 1 to {self.max_answers}"}
        try:
            answers = self.runner.query(tokens, max_answers, self.timeout)
        except QueryFailure as exc:
            return 502, {"error": str(exc)}
        return 200, {"answers": answers, "count": len(answers), "truncated": len(answers) >= max_answers}


def make_handler(application: QueryApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/v1/query":
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, {"error": "invalid Content-Length"})
                return
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send(413, {"error": "request body must be 1..65536 bytes"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, {"error": "body must be valid JSON"})
                return
            self._send(*application.handle(payload))

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"http {self.address_string()} {format % args}", flush=True)

    return Handler


if __name__ == "__main__":
    host = os.getenv("PROXY_HTTP_HOST", "0.0.0.0")
    port = int(os.getenv("PROXY_HTTP_PORT", "8080"))
    ThreadingHTTPServer((host, port), make_handler(QueryApplication(DasQueryRunner()))).serve_forever()
