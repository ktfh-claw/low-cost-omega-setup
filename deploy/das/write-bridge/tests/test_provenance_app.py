"""v2 provenance/tv write path and /v1/archive endpoint (fake runner + tmp store)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from app import WriteApplication, make_handler
from http.server import ThreadingHTTPServer

from conftest import EXPECTED_HANDLES, X402_METTA

X402 = X402_METTA

PROV = {"url": "https://example.com/x", "git_commit": "git:" + "a" * 40}
TV = {"strength": 0.9, "confidence": 0.8}


class FakeRunner:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "written": EXPECTED_HANDLES,
            "verified": True,
            "missing": [],
            "provenance_link": "provhandle",
        }
        self.error = error
        self.calls = []

    def write(self, metta, verify=True, provenance=None, tv=None):
        self.calls.append((metta, verify, provenance, tv))
        if self.error is not None:
            raise self.error
        return self.result


class TestProvenanceWrite:
    def test_provenance_tv_passthrough(self):
        runner = FakeRunner()
        status, payload = WriteApplication(runner).handle(
            {"metta": X402, "provenance": PROV, "tv": TV}
        )
        assert status == 200
        assert payload["provenance_link"] == "provhandle"
        metta, verify, provenance, tv = runner.calls[0]
        assert metta == X402 and verify is True
        assert provenance == PROV and tv == TV

    def test_provenance_without_link_omits_field(self):
        runner = FakeRunner(
            result={"written": EXPECTED_HANDLES, "verified": True, "missing": []}
        )
        status, payload = WriteApplication(runner).handle({"metta": X402, "provenance": PROV})
        assert status == 200
        assert "provenance_link" not in payload
        assert runner.calls[0][2] == PROV and runner.calls[0][3] is None

    def test_rejects_unknown_keys(self):
        runner = FakeRunner()
        status, payload = WriteApplication(runner).handle({"metta": X402, "bogus": 1})
        assert status == 400
        assert runner.calls == []

    def test_rejects_non_object_provenance(self):
        runner = FakeRunner()
        status, _ = WriteApplication(runner).handle({"metta": X402, "provenance": "x"})
        assert status == 400
        status, _ = WriteApplication(runner).handle({"metta": X402, "tv": [1]})
        assert status == 400
        assert runner.calls == []


class TestArchiveEndpoint:
    def _server(self, app):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{server.server_port}"
        server.shutdown()

    def test_archive_not_configured(self):
        app = WriteApplication(FakeRunner())  # no WRITE_PROVENANCE_REPO
        status, payload = app.handle_archive({"url": "https://a.com", "content": "x"})
        assert status == 503
        assert "not configured" in payload["error"]

    def test_archive_roundtrip(self, tmp_path):
        from provenance_store import ProvenanceStore

        store = ProvenanceStore(str(tmp_path / "repo"))
        app = WriteApplication(FakeRunner(), store=store)
        status, payload = app.handle_archive(
            {"url": "https://example.com/a", "content": "body", "content_type": "text/html"}
        )
        assert status == 200
        assert len(payload["commit"]) == 40
        assert payload["path"].endswith(".html")
        # Re-archive dedupes.
        status2, payload2 = app.handle_archive(
            {"url": "https://example.com/a", "content": "body", "content_type": "text/html"}
        )
        assert status2 == 200 and payload2["deduped"] is True
        assert payload2["commit"] == payload["commit"]

    def test_archive_rejects_bad_payload(self, tmp_path):
        from provenance_store import ProvenanceStore

        store = ProvenanceStore(str(tmp_path / "repo"))
        app = WriteApplication(FakeRunner(), store=store)
        status, _ = app.handle_archive({"url": "https://a.com"})
        assert status == 400
        status, _ = app.handle_archive({"url": "https://a.com", "content": "x", "extra": 1})
        assert status == 400
