"""v3 source-ref suffix parsing in das_write_bridge.intercept (fake facade)."""

from __future__ import annotations

import hashlib
import json
import urllib.request

import pytest

import das_write_bridge
from das_write_bridge import (
    MAX_METTA_CHARS,
    STATUS_OK,
    STATUS_WRITE_FAILED,
    intercept,
)

FACT = '(Inheritance (Concept "TestNet") (Concept "AgentPaymentNetwork"))'
URL = "https://example.com/news/testnet"
CONTENT = "TestNet launched its agent-payment network on 2026-10-27.\n"
CONTENT_SHA = hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
COMMIT = "ab12" * 10  # bare 40-hex commit returned by /v1/source
TOP = "fact-top-handle-1"

GIT_REJECTED = (
    STATUS_WRITE_FAILED
    + ": git citations are no longer accepted — pass the source reference; archiving is automatic"
)
BAD_REF = (
    STATUS_WRITE_FAILED
    + ": source ref must be an http(s) URL or an allowed absolute path (≤480 chars, no whitespace)"
)
UNEXPECTED = STATUS_WRITE_FAILED + ": unexpected content after the source reference"


@pytest.fixture(autouse=True)
def _source_cache():
    das_write_bridge._source_cache.clear()
    yield
    das_write_bridge._source_cache.clear()


@pytest.fixture()
def enabled(cfg):
    cfg["dasWriteEnabled"] = "1"
    cfg["dasWriteOrigin"] = "http://write-bridge:8080"
    return cfg


class FakeResponse:
    """Minimal stand-in for the object returned by urlopen."""

    def __init__(self, body: bytes, content_type: str = "application/json"):
        self._body = body
        self.status = 200
        self.headers = {"Content-Type": content_type}

    def read(self, size: int | None = None) -> bytes:
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Router:
    """Fake urlopen: the source fetch matched by URL, facade POSTs by path."""

    def __init__(self):
        self.calls = []  # (kind, url, body-or-None)
        self.fetch_response = FakeResponse(CONTENT.encode("utf-8"), "text/markdown")
        self.fetch_error = None
        self.source_response = {
            "commit": COMMIT,
            "deduped": False,
            "entry_date": "2026-10-28T00:00:00Z",
        }
        self.source_error = None
        self.write_response = {
            "handles": ["h1", "h2"],
            "verified": True,
            "missing": [],
            "top_handle": TOP,
        }
        self.write_error = None

    def __call__(self, request, timeout=None):
        url = request.full_url
        data = json.loads(request.data.decode("utf-8")) if request.data else None
        if url.endswith("/v1/source"):
            self.calls.append(("source", url, data))
            if self.source_error is not None:
                raise self.source_error
            return FakeResponse(json.dumps(self.source_response).encode())
        if url.endswith("/v1/write"):
            self.calls.append(("write", url, data))
            if self.write_error is not None:
                raise self.write_error
            return FakeResponse(json.dumps(self.write_response).encode())
        # Source fetch (matched by URL).
        self.calls.append(("fetch", url, data))
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.fetch_response


@pytest.fixture()
def router(monkeypatch):
    fake = Router()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def _write_text(expr=FACT, suffix=""):
    return f"(add-atom &persistent {expr}{suffix})"


class TestV3UrlRef:
    def test_url_ref_flow(self, enabled, router):
        result = intercept(_write_text(suffix=f' "{URL}"'))
        assert result == [STATUS_OK + f": verified=2 top={TOP}"]
        # Call order: fetch the source, ledger-append, then the gated write.
        kinds = [call[0] for call in router.calls]
        assert kinds == ["fetch", "source", "write"]
        assert router.calls[0][1] == URL
        assert router.calls[1][1] == "http://write-bridge:8080/v1/source"
        assert router.calls[2][1] == "http://write-bridge:8080/v1/write"
        # Exact /v1/source body: sha256 of the fake fetched content.
        assert router.calls[1][2] == {"ref": URL, "sha256": CONTENT_SHA}
        # Exact /v1/write provenance keys and values.
        write_body = router.calls[2][2]
        assert write_body["metta"] == FACT
        assert write_body["verify"] is True
        assert "tv" not in write_body
        assert set(write_body["provenance"]) == {"ref", "git_commit", "blob_sha256"}
        assert write_body["provenance"] == {
            "ref": URL,
            "git_commit": "git:" + COMMIT,
            "blob_sha256": CONTENT_SHA,
        }

    def test_url_ref_with_stv(self, enabled, router):
        result = intercept(_write_text(suffix=f' "{URL}" (stv 0.9 0.8)'))
        assert result == [STATUS_OK + f": verified=2 top={TOP} stv=(0.9,0.8)"]
        write_body = router.calls[2][2]
        assert write_body["tv"] == {"strength": 0.9, "confidence": 0.8}
        assert write_body["provenance"] == {
            "ref": URL,
            "git_commit": "git:" + COMMIT,
            "blob_sha256": CONTENT_SHA,
        }

    def test_whitespace_tolerated_in_suffix(self, enabled, router):
        result = intercept(f'(add-atom &persistent  {FACT}  "{URL}"   (stv 0.8 0.6) )')
        assert result == [STATUS_OK + f": verified=2 top={TOP} stv=(0.8,0.6)"]
        assert [call[0] for call in router.calls] == ["fetch", "source", "write"]


