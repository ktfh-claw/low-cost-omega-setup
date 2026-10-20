"""das_write_bridge interception logic with the HTTP call stubbed (no network)."""

from __future__ import annotations

import io
import json
import socket
import urllib.error
import urllib.request

import pytest

import das_write_bridge
from das_write_bridge import (
    DEFAULT_ORIGIN,
    MAX_METTA_CHARS,
    REQUEST_TIMEOUT_SECONDS,
    STATUS_OK,
    STATUS_REMOVE_UNSUPPORTED,
    STATUS_WRITE_FAILED,
    intercept,
    is_enabled,
)
# ----------------------------------------------------------------- helpers

class FakeResponse:
    """Minimal stand-in for the object returned by urlopen."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self, size: int | None = None) -> bytes:
        if size is None:
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
        spy.response = FakeResponse(json.dumps({"handles": ["h1"], "verified": True, "missing": []}).encode())
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
        spy.response = FakeResponse(json.dumps({"handles": ["h1"], "verified": True, "missing": []}).encode())
        assert intercept("!(add-atom &persistent (Concept foo))")[0].startswith(STATUS_OK)
        assert intercept("! (add-atom &persistent (Concept foo))")[0].startswith(STATUS_OK)

    def test_extra_whitespace_tolerated(self, enabled, spy):
        spy.response = FakeResponse(json.dumps({"handles": ["h1"], "verified": True, "missing": []}).encode())
        assert intercept("  (add-atom   &persistent   (Concept foo))  ")[0].startswith(STATUS_OK)

    def test_case_sensitive_markers(self, enabled, spy):
        assert intercept("(Add-atom &persistent (foo))") == []
        assert intercept("(REMOVE-ATOM &persistent (foo))") == []
        assert spy.calls == []


# ------------------------------------------------------------ payload slicing

class TestSlicing:
    def _ok_response(self, spy):
        spy.response = FakeResponse(json.dumps({"handles": ["h1"], "verified": True, "missing": []}).encode())

    def test_parens_inside_quoted_strings(self, enabled, spy):
        self._ok_response(spy)
        payload = '(Concept "foo (bar) baz")'
        result = intercept(f"(add-atom &persistent {payload})")
        assert result[0].startswith(STATUS_OK)
        assert spy.calls[0]["data"]["metta"] == payload

    def test_nested_balanced_expressions(self, enabled, spy):
        self._ok_response(spy)
        payload = "(Inheritance (Concept x) (Concept y))"
        result = intercept(f"(add-atom &persistent {payload})")
        assert result[0].startswith(STATUS_OK)
        assert spy.calls[0]["data"]["metta"] == payload

    def test_escaped_quote_inside_string(self, enabled, spy):
        self._ok_response(spy)
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
        assert result[0] == STATUS_WRITE_FAILED + ": expected one balanced expression after &persistent"
        assert spy.calls == []

    def test_trailing_garbage_fails(self, enabled, spy):
        result = intercept("(add-atom &persistent (Concept foo) extra)")
        assert len(result) == 1
        assert result[0] == STATUS_WRITE_FAILED + ": expected one balanced expression after &persistent"

    def test_two_expressions_fails(self, enabled, spy):
        result = intercept("(add-atom &persistent (Concept a) (Concept b))")
        assert len(result) == 1
        assert result[0] == STATUS_WRITE_FAILED + ": expected one balanced expression after &persistent"

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
        spy.response = FakeResponse(json.dumps({"handles": ["h1"], "verified": True, "missing": []}).encode())
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
        spy.response = FakeResponse(json.dumps({"handles": ["h1"], "verified": True, "missing": []}).encode())
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result[0].startswith(STATUS_OK)
        assert spy.calls[0]["url"] == DEFAULT_ORIGIN + "/v1/write"

    def test_request_shape(self, enabled, spy):
        spy.response = FakeResponse(json.dumps({"handles": ["h1"], "verified": True, "missing": []}).encode())
        intercept("(add-atom &persistent (Concept foo))")
        call = spy.calls[0]
        assert call["url"] == "http://write-bridge:8080/v1/write"
        assert call["data"] == {"metta": "(Concept foo)", "verify": True}
        assert call["timeout"] == REQUEST_TIMEOUT_SECONDS


# ------------------------------------------------------------ response paths

class TestResponses:
    def test_200_verified_true_formats_handles(self, enabled, spy):
        handles = ["h1", "h2", "h3", "h4", "h5"]
        spy.response = FakeResponse(json.dumps({"handles": handles, "verified": True, "missing": []}).encode())
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_OK + ": verified=5 handles=h1,h2,h3"]

    def test_200_verified_true_single_handle(self, enabled, spy):
        spy.response = FakeResponse(json.dumps({"handles": ["only"], "verified": True, "missing": []}).encode())
        result = intercept("(add-atom &persistent (Concept foo))")
        assert result == [STATUS_OK + ": verified=1 handles=only"]

    def test_200_verified_false_lists_missing(self, enabled, spy):
        spy.response = FakeResponse(json.dumps({"handles": ["h1", "h2"], "verified": False, "missing": ["h2"]}).encode())
        result = intercept("(add-atom &persistent (Concept foo))")
        assert len(result) == 1
        assert result[0].startswith(STATUS_WRITE_FAILED)
        assert "written but read-back verification missing handles:" in result[0]
        assert "h2" in result[0]

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
