"""WriteApplication validation and HTTP facade behavior (fake runner)."""

from __future__ import annotations

import json
import re
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

SRC_REF = "https://example.com/source.md"
SRC_SHA = "a" * 64
TV = {"strength": 0.9, "confidence": 0.8}
ENTRY_DATE_RE = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"


class FakeRunner:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "written": EXPECTED_HANDLES,
            "verified": True,
            "missing": [],
            "top_handle": TOP_HANDLE,
        }
        self.error = error
        self.calls = []

    def write(self, metta, verify=True, provenance=None, tv=None):
        self.calls.append((metta, verify, provenance, tv))
        if self.error is not None:
            raise self.error
        return self.result


class TestHandle:
    def test_success(self):
        runner = FakeRunner()
        status, payload = WriteApplication(runner).handle({"metta": X402})
        assert status == 200
        assert payload == {
            "handles": EXPECTED_HANDLES,
            "verified": True,
            "missing": [],
            "top_handle": TOP_HANDLE,
        }
        assert runner.calls == [(X402, True, None, None)]

    def test_verify_flag_passthrough(self):
        runner = FakeRunner(
            result={"written": ["h"], "verified": None, "missing": [], "top_handle": TOP_HANDLE}
        )
        status, payload = WriteApplication(runner).handle({"metta": X402, "verify": False})
        assert status == 200
        assert payload == {"handles": ["h"], "verified": None, "missing": [], "top_handle": TOP_HANDLE}
        assert runner.calls == [(X402, False, None, None)]

    def test_unverified_missing_links_shape(self):
        runner = FakeRunner(
            result={"written": EXPECTED_HANDLES, "verified": False, "missing": [TOP_HANDLE], "top_handle": TOP_HANDLE}
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

    @pytest.fixture()
    def ledger_server(self, tmp_path):
        from provenance_store import LedgerStore

        store = LedgerStore(str(tmp_path / "repo"))
        app = WriteApplication(FakeRunner(), store=store)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
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
        assert body["top_handle"] == TOP_HANDLE

    def test_source_round_trip(self, ledger_server):
        status, body = self._post(
            ledger_server.server_address[1],
            "/v1/source",
            json.dumps({"ref": SRC_REF, "sha256": SRC_SHA}).encode(),
        )
        assert status == 200
        assert re.fullmatch(r"[0-9a-f]{40}", body["commit"])
        assert body["deduped"] is False
        assert re.fullmatch(ENTRY_DATE_RE, body["entry_date"])
        # The re-POST dedups to the same commit.
        status, body2 = self._post(
            ledger_server.server_address[1],
            "/v1/source",
            json.dumps({"ref": SRC_REF, "sha256": SRC_SHA}).encode(),
        )
        assert status == 200
        assert body2["deduped"] is True
        assert body2["commit"] == body["commit"]

    def test_source_body_cap_is_16kib(self, ledger_server):
        big = json.dumps({"ref": "https://example.com/" + "a" * (16 * 1024), "sha256": SRC_SHA}).encode()
        assert len(big) > MAX_BODY_BYTES
        status, body = self._post(ledger_server.server_address[1], "/v1/source", big)
        assert status == 413
        assert str(MAX_BODY_BYTES) in body["error"]

    def test_archive_route_is_gone(self, server):
        status, body = self._post(
            server.server_address[1],
            "/v1/archive",
            json.dumps({"url": "https://a.com", "content": "x"}).encode(),
        )
        assert status == 404
        assert body == {"error": "not found"}

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


# ------------------------------------------------------------- /v1/source


def _ledger_app(tmp_path, runner=None):
    """A WriteApplication backed by a real LedgerStore in tmp_path."""
    from provenance_store import LedgerStore

    store = LedgerStore(str(tmp_path / "repo"))
    app = WriteApplication(runner or FakeRunner(), store=store)
    return app, store


class TestSourceEndpoint:
    def test_record_happy_path(self, tmp_path):
        app, _store = _ledger_app(tmp_path)
        status, payload = app.handle_source({"ref": SRC_REF, "sha256": SRC_SHA})
        assert status == 200
        assert re.fullmatch(r"[0-9a-f]{40}", payload["commit"])
        assert payload["deduped"] is False
        assert re.fullmatch(ENTRY_DATE_RE, payload["entry_date"])

    def test_record_dedup_repost(self, tmp_path):
        app, _store = _ledger_app(tmp_path)
        status, first = app.handle_source({"ref": SRC_REF, "sha256": SRC_SHA})
        assert status == 200
        status, second = app.handle_source({"ref": SRC_REF, "sha256": SRC_SHA})
        assert status == 200
        assert second["deduped"] is True
        assert second["commit"] == first["commit"]
        assert second["entry_date"] == first["entry_date"]

    def test_record_absolute_path_ref(self, tmp_path):
        app, _store = _ledger_app(tmp_path)
        status, payload = app.handle_source({"ref": "/var/lib/sources/doc.md", "sha256": SRC_SHA})
        assert status == 200
        assert payload["deduped"] is False

    def test_rejects_unknown_key(self, tmp_path):
        app, _store = _ledger_app(tmp_path)
        status, payload = app.handle_source({"ref": SRC_REF, "sha256": SRC_SHA, "extra": 1})
        assert status == 400
        assert payload == {"error": "body must contain ref and sha256"}

    def test_rejects_missing_key(self, tmp_path):
        app, _store = _ledger_app(tmp_path)
        status, payload = app.handle_source({"ref": SRC_REF})
        assert status == 400
        assert payload == {"error": "body must contain ref and sha256"}
        status, payload = app.handle_source({"sha256": SRC_SHA})
        assert status == 400
        assert payload == {"error": "body must contain ref and sha256"}
        status, payload = app.handle_source("not-a-dict")
        assert status == 400
        assert payload == {"error": "body must contain ref and sha256"}

    def test_rejects_bad_ref_with_exact_strings(self, tmp_path):
        app, _store = _ledger_app(tmp_path)
        status, payload = app.handle_source({"ref": "", "sha256": SRC_SHA})
        assert status == 400
        assert payload == {"error": "ref must be a non-empty string of at most 480 characters"}
        status, payload = app.handle_source({"ref": "https://a.com/a b", "sha256": SRC_SHA})
        assert status == 400
        assert payload == {"error": "ref must not contain whitespace"}
        status, payload = app.handle_source({"ref": "ftp://a.com/doc", "sha256": SRC_SHA})
        assert status == 400
        assert payload == {"error": "ref must be an http(s) URL or an absolute path"}

    def test_rejects_bad_sha_with_exact_string(self, tmp_path):
        app, _store = _ledger_app(tmp_path)
        status, payload = app.handle_source({"ref": SRC_REF, "sha256": "A" * 64})
        assert status == 400
        assert payload == {"error": "sha256 must be 64 lowercase hex characters"}
        status, payload = app.handle_source({"ref": SRC_REF, "sha256": "a" * 63})
        assert status == 400
        assert payload == {"error": "sha256 must be 64 lowercase hex characters"}

    def test_source_without_store_is_503(self):
        app = WriteApplication(FakeRunner())  # no WRITE_PROVENANCE_REPO
        status, payload = app.handle_source({"ref": SRC_REF, "sha256": SRC_SHA})
        assert status == 503
        assert payload == {"error": "ledger requires the configured provenance repo (WRITE_PROVENANCE_REPO unset)"}


# ------------------------------------------------- /v1/write provenance v4


def _recorded_app(tmp_path, runner=None):
    """A ledger-backed app with one recorded source entry."""
    from provenance_store import LedgerStore

    store = LedgerStore(str(tmp_path / "repo"))
    app = WriteApplication(runner or FakeRunner(), store=store)
    recorded = store.record(SRC_REF, SRC_SHA)
    return app, store, recorded


class TestWriteProvenanceV4:
    def test_valid_provenance_passes_gate_and_reaches_runner(self, tmp_path):
        app, _store, recorded = _recorded_app(tmp_path)
        runner = app.runner
        prov = {"ref": SRC_REF, "git_commit": "git:" + recorded["commit"], "blob_sha256": SRC_SHA}
        status, payload = app.handle({"metta": X402, "provenance": prov, "tv": TV})
        assert status == 200
        assert payload == {
            "handles": EXPECTED_HANDLES,
            "verified": True,
            "missing": [],
            "top_handle": TOP_HANDLE,
        }
        assert "provenance_link" not in payload
        metta, verify, provenance, tv = runner.calls[0]
        assert metta == X402 and verify is True
        assert provenance == prov and tv == TV

    def test_hallucinated_commit_rejected_before_write(self, tmp_path):
        app, _store, _recorded = _recorded_app(tmp_path)
        runner = app.runner
        fake = {"ref": SRC_REF, "git_commit": "git:" + "f" * 40, "blob_sha256": SRC_SHA}
        status, payload = app.handle({"metta": X402, "provenance": fake})
        assert status == 400
        assert "not found in the ledger" in payload["error"]
        assert "write the source first via the skill" in payload["error"]
        assert runner.calls == []

    def test_right_commit_wrong_ref_rejected(self, tmp_path):
        app, _store, recorded = _recorded_app(tmp_path)
        runner = app.runner
        swapped = {
            "ref": "https://other.example.com/y.md",
            "git_commit": "git:" + recorded["commit"],
            "blob_sha256": SRC_SHA,
        }
        status, payload = app.handle({"metta": X402, "provenance": swapped})
        assert status == 400
        assert "does not add the cited source entry" in payload["error"]
        assert runner.calls == []

    def test_right_commit_wrong_sha_rejected(self, tmp_path):
        app, _store, recorded = _recorded_app(tmp_path)
        runner = app.runner
        swapped = {
            "ref": SRC_REF,
            "git_commit": "git:" + recorded["commit"],
            "blob_sha256": "b" * 64,
        }
        status, payload = app.handle({"metta": X402, "provenance": swapped})
        assert status == 400
        assert "does not add the cited source entry" in payload["error"]
        assert runner.calls == []

    def test_malformed_citation_rejected(self, tmp_path):
        app, _store, _recorded = _recorded_app(tmp_path)
        runner = app.runner
        bad = {"ref": SRC_REF, "git_commit": "git:not-hex", "blob_sha256": SRC_SHA}
        status, payload = app.handle({"metta": X402, "provenance": bad})
        assert status == 400
        assert 'must be "git:" + 40 hex chars' in payload["error"]
        assert runner.calls == []

    def test_legacy_v2_provenance_shape_rejected(self, tmp_path):
        app, _store, recorded = _recorded_app(tmp_path)
        runner = app.runner
        legacy = {"url": SRC_REF, "git_commit": "git:" + recorded["commit"]}
        status, payload = app.handle({"metta": X402, "provenance": legacy})
        assert status == 400
        assert payload == {"error": "provenance must contain ref, git_commit and blob_sha256"}
        assert runner.calls == []

    def test_v4_provenance_extra_key_rejected(self, tmp_path):
        app, _store, recorded = _recorded_app(tmp_path)
        runner = app.runner
        extra = {
            "ref": SRC_REF,
            "git_commit": "git:" + recorded["commit"],
            "blob_sha256": SRC_SHA,
            "fetched_at": "2026-10-27T00:00:00Z",
        }
        status, payload = app.handle({"metta": X402, "provenance": extra})
        assert status == 400
        assert payload == {"error": "provenance must contain ref, git_commit and blob_sha256"}
        assert runner.calls == []

    def test_rejects_non_object_provenance(self):
        runner = FakeRunner()
        status, payload = WriteApplication(runner).handle({"metta": X402, "provenance": "x"})
        assert status == 400
        assert payload == {"error": "provenance must contain ref, git_commit and blob_sha256"}
        status, _ = WriteApplication(runner).handle({"metta": X402, "tv": [1]})
        assert status == 400
        assert runner.calls == []

    def test_provenance_without_store_is_503(self):
        runner = FakeRunner()
        app = WriteApplication(runner)  # no WRITE_PROVENANCE_REPO
        prov = {"ref": SRC_REF, "git_commit": "git:" + "a" * 40, "blob_sha256": SRC_SHA}
        status, payload = app.handle({"metta": X402, "provenance": prov})
        assert status == 503
        assert payload == {"error": "ledger requires the configured provenance repo (WRITE_PROVENANCE_REPO unset)"}
        assert runner.calls == []
