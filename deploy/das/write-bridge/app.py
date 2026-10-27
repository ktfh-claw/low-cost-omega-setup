"""Private-network HTTP facade for bounded, verified DAS writes."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from metta_to_atoms import MettaParseError
from provenance_store import ArchiveError, LedgerStore
from write_client import DasWriteRunner, WriteFailure

MAX_BODY_BYTES = 16 * 1024

_PROVENANCE_KEYS = {"ref", "git_commit", "blob_sha256"}


class WriteApplication:
    def __init__(self, runner: Any, store: LedgerStore | None = None) -> None:
        self.runner = runner
        self.max_metta_chars = int(os.getenv("WRITE_MAX_METTA_CHARS", "2048"))
        repo_root = os.getenv("WRITE_PROVENANCE_REPO", "")
        self.store = store or (LedgerStore(repo_root) if repo_root else None)
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
        if provenance is not None and (
            not isinstance(provenance, dict) or set(provenance) != _PROVENANCE_KEYS
        ):
            return 400, {"error": "provenance must contain ref, git_commit and blob_sha256"}
        tv = payload.get("tv")
        if tv is not None and not isinstance(tv, dict):
            return 400, {"error": "tv must be an object"}
        if provenance is not None:
            if self.store is None:
                return 503, {"error": "ledger requires the configured provenance repo (WRITE_PROVENANCE_REPO unset)"}
            # Provenance v4 citation gate: the cited commit must be a real
            # ledger commit adding exactly the cited (ref, sha256) entry.
            # Hallucinated or swapped citations are rejected with an
            # actionable, retryable message before anything reaches DAS.
            try:
                self.store.verify_commit(
                    provenance["git_commit"], provenance["ref"], provenance["blob_sha256"]
                )
            except ArchiveError as exc:
                return 400, {"error": str(exc)}
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
        return 200, {
            "handles": result["written"],
            "verified": result["verified"],
            "missing": result["missing"],
            "top_handle": result["top_handle"],
        }

    def handle_source(self, payload: Any) -> tuple[int, dict[str, Any]]:
        """Append one (ref, sha256) entry to the git source ledger."""
        if self.store is None:
            return 503, {"error": "ledger requires the configured provenance repo (WRITE_PROVENANCE_REPO unset)"}
        if not isinstance(payload, dict) or set(payload) != {"ref", "sha256"}:
            return 400, {"error": "body must contain ref and sha256"}
        try:
            result = self.store.record(payload["ref"], payload["sha256"])
        except ArchiveError as exc:
            return 400, {"error": str(exc)}
        return 200, result


def make_handler(application: WriteApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path in ("/v1/write", "/v1/source"):
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
            if self.path == "/v1/source":
                self._send(*application.handle_source(payload))
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
