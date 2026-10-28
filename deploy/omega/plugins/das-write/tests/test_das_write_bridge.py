"""das_write_bridge interception logic with the HTTP call stubbed (no network)."""

from __future__ import annotations

import hashlib
import io
import json
import socket
import urllib.error
import urllib.request

import pytest

import das_write_bridge
from das_write_bridge import (
    DEFAULT_ORIGIN,
    MAX_FETCH_CHARS,
    MAX_METTA_CHARS,
    REQUEST_TIMEOUT_SECONDS,
    STATUS_OK,
    STATUS_REMOVE_UNSUPPORTED,
    STATUS_WRITE_FAILED,
    intercept,
    is_enabled,
)

# ----------------------------------------------------------------- helpers

SOURCE_URL = "https://sources.example/background/spatial-knowledge.md"
SOURCE_CONTENT = "The room's spatial knowledge, verbatim.\n"
SOURCE_SHA = hashlib.sha256(SOURCE_CONTENT.encode("utf-8")).hexdigest()
LEDGER_COMMIT = "beef" * 10  # bare 40-hex commit returned by /v1/source
TOP_HANDLE = "fact-top-handle-1"

V3_FACT = '(Inheritance (Concept "WindowlessRoom") (Concept "SpatialCase"))'


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


class FakeHTTPError(urllib.error.HTTPError):
    """HTTPError with a readable body (the real one needs a file-like)."""

    def __init__(self, code: int, body: bytes):
        super().__init__(f"http://stub/{code}", code, "stub error", None, io.BytesIO(body))

    def read(self, size: int | None = None) -> bytes:
        return self.fp.read(size) if size is None else self.fp.read(size)


