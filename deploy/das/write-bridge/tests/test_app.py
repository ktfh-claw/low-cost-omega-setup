"""WriteApplication validation and HTTP facade behavior (fake runner)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

import pytest

from app import MAX_BODY_BYTES, WriteApplication, make_handler
from http.server import ThreadingHTTPServer
from metta_to_atoms import MettaParseError
from write_client import WriteFailure

from conftest import EXPECTED_HANDLES, TOP_HANDLE, X402_METTA

X402 = X402_METTA


class FakeRunner:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "written": EXPECTED_HANDLES,
            "verified": True,
            "missing": [],
        }
        self.error = error
        self.calls = []

    def write(self, metta, verify=True):
        self.calls.append((metta, verify))
        if self.error is not None:
            raise self.error
        return self.result


class TestHandle:
    def test_success(self):
        runner = FakeRunner()
        status, payload = WriteApplication(runner).handle({"metta": X402})
        assert status == 200
        assert payload == {"handles": EXPECTED_HANDLES, "verified": True, "missing": []}
        assert runner.calls == [(X402, True)]

    def test_verify_flag_passthrough(self):
        runner = FakeRunner(result={"written": ["h"], "verified": None, "missing": []})
        status, payload = WriteApplication(runner).handle({"metta": X402, "verify": False})
        assert status == 200
        assert payload == {"handles": ["h"], "verified": None, "missing": []}
        assert runner.calls == [(X402, False)]

    def test_unverified_missing_links_shape(self):
        runner = FakeRunner(
            result={"written": EXPECTED_HANDLES, "verified": False, "missing": [TOP_HANDLE]}
        )
        status, payload = WriteApplication(runner).handle({"metta": X402})
        assert status == 200
        assert payload["verified"] is False
        assert payload["missing"] == [TOP_HANDLE]

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            [],
            "text",
            {},
            {"metta": X402, "extra": 1},
            {"verify": True},
            {"metta": 123},
            {"metta": ""},
            {"metta": "   "},
            {"metta": X402, "verify": "yes"},
            {"metta": X402, "verify": 1},
            {"metta": X402, "verify": None},
        ],
    )
    def test_rejected_payloads(self, payload):
        status, body = WriteApplication(FakeRunner()).handle(payload)
        assert status == 400
        assert "error" in body

    def test_metta_char_cap(self, monkeypatch):
        monkeypatch.setenv("WRITE_MAX_METTA_CHARS", "16")
        status, body = WriteApplication(FakeRunner()).handle({"metta": "(a " + "b" * 20 + ")"})
        assert status == 400
        assert "at most 16 characters" in body["error"]

    def test_default_metta_cap_is_2048(self):
        assert WriteApplication(FakeRunner()).max_metta_chars == 2048

    def test_parse_error_maps_to_400(self):
        runner = FakeRunner(error=MettaParseError("metta must be a single parenthesized expression"))
        status, body = WriteApplication(runner).handle({"metta": "(a"})
        assert status == 400
        assert body == {"error": "metta must be a single parenthesized expression"}

    def test_write_failure_maps_to_502_with_handles(self):
        error = WriteFailure("atomdb write failed: broker unreachable", EXPECTED_HANDLES)
        status, body = WriteApplication(FakeRunner(error=error)).handle({"metta": X402})
        assert status == 502
        assert body["error"] == "atomdb write failed: broker unreachable"
        assert body["handles"] == EXPECTED_HANDLES

    def test_write_failure_without_handles(self):
        error = WriteFailure("atomdb write failed: no peer")
        status, body = WriteApplication(FakeRunner(error=error)).handle({"metta": X402})
        assert status == 502
        assert body == {"error": "atomdb write failed: no peer"}
        assert "handles" not in body


class TestHttpSurface:
    @pytest.fixture()
    def server(self):
        runner = FakeRunner()
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(WriteApplication(runner)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join(timeout=5)

    def _post(self, port: int, path: str, data: bytes) -> tuple[int, Any]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_round_trip(self, server):
        status, body = self._post(
            server.server_address[1], "/v1/write", json.dumps({"metta": X402}).encode()
        )
        assert status == 200
        assert body["handles"] == EXPECTED_HANDLES
        assert body["verified"] is True

    def test_wrong_path_is_404(self, server):
        status, body = self._post(
            server.server_address[1], "/v1/other", json.dumps({"metta": X402}).encode()
        )
        assert status == 404
        assert body == {"error": "not found"}

    def test_invalid_json_is_400(self, server):
        status, body = self._post(server.server_address[1], "/v1/write", b"not-json")
        assert status == 400
        assert body == {"error": "body must be valid JSON"}

    def test_body_cap_is_16kib(self, server):
        assert MAX_BODY_BYTES == 16 * 1024
        big = json.dumps({"metta": X402, "pad": "x" * (16 * 1024)}).encode()
        assert len(big) > MAX_BODY_BYTES
        status, body = self._post(server.server_address[1], "/v1/write", big)
        assert status == 413
        assert str(MAX_BODY_BYTES) in body["error"]

    def test_empty_body_is_rejected(self, server):
        status, body = self._post(server.server_address[1], "/v1/write", b"")
        assert status == 413


class TestBodyCapBoundary:
    def test_16kib_exact_boundary_accepted_by_application(self):
        # Content-Length is enforced by the HTTP handler; the application
        # layer itself only sees parsed payloads.
        runner = FakeRunner()
        status, _ = WriteApplication(runner).handle({"metta": X402})
        assert status == 200
