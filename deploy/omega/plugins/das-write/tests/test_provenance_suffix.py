"""v2 provenance suffix parsing in das_write_bridge.intercept (fake facade)."""

from __future__ import annotations

import json
import urllib.request

import pytest

import das_write_bridge
from das_write_bridge import (
    STATUS_OK,
    STATUS_WRITE_FAILED,
    intercept,
)

FACT = '(Inheritance (Concept "TestNet") (Concept "AgentPaymentNetwork"))'
URL = "https://example.com/news/testnet"
SHA = "git:" + "ab12" * 10


@pytest.fixture()
def enabled(cfg):
    cfg["dasWriteEnabled"] = "1"
    return cfg


@pytest.fixture()
def spy(monkeypatch):
    """Record facade POSTs; return a list of (url, body_dict)."""
    posts = []

    class Recorder:
        def __init__(self, request, timeout=None):
            self.request = request
            self._data = json.loads(request.data.decode("utf-8"))

        def read(self, limit=-1):
            return json.dumps(
                {
                    "handles": ["h1", "h2"],
                    "verified": True,
                    "missing": [],
                    "provenance_link": "provlink",
                }
            ).encode("utf-8")

        def __enter__(self):
            posts.append((self.request.full_url, self._data))
            return self

        def __exit__(self, *exc):
            return False

        @property
        def status(self):
            return 200

    monkeypatch.setattr(urllib.request, "urlopen", Recorder)
    return posts


class TestProvenanceSuffix:
    def test_url_and_git_suffix_posted(self, enabled, spy):
        text = f'(add-atom &persistent {FACT} "{URL}" "{SHA}")'
        result = intercept(text)
        assert result and result[0].startswith(STATUS_OK)
        assert "provenance=provlink" in result[0]
        assert "source=archived" in result[0]
        url, body = spy[0]
        assert body["provenance"] == {"url": URL, "git_commit": SHA}
        assert "tv" not in body

    def test_full_suffix_with_stv(self, enabled, spy):
        text = f'(add-atom &persistent {FACT} "{URL}" "{SHA}" (stv 0.9 0.8))'
        result = intercept(text)
        assert result and result[0].startswith(STATUS_OK)
        assert "stv=(0.9,0.8)" in result[0]
        _, body = spy[0]
        assert body["tv"] == {"strength": 0.9, "confidence": 0.8}

    def test_stv_alone(self, enabled, spy):
        text = f"(add-atom &persistent {FACT} (stv 0.7 0.5))"
        result = intercept(text)
        assert result and result[0].startswith(STATUS_OK)
        _, body = spy[0]
        assert "provenance" not in body
        assert body["tv"] == {"strength": 0.7, "confidence": 0.5}

    def test_v1_form_unchanged(self, enabled, spy):
        result = intercept(f"(add-atom &persistent {FACT})")
        assert result and result[0].startswith(STATUS_OK)
        _, body = spy[0]
        assert "provenance" not in body and "tv" not in body

    def test_url_without_git_fails(self, enabled, spy):
        text = f'(add-atom &persistent {FACT} "{URL}")'
        result = intercept(text)
        assert result and result[0].startswith(STATUS_WRITE_FAILED)
        assert "both url and git commit" in result[0]
        assert spy == []

    def test_git_without_url_fails(self, enabled, spy):
        text = f'(add-atom &persistent {FACT} "{SHA}")'
        result = intercept(text)
        assert result and result[0].startswith(STATUS_WRITE_FAILED)
        assert spy == []

    def test_bad_sha_fails(self, enabled, spy):
        text = f'(add-atom &persistent {FACT} "{URL}" "git:xyz")'
        result = intercept(text)
        assert result and result[0].startswith(STATUS_WRITE_FAILED)
        assert spy == []

    def test_stv_out_of_range_fails(self, enabled, spy):
        text = f"(add-atom &persistent {FACT} (stv 1.5 0.8))"
        result = intercept(text)
        assert result and result[0].startswith(STATUS_WRITE_FAILED)
        assert spy == []

    def test_garbage_after_suffix_fails(self, enabled, spy):
        text = f'(add-atom &persistent {FACT} "{URL}" "{SHA}" extra)'
        result = intercept(text)
        assert result and result[0].startswith(STATUS_WRITE_FAILED)
        assert spy == []

    def test_whitespace_tolerated_in_suffix(self, enabled, spy):
        text = f'(add-atom &persistent  {FACT}  "{URL}"   "{SHA}"  (stv 0.8 0.6) )'
        result = intercept(text)
        assert result and result[0].startswith(STATUS_OK)
        _, body = spy[0]
        assert body["provenance"] == {"url": URL, "git_commit": SHA}
        assert body["tv"] == {"strength": 0.8, "confidence": 0.6}

    def test_url_with_space_fails(self, enabled, spy):
        text = f'(add-atom &persistent {FACT} "https://example.com/a b" "{SHA}")'
        result = intercept(text)
        assert result and result[0].startswith(STATUS_WRITE_FAILED)
        assert spy == []