class TestV3PathRef:
    def test_path_ref_within_roots(self, enabled, router, tmp_path):
        content = "the room has no windows\n"
        source = tmp_path / "spatial.md"
        source.write_text(content, encoding="utf-8")
        enabled["dasWriteSourceRoots"] = str(tmp_path)
        result = intercept(_write_text(suffix=f' "{source}"'))
        assert result == [STATUS_OK + f": verified=2 top={TOP}"]
        # Path refs are read directly: no URL fetch, just the two POSTs.
        assert [call[0] for call in router.calls] == ["source", "write"]
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert router.calls[0][2] == {"ref": str(source), "sha256": sha}
        assert router.calls[1][2]["provenance"] == {
            "ref": str(source),
            "git_commit": "git:" + COMMIT,
            "blob_sha256": sha,
        }

    def test_path_ref_outside_roots(self, enabled, router, tmp_path):
        enabled["dasWriteSourceRoots"] = str(tmp_path / "roots")
        result = intercept(_write_text(suffix=' "/etc/hostname"'))
        assert result == [
            STATUS_WRITE_FAILED + ": source path outside the configured roots (dasWriteSourceRoots)"
        ]
        assert router.calls == []

    def test_path_ref_roots_unset(self, enabled, router, tmp_path):
        source = tmp_path / "spatial.md"
        source.write_text("content", encoding="utf-8")
        result = intercept(_write_text(suffix=f' "{source}"'))
        assert result == [
            STATUS_WRITE_FAILED + ": source path outside the configured roots (dasWriteSourceRoots)"
        ]
        assert router.calls == []


class TestV2Rejection:
    def test_git_token_alone(self, enabled, router):
        result = intercept(_write_text(suffix=f' "git:{"cd" * 20}"'))
        assert result == [GIT_REJECTED]
        assert router.calls == []

    def test_git_token_after_url(self, enabled, router):
        result = intercept(_write_text(suffix=f' "{URL}" "git:{"cd" * 20}"'))
        assert result == [GIT_REJECTED]
        assert router.calls == []

    def test_git_garbage_token_rejected(self, enabled, router):
        result = intercept(_write_text(suffix=' "git:xyz"'))
        assert result == [GIT_REJECTED]
        assert router.calls == []


class TestRefShape:
    def test_non_url_non_path_token(self, enabled, router):
        result = intercept(_write_text(suffix=' "ftp://example.com/x"'))
        assert result == [BAD_REF]
        assert router.calls == []

    def test_relative_path_token(self, enabled, router):
        result = intercept(_write_text(suffix=' "relative/path.md"'))
        assert result == [BAD_REF]
        assert router.calls == []

    def test_ref_over_480_chars(self, enabled, router):
        ref = "https://example.com/" + "a" * 461
        assert len(ref) == 481
        result = intercept(_write_text(suffix=f' "{ref}"'))
        assert result == [BAD_REF]
        assert router.calls == []

    def test_ref_with_whitespace(self, enabled, router):
        result = intercept(_write_text(suffix=' "https://example.com/a b"'))
        assert result == [BAD_REF]
        assert router.calls == []


class TestV1Unchanged:
    def test_v1_write_no_provenance(self, enabled, router):
        result = intercept(_write_text())
        assert result == [STATUS_OK + f": verified=2 top={TOP}"]
        assert len(router.calls) == 1
        url, body = router.calls[0][1], router.calls[0][2]
        assert url == "http://write-bridge:8080/v1/write"
        assert body == {"metta": FACT, "verify": True}

    def test_stv_alone_write(self, enabled, router):
        result = intercept(_write_text(suffix=" (stv 0.7 0.5)"))
        assert result == [STATUS_OK + f": verified=2 top={TOP} stv=(0.7,0.5)"]
        _, body = router.calls[0][1], router.calls[0][2]
        assert "provenance" not in body
        assert body["tv"] == {"strength": 0.7, "confidence": 0.5}


class TestTrailingContent:
    def test_garbage_after_ref(self, enabled, router):
        result = intercept(_write_text(suffix=f' "{URL}" extra'))
        assert result == [UNEXPECTED]
        assert router.calls == []

    def test_garbage_after_stv(self, enabled, router):
        result = intercept(_write_text(suffix=f' "{URL}" (stv 0.9 0.8) extra'))
        assert result == [UNEXPECTED]
        assert router.calls == []

    def test_second_quoted_token_after_url(self, enabled, router):
        result = intercept(_write_text(suffix=f' "{URL}" "https://other.example/x"'))
        assert result == [UNEXPECTED]
        assert router.calls == []

    def test_stv_out_of_range(self, enabled, router):
        result = intercept(_write_text(suffix=" (stv 1.5 0.8)"))
        assert result == [UNEXPECTED]
        assert router.calls == []


class TestSizeCap:
    def test_oversized_expression_with_ref(self, enabled, router):
        expr = "(Concept " + "x" * MAX_METTA_CHARS + ")"
        result = intercept(_write_text(expr=expr, suffix=f' "{URL}"'))
        assert result == [STATUS_WRITE_FAILED + ": expression exceeds 2048 characters"]
        assert router.calls == []

    def test_oversized_expression_v1(self, enabled, router):
        expr = "(Concept " + "x" * MAX_METTA_CHARS + ")"
        result = intercept(_write_text(expr=expr))
        assert result == [STATUS_WRITE_FAILED + ": expression exceeds 2048 characters"]
        assert router.calls == []
