"""Private-network HTTP facade for bounded, verified DAS writes."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from metta_to_atoms import MettaParseError
from provenance_store import ArchiveError, ProvenanceStore
from write_client import DasWriteRunner, WriteFailure

MAX_BODY_BYTES = 16 * 1024

# Archive bodies carry fetched page content: bounded well above the write
# body but still finite (8 MiB, matching the agent-side fetch cap).
MAX_ARCHIVE_BODY_BYTES = 8 * 1024 * 1024


class WriteApplication:
    def __init__(self, runner: Any, store: ProvenanceStore | None = None) -> None:
        self.runner = runner
        self.max_metta_chars = int(os.getenv("WRITE_MAX_METTA_CHARS", "2048"))
        repo_root = os.getenv("WRITE_PROVENANCE_REPO", "")
        self.store = store or (ProvenanceStore(repo_root) if repo_root else None)
        if repo_root and self.store is not None:
            self.store.ensure_repo()

    def handle(self, payload: Any) -> tuple[int, dict[str, Any]]:
        allowed = {"metta", "verify", "provenance", "tv"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            return 400, {"error": "body must contain metta and optional verify, provenance, tv"}
        if "metta" not in payload:
            return 400, {"error": "metta is required"}
        metta = payload["metta"]
        if not isinstance(metta, str) or not metta or len(metta) > self.max_metta_chars:
            return 400, {"error": f"metta must be a non-empty string of at most {self.max_metta_chars} characters"}
        if not metta.strip().startswith("("):
            return 400, {"error": "metta must be a single parenthesized expression"}
        verify = payload.get("verify", True)
        if not isinstance(verify, bool):
            return 400, {"error": "verify must be a boolean"}
        provenance = payload.get("provenance")
        if provenance is not None and not isinstance(provenance, dict):
            return 400, {"error": "provenance must be an object"}
        tv = payload.get("tv")
        if tv is not None and not isinstance(tv, dict):
            return 400, {"error": "tv must be an object"}
        try:
            result = self.runner.write(metta, verify=verify, provenance=provenance, tv=tv)
        except MettaParseError as exc:
            return 400, {"error": str(exc)}
        except WriteFailure as exc:
            # The write side is fire-and-forget: deterministic handles are
            # still returned (when known) so the operator can clean up or
            # re-check by handle.
            failure = {"error": str(exc)}
            if exc.handles:
                failure["handles"] = exc.handles
            return 502, failure
        response = {
            "handles": result["written"],
            "verified": result["verified"],
            "missing": result["missing"],
        }
        if result.get("provenance_link"):
            response["provenance_link"] = result["provenance_link"]
        return 200, response

    def handle_archive(self, payload: Any) -> tuple[int, dict[str, Any]]:
        """Archive fetched source content into the git provenance repo."""
        if self.store is None:
            return 503, {"error": "provenance archive is not configured (WRITE_PROVENANCE_REPO unset)"}
        if not isinstance(payload, dict) or set(payload) - {"url", "content", "content_type", "fetched_at"}:
            return 400, {"error": "body must contain url, content and optional content_type, fetched_at"}
        if "url" not in payload or "content" not in payload:
            return 400, {"error": "url and content are required"}
        try:
            result = self.store.archive(
                payload["url"],
                payload["content"],
                content_type=payload.get("content_type"),
                fetched_at=payload.get("fetched_at"),
            )
        except ArchiveError as exc:
            return 400, {"error": str(exc)}
        return 200, result


def make_handler(application: WriteApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path == "/v1/archive":
                max_body = MAX_ARCHIVE_BODY_BYTES
            elif self.path == "/v1/write":
                max_body = MAX_BODY_BYTES
            else:
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, {"error": "invalid Content-Length"})
                return
            if length <= 0 or length > max_body:
                self._send(413, {"error": f"request body must be 1..{max_body} bytes"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, {"error": "body must be valid JSON"})
                return
            if self.path == "/v1/archive":
                self._send(*application.handle_archive(payload))
            else:
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
    host = os.getenv("WRITE_HTTP_HOST", "0.0.0.0")
    port = int(os.getenv("WRITE_HTTP_PORT", "8080"))
    ThreadingHTTPServer((host, port), make_handler(WriteApplication(DasWriteRunner()))).serve_forever()
