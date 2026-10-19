"""Private-network HTTP facade for bounded, read-only DAS pattern queries."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from das_client import DasQueryRunner, QueryFailure

MAX_BODY_BYTES = 64 * 1024


def _validate_structural_tokens(tokens: list[str]) -> str | None:
    """Reject structural schemas the pinned engine would silently never answer.

    The engine's only working structural dialect is LINK_TEMPLATE with a fixed
    arity and NODE/VARIABLE target specs. Anything else (wrong first token,
    arity/target mismatch, truncated specs, no variable) leaves the query
    hanging server-side until the client times out (verified live 2026-10-19,
    bridge iteration 2). The dialect is rigid, so the facade can parse and
    reject malformed shapes deterministically before touching the bus.
    """
    if tokens[0] != "LINK_TEMPLATE":
        return "structural queries must start with LINK_TEMPLATE; use the metta field for MeTTa-form queries"
    if len(tokens) < 4 or tokens[2] not in ("2", "3"):
        return "third token must be the link arity (2 or 3)"
    arity = int(tokens[2])
    position = 3
    variable_seen = False
    for _ in range(arity):
        if position >= len(tokens):
            return "fewer target specs than the declared arity"
        if tokens[position] == "NODE":
            if position + 3 > len(tokens):
                return "truncated NODE target spec"
            position += 3
        elif tokens[position] == "VARIABLE":
            if position + 2 > len(tokens):
                return "truncated VARIABLE target spec"
            variable_seen = True
            position += 2
        else:
            return f"invalid target spec at position {position}: expected NODE or VARIABLE"
    if position != len(tokens):
        return "more target specs than the declared arity"
    if not variable_seen:
        return "variable-free structural patterns never complete in the pinned engine; include at least one VARIABLE token and compare assignments client-side"
    return None


class QueryApplication:
    def __init__(self, runner: Any) -> None:
        self.runner = runner
        self.max_answers = int(os.getenv("PROXY_MAX_ANSWERS", "100"))
        self.max_tokens = int(os.getenv("PROXY_MAX_QUERY_TOKENS", "256"))
        self.max_metta_chars = int(os.getenv("PROXY_MAX_METTA_CHARS", "1024"))
        self.timeout = float(os.getenv("PROXY_QUERY_TIMEOUT_SECONDS", "30"))

    def handle(self, payload: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(payload, dict) or set(payload) - {"tokens", "metta", "max_answers"}:
            return 400, {"error": "body must contain only tokens or metta, and optional max_answers"}
        if ("tokens" in payload) == ("metta" in payload):
            return 400, {"error": "provide exactly one of tokens (structural) or metta (MeTTa-form)"}
        max_answers = payload.get("max_answers", min(10, self.max_answers))
        if isinstance(max_answers, bool) or not isinstance(max_answers, int) or not 1 <= max_answers <= self.max_answers:
            return 400, {"error": f"max_answers must be an integer from 1 to {self.max_answers}"}
        if "metta" in payload:
            # MeTTa-form query: one MeTTa expression string, parsed server-side by
            # the query engine's MettaParser (use_metta_as_query_tokens=true).
            # Engine caveat (verified live 2026-10-19, bridge iteration 2):
            # variable-free patterns NEVER complete in the pinned engine in
            # EITHER mode (server-side "Invalid LinkSchema with no variables" /
            # no answer flow), so a ground query would hang until timeout.
            # Reject them fast with guidance instead: bind one target to a
            # $variable and compare the returned assignments client-side.
            metta = payload["metta"]
            if not isinstance(metta, str) or not metta or len(metta) > self.max_metta_chars:
                return 400, {"error": f"metta must be a non-empty string of at most {self.max_metta_chars} characters"}
            if "$" not in metta:
                return 400, {"error": "ground (variable-free) MeTTa patterns never complete in the pinned engine; rewrite with at least one $variable and compare assignments client-side"}
            tokens, metta_mode = [metta], True
        else:
            tokens = payload["tokens"]
            if not isinstance(tokens, list) or not tokens or len(tokens) > self.max_tokens:
                return 400, {"error": f"tokens must be a non-empty array of at most {self.max_tokens} strings"}
            if any(not isinstance(token, str) or not token or len(token) > 1024 for token in tokens):
                return 400, {"error": "each token must be a non-empty string of at most 1024 characters"}
            schema_error = _validate_structural_tokens(tokens)
            if schema_error:
                return 400, {"error": schema_error}
            metta_mode = False
        try:
            answers = self.runner.query(tokens, max_answers, self.timeout, metta_mode=metta_mode)
        except QueryFailure as exc:
            return 502, {"error": str(exc)}
        return 200, {"mode": "metta" if metta_mode else "structural", "answers": answers, "count": len(answers), "truncated": len(answers) >= max_answers}


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