class UrlopenSpy:
    """Records the request and returns a scripted response or raises."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append({
            "url": request.full_url,
            "data": json.loads(request.data.decode("utf-8")),
            "timeout": timeout,
            "headers": dict(request.header_items()),
        })
        if self.error is not None:
            raise self.error
        return self.response


class FacadeRouter:
    """Fake urlopen routing the source fetch and the facade POSTs by URL.

    Records every call as (kind, url, body) with kind in
    {"fetch", "source", "write"}; each route serves a scripted response
    or raises a scripted error.
    """

    def __init__(self):
        self.calls = []
        self.fetch_response = FakeResponse(SOURCE_CONTENT.encode("utf-8"), "text/markdown")
        self.fetch_error = None
        self.source_response = {
            "commit": LEDGER_COMMIT,
            "deduped": False,
            "entry_date": "2026-10-28T00:00:00Z",
        }
        self.source_error = None
        self.write_response = {
            "handles": ["l1", "l2"],
            "verified": True,
            "missing": [],
            "top_handle": TOP_HANDLE,
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
        self.calls.append(("fetch", url, data))
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.fetch_response


@pytest.fixture(autouse=True)
def _source_cache():
    """Clear the module-level source cache around every test."""
    das_write_bridge._source_cache.clear()
    yield
    das_write_bridge._source_cache.clear()


@pytest.fixture()
def enabled(cfg):
    """Bridge enabled with the standard test origin (config-key based)."""
    cfg["dasWriteEnabled"] = "1"
    cfg["dasWriteOrigin"] = "http://write-bridge:8080"
    return cfg


@pytest.fixture()
def spy(monkeypatch):
    """Replace urlopen with a recorder; the test sets .response/.error."""
    recorder = UrlopenSpy()
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    return recorder


@pytest.fixture()
def router(monkeypatch):
    """Replace urlopen with the v3 source/facade router."""
    fake = FacadeRouter()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def _ok_response(top_handle=TOP_HANDLE, handles=("h1",), missing=(), verified=True):
    return FakeResponse(
        json.dumps(
            {
                "handles": list(handles),
                "verified": verified,
                "missing": list(missing),
                "top_handle": top_handle,
            }
        ).encode()
    )


def _v3_text(expr=V3_FACT, ref=SOURCE_URL):
    return f'(add-atom &persistent {expr} "{ref}")'


# ------------------------------------------------------------------- gating

class TestGating:
    def test_disabled_returns_empty_for_valid_persistent_add(self, cfg, spy):
        assert intercept("(add-atom &persistent (Concept foo))") == []
        assert spy.calls == []

    def test_enabled_value_must_be_exact_one(self, cfg, spy):
        cfg["dasWriteEnabled"] = "true"
        assert intercept("(add-atom &persistent (Concept foo))") == []

    def test_is_enabled_exact_one(self, cfg):
        assert is_enabled() is False
        cfg["dasWriteEnabled"] = "1"
        assert is_enabled() is True

    def test_is_enabled_accepts_yaml_int_one(self, cfg):
        # config.yaml carries a real int 1, not the string "1"
        cfg["dasWriteEnabled"] = 1
        assert is_enabled() is True

    def test_non_str_and_empty_fall_through(self, enabled, spy):
        assert intercept(None) == []
        assert intercept(123) == []
        assert intercept("") == []
        assert intercept("   ") == []
        assert spy.calls == []


# ---------------------------------------------------------------- detection

class TestDetection:
    @pytest.mark.parametrize("text", [
        "(add-atom &self (Concept foo))",
        "(add-atom &persistentX (Concept foo))",
        "(add-atom &Persistent (Concept foo))",
        "(ADD-ATOM &persistent (Concept foo))",
        "(Add-Atom &persistent (Concept foo))",
        "(remove-atom &self (Concept foo))",
        "(add (Concept foo))",
        "add-atom &persistent (Concept foo)",
        "(add-atom &persistent)",
        "(add-atom &persistent(Concept foo))",
        "(car &persistent (foo))",
        "!(add-atom &self (foo))",
    ])
    def test_non_targets_fall_through(self, enabled, spy, text):
        assert intercept(text) == []
        assert spy.calls == []

    def test_add_atom_persistent_is_target(self, enabled, spy):
        spy.response = _ok_response()
        result = intercept("(add-atom &persistent (Concept foo))")
        assert len(result) == 1
        assert result[0].startswith(STATUS_OK)
        assert len(spy.calls) == 1

    def test_remove_atom_persistent_is_target(self, enabled, spy):
        result = intercept("(remove-atom &persistent (Concept foo))")
        assert len(result) == 1
        assert result[0].startswith(STATUS_REMOVE_UNSUPPORTED)
        assert spy.calls == []

    def test_leading_bang_tolerated(self, enabled, spy):
        spy.response = _ok_response()
        assert intercept("!(add-atom &persistent (Concept foo))")[0].startswith(STATUS_OK)
        assert intercept("! (add-atom &persistent (Concept foo))")[0].startswith(STATUS_OK)

    def test_extra_whitespace_tolerated(self, enabled, spy):
        spy.response = _ok_response()
        assert intercept("  (add-atom   &persistent   (Concept foo))  ")[0].startswith(STATUS_OK)

    def test_case_sensitive_markers(self, enabled, spy):
        assert intercept("(Add-atom &persistent (foo))") == []
        assert intercept("(REMOVE-ATOM &persistent (foo))") == []
        assert spy.calls == []


# ------------------------------------------------------------ payload slicing

class TestSlicing:
    def _ok(self, spy):
        spy.response = _ok_response()

    def test_parens_inside_quoted_strings(self, enabled, spy):
        self._ok(spy)
        payload = '(Concept "foo (bar) baz")'
        result = intercept(f"(add-atom &persistent {payload})")
        assert result[0].startswith(STATUS_OK)
        assert spy.calls[0]["data"]["metta"] == payload

    def test_nested_balanced_expressions(self, enabled, spy):
        self._ok(spy)
        payload = "(Inheritance (Concept x) (Concept y))"
        result = intercept(f"(add-atom &persistent {payload})")
        assert result[0].startswith(STATUS_OK)
        assert spy.calls[0]["data"]["metta"] == payload

    def test_escaped_quote_inside_string(self, enabled, spy):
        self._ok(spy)
        payload = '(Concept "he\\"llo")'
        result = intercept(f'(add-atom &persistent {payload})')
        assert result[0].startswith(STATUS_OK)
        assert spy.calls[0]["data"]["metta"] == payload

    def test_empty_payload_fails(self, enabled, spy):
        result = intercept("(add-atom &persistent )")
        assert len(result) == 1
        assert result[0] == STATUS_WRITE_FAILED + ": expected one balanced expression after &persistent"
        assert spy.calls == []

    def test_missing_payload_fails(self, enabled, spy):
        result = intercept("(add-atom &persistent")
        assert result == []

    def test_unclosed_payload_fails(self, enabled, spy):
        result = intercept("(add-atom &persistent (Concept foo)")
        assert len(result) == 1
        # The balanced expression exists; the add-atom closing paren is
        # missing — the precise diagnosis.
        assert result[0] == STATUS_WRITE_FAILED + ": missing add-atom closing paren"
        assert spy.calls == []

    def test_trailing_garbage_fails(self, enabled, spy):
        result = intercept("(add-atom &persistent (Concept foo) extra)")
        assert len(result) == 1
        # Trailing content that is not a v3 source-ref suffix.
        assert result[0] == STATUS_WRITE_FAILED + ": unexpected content after the source reference"

    def test_two_expressions_fails(self, enabled, spy):
        result = intercept("(add-atom &persistent (Concept a) (Concept b))")
        assert len(result) == 1
        # A second expression is not a valid v3 source-ref suffix.
        assert result[0] == STATUS_WRITE_FAILED + ": unexpected content after the source reference"

    def test_bare_symbol_payload_fails(self, enabled, spy):
        result = intercept("(add-atom &persistent symbol)")
        assert len(result) == 1
        assert result[0] == STATUS_WRITE_FAILED + ": expected one balanced expression after &persistent"


# --------------------------------------------------------------- size cap

class TestSizeCap:
    def test_payload_over_2048_fails(self, enabled, spy):
        payload = "(Concept " + "x" * (MAX_METTA_CHARS) + ")"
        result = intercept(f"(add-atom &persistent {payload})")
        assert len(result) == 1
        assert result[0] == STATUS_WRITE_FAILED + ": expression exceeds 2048 characters"
        assert spy.calls == []

    def test_payload_exactly_2048_ok(self, enabled, spy):
        spy.response = _ok_response()
        payload = "(" + "x" * (MAX_METTA_CHARS - 2) + ")"
        assert len(payload) == MAX_METTA_CHARS
        result = intercept(f"(add-atom &persistent {payload})")
        assert result[0].startswith(STATUS_OK)


# --------------------------------------------------------- origin validation

class TestOriginValidation:
    @pytest.mark.parametrize("origin", [
        "http://write-bridge",
        "http://write-bridge:8080/",
        "http://write-bridge:8080/path",
        "https://write-bridge:8080",
        "write-bridge:8080",
        "http://user:pass@write-bridge:8080",
        "http://write-bridge:8080?q=1",
        " http://write-bridge:8080",
        "http://WRITE-BRIDGE:8080",
    ])
    def test_invalid_origin_fails(self, enabled, spy, origin):
        spy.response = FakeResponse(b"{}")
        enabled["dasWriteOrigin"] = origin
        result = intercept("(add-atom &persistent (Concept foo))")
        assert len(result) == 1
        assert result[0] == STATUS_WRITE_FAILED + ": invalid dasWriteOrigin"
        assert spy.calls == []

    def test_default_origin_used_when_unset(self, cfg, spy):
        cfg["dasWriteEnabled"] = "1"
        spy.response = _ok_response()
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result[0].startswith(STATUS_OK)
        assert spy.calls[0]["url"] == DEFAULT_ORIGIN + "/v1/write"

    def test_request_shape(self, enabled, spy):
        spy.response = _ok_response()
        intercept("(add-atom &persistent (Concept foo))")
        call = spy.calls[0]
        assert call["url"] == "http://write-bridge:8080/v1/write"
        assert call["data"] == {"metta": "(Concept foo)", "verify": True}
        assert call["timeout"] == REQUEST_TIMEOUT_SECONDS


# ------------------------------------------------------------ response paths

class TestResponses:
    def test_200_verified_true_formats_receipt(self, enabled, spy):
        handles = ["h1", "h2", "h3", "h4", "h5"]
        spy.response = _ok_response(top_handle="top-abc", handles=handles)
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_OK + ": verified=5 top=top-abc"]

    def test_200_verified_true_single_handle(self, enabled, spy):
        spy.response = _ok_response(top_handle="only-top", handles=["only"])
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_OK + ": verified=1 top=only-top"]

    def test_200_verified_false_lists_missing(self, enabled, spy):
        spy.response = _ok_response(
            top_handle="top-abc", handles=["h1", "h2"], missing=["h2"], verified=False
        )
        result = intercept("(add-atom &persistent (Concept foo))")
        assert len(result) == 1
        assert result[0].startswith(STATUS_WRITE_FAILED)
        assert "written but read-back verification missing handles:" in result[0]
        assert "h2" in result[0]

    def test_200_verified_true_missing_top_handle(self, enabled, spy):
        spy.response = FakeResponse(json.dumps({"handles": ["h1"], "verified": True, "missing": []}).encode())
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_WRITE_FAILED + ": invalid response from facade"]

    def test_200_verified_true_top_handle_not_a_string(self, enabled, spy):
        spy.response = FakeResponse(
            json.dumps({"handles": ["h1"], "verified": True, "missing": [], "top_handle": 123}).encode()
        )
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_WRITE_FAILED + ": invalid response from facade"]

    def test_400_returns_error_field(self, enabled, spy):
        spy.error = FakeHTTPError(400, json.dumps({"error": "metta must be a single parenthesized expression"}).encode())
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_WRITE_FAILED + ": metta must be a single parenthesized expression"]

    def test_502_returns_error_field(self, enabled, spy):
        spy.error = FakeHTTPError(502, json.dumps({"error": "atomdb write failed", "handles": ["h1"]}).encode())
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_WRITE_FAILED + ": atomdb write failed"]

    def test_http_error_with_unparseable_body(self, enabled, spy):
        spy.error = FakeHTTPError(500, b"not json")
        result = intercept("(add-atom &persistent (Concept foo))")
        assert len(result) == 1
        assert result[0].startswith(STATUS_WRITE_FAILED)
        assert result[0] != STATUS_WRITE_FAILED + ": "

    def test_urlerror_connection_refused(self, enabled, spy):
        spy.error = urllib.error.URLError(ConnectionRefusedError())
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_WRITE_FAILED + ": request failed"]

    def test_urlerror_timeout(self, enabled, spy):
        spy.error = urllib.error.URLError(socket.timeout())
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_WRITE_FAILED + ": request timed out"]

    def test_raw_timeout(self, enabled, spy):
        spy.error = TimeoutError()
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_WRITE_FAILED + ": request timed out"]

    def test_unparseable_200_body(self, enabled, spy):
        spy.response = FakeResponse(b"not json at all")
        result = intercept("(add-atom &persistent (Concept foo))")
        assert len(result) == 1
        assert result[0].startswith(STATUS_WRITE_FAILED)

    def test_200_with_unexpected_verified_value(self, enabled, spy):
        spy.response = FakeResponse(json.dumps({"handles": ["h1"], "verified": "yes", "missing": []}).encode())
        result = intercept("(add-atom &persistent (Concept foo))")
        assert len(result) == 1
        assert result[0].startswith(STATUS_WRITE_FAILED)


# ------------------------------------------------------- v3 source flow

class TestV3Flow:
    """v3: fetch/read the source, sha256, POST /v1/source, POST /v1/write."""

    def test_first_write_is_fetch_source_write(self, enabled, router):
        result = intercept(_v3_text())
        assert result == [STATUS_OK + f": verified=2 top={TOP_HANDLE}"]
        assert [call[0] for call in router.calls] == ["fetch", "source", "write"]
        assert router.calls[0][1] == SOURCE_URL
        # Exact /v1/source body: the plugin-computed sha256 of the content.
        assert router.calls[1][1] == "http://write-bridge:8080/v1/source"
        assert router.calls[1][2] == {"ref": SOURCE_URL, "sha256": SOURCE_SHA}
        # Exact /v1/write provenance.
        assert router.calls[2][1] == "http://write-bridge:8080/v1/write"
        assert router.calls[2][2]["provenance"] == {
            "ref": SOURCE_URL,
            "git_commit": "git:" + LEDGER_COMMIT,
            "blob_sha256": SOURCE_SHA,
        }
        assert router.calls[2][2]["metta"] == V3_FACT
        assert router.calls[2][2]["verify"] is True

    def test_cache_hit_second_write_single_post(self, enabled, router):
        assert intercept(_v3_text())[0].startswith(STATUS_OK)
        assert len(router.calls) == 3
        router.calls.clear()
        result = intercept(_v3_text(expr='(Concept "second-fact")'))
        assert result == [STATUS_OK + f": verified=2 top={TOP_HANDLE}"]
        # Cache hit: no fetch, no /v1/source — exactly ONE facade POST.
        assert len(router.calls) == 1
        assert router.calls[0][0] == "write"
        assert router.calls[0][2]["provenance"] == {
            "ref": SOURCE_URL,
            "git_commit": "git:" + LEDGER_COMMIT,
            "blob_sha256": SOURCE_SHA,
        }

    def test_dedup_propagation(self, enabled, router):
        original = "feed" * 10
        router.source_response = {
            "commit": original,
            "deduped": True,
            "entry_date": "2026-10-27T09:00:00Z",
        }
        result = intercept(_v3_text())
        assert result[0].startswith(STATUS_OK)
        # The write proceeds with the ORIGINAL commit returned by dedup.
        assert router.calls[2][2]["provenance"]["git_commit"] == "git:" + original

    def test_source_400_error_field(self, enabled, router):
        router.source_error = FakeHTTPError(
            400, json.dumps({"error": "ref must not contain whitespace"}).encode()
        )
        result = intercept(_v3_text())
        assert result == [
            STATUS_WRITE_FAILED + ": ledger append failed (ref must not contain whitespace)"
        ]
        assert [call[0] for call in router.calls] == ["fetch", "source"]

    def test_source_http_error_unparseable_body(self, enabled, router):
        router.source_error = FakeHTTPError(500, b"not json")
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": ledger append failed (HTTP 500)"]

    def test_source_malformed_200(self, enabled, router):
        router.source_response = {"deduped": False}
        result = intercept(_v3_text())
        assert result == [
            STATUS_WRITE_FAILED + ": ledger append failed (invalid response from facade)"
        ]

    def test_source_transport_error(self, enabled, router):
        router.source_error = urllib.error.URLError(ConnectionRefusedError())
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": ledger append failed (request failed)"]

    def test_source_timeout(self, enabled, router):
        router.source_error = urllib.error.URLError(socket.timeout())
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": ledger append failed (request timed out)"]

    def test_fetch_http_error(self, enabled, router):
        router.fetch_error = FakeHTTPError(404, b"gone")
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": source fetch failed (HTTP 404)"]
        assert [call[0] for call in router.calls] == ["fetch"]

    def test_fetch_urlerror_reason(self, enabled, router):
        router.fetch_error = urllib.error.URLError(OSError("boom"))
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": source fetch failed (boom)"]

    def test_fetch_timeout(self, enabled, router):
        router.fetch_error = urllib.error.URLError(socket.timeout())
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": fetch timed out"]

    def test_fetch_raw_timeout(self, enabled, router):
        router.fetch_error = TimeoutError()
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": fetch timed out"]

    def test_fetch_unsupported_content_type(self, enabled, router):
        router.fetch_response = FakeResponse(SOURCE_CONTENT.encode("utf-8"), "image/png")
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": unsupported content type image/png (text only)"]

    def test_fetch_empty_content(self, enabled, router):
        router.fetch_response = FakeResponse(b"   \n", "text/plain")
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": source content empty"]

    def test_fetch_oversize_content(self, enabled, router):
        router.fetch_response = FakeResponse(b"x" * (MAX_FETCH_CHARS + 1), "text/plain")
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": source exceeds the 2,000,000 character limit"]

    def test_write_verified_true_without_top_handle(self, enabled, router):
        router.write_response = {"handles": ["l1"], "verified": True, "missing": []}
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": invalid response from facade"]

    def test_write_verified_true_top_handle_not_a_string(self, enabled, router):
        router.write_response = {"handles": ["l1"], "verified": True, "missing": [], "top_handle": 123}
        result = intercept(_v3_text())
        assert result == [STATUS_WRITE_FAILED + ": invalid response from facade"]


# ------------------------------------------------------------- remove-atom

class TestRemoveAtom:
    def test_remove_atom_returns_unsupported(self, enabled, spy):
        result = intercept("(remove-atom &persistent (Concept foo))")
        assert result == [STATUS_REMOVE_UNSUPPORTED + ": remove-atom &persistent is not bridged yet; nothing was removed from DAS"]
        assert spy.calls == []

    def test_remove_atom_with_bang(self, enabled, spy):
        result = intercept("!(remove-atom &persistent (Concept foo))")
        assert result[0].startswith(STATUS_REMOVE_UNSUPPORTED)


# ---------------------------------------------------------------- never raises

class TestNeverRaises:
    def test_weird_input_never_raises(self, enabled, spy):
        for text in ["!", "!!", "(", ")", "((", '("', "add-atom", "&persistent", "(add-atom", "(remove-atom &persistent", "\x00"]:
            result = intercept(text)  # must not raise
            assert isinstance(result, list)
            assert len(result) <= 1

    def test_v3_weird_input_never_raises(self, enabled, spy):
        for text in [
            '(add-atom &persistent (Concept x) "git:',
            '(add-atom &persistent (Concept x) "unterminated',
            '(add-atom &persistent (Concept x) "https://x.example/a" "git:abc',
            '(add-atom &persistent (Concept x) "/no/such/root" extra"',
        ]:
            result = intercept(text)  # must not raise
            assert isinstance(result, list)
            assert len(result) <= 1
