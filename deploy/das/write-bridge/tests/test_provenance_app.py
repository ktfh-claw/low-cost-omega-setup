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

ARCHIVED_URL = "https://example.com/x"


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


def _archived_app(tmp_path, runner=None):
    """WriteApplication backed by a real store with one archived source."""
    from provenance_store import ProvenanceStore

    store = ProvenanceStore(str(tmp_path / "repo"))
    app = WriteApplication(runner or FakeRunner(), store=store)
    archived = store.archive(ARCHIVED_URL, "content-body", content_type="text/html")
    return app, store, archived


class TestProvenanceWrite:
    def test_provenance_tv_passthrough(self, tmp_path):
        app, _store, archived = _archived_app(tmp_path)
        prov = {"url": ARCHIVED_URL, "git_commit": "git:" + archived["commit"]}
        runner = app.runner
        status, payload = app.handle(
            {"metta": X402, "provenance": prov, "tv": TV}
        )
        assert status == 200
        assert payload["provenance_link"] == "provhandle"
        metta, verify, provenance, tv = runner.calls[0]
        assert metta == X402 and verify is True
        assert provenance == prov and tv == TV

    def test_provenance_without_link_omits_field(self, tmp_path):
        app, _store, archived = _archived_app(tmp_path)
        prov = {"url": ARCHIVED_URL, "git_commit": "git:" + archived["commit"]}
        runner = FakeRunner(
            result={"written": EXPECTED_HANDLES, "verified": True, "missing": []}
        )
        app.runner = runner
        status, payload = app.handle({"metta": X402, "provenance": prov})
        assert status == 200
        assert "provenance_link" not in payload
        assert runner.calls[0][2] == prov and runner.calls[0][3] is None

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


class TestCitationGate:
    """v2.1 Options A+B: write-time commit existence + URL cross-check."""

    def test_hallucinated_sha_rejected_before_write(self, tmp_path):
        app, _store, _archived = _archived_app(tmp_path)
        runner = app.runner
        fake = {"url": ARCHIVED_URL, "git_commit": "git:" + "f" * 40}
        status, payload = app.handle({"metta": X402, "provenance": fake})
        assert status == 400
        assert "not found in the archive" in payload["error"]
        assert "archive-source" in payload["error"] and "retry" in payload["error"]
        assert runner.calls == []

    def test_right_sha_wrong_url_rejected(self, tmp_path):
        app, _store, archived = _archived_app(tmp_path)
        runner = app.runner
        swapped = {"url": "https://other.example.com/y", "git_commit": "git:" + archived["commit"]}
        status, payload = app.handle({"metta": X402, "provenance": swapped})
        assert status == 400
        assert "archives a different source" in payload["error"]
        assert ARCHIVED_URL in payload["error"] and "other.example.com" in payload["error"]
        assert runner.calls == []

    def test_malformed_citation_rejected(self, tmp_path):
        app, _store, _archived = _archived_app(tmp_path)
        runner = app.runner
        bad = {"url": ARCHIVED_URL, "git_commit": "git:not-hex"}
        status, payload = app.handle({"metta": X402, "provenance": bad})
        assert status == 400
        assert "must be" in payload["error"]
        assert runner.calls == []

    def test_provenance_without_store_configured(self):
        runner = FakeRunner()
        app = WriteApplication(runner)  # no WRITE_PROVENANCE_REPO
        status, payload = app.handle({"metta": X402, "provenance": PROV})
        assert status == 503
        assert "WRITE_PROVENANCE_REPO" in payload["error"]
        assert runner.calls == []

    def test_valid_pair_passes_and_reaches_runner(self, tmp_path):
        app, _store, archived = _archived_app(tmp_path)
        runner = app.runner
        good = {"url": ARCHIVED_URL, "git_commit": "git:" + archived["commit"]}
        status, payload = app.handle({"metta": X402, "provenance": good, "tv": TV})
        assert status == 200 and payload["verified"] is True
        assert runner.calls[0][2] == good


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
