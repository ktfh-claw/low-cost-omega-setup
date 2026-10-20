"""Opt-in, read-only client for the private DAS JSON proxy (v2).

v2 changes (2026-10-20, omega-das-bridge iteration 29, Balázs directive
16:01 UTC — "the read path must work", no workarounds):

- REQUEST: accept ``{"metta": <str>, "max_answers"?: <int>}`` (MeTTa-form
  mode — the only mode that reliably answers on the pinned engine), a
  lenient ``{"query": <str>}`` alias for metta (observed natural agent
  shape, live 2026-10-20), and the original ``{"tokens": [...],
  "max_answers"?: <int>}`` structural mode. ``max_answers`` is now
  optional (default 10). v1 required exactly ``{tokens, max_answers}`` and
  nothing else, while the read-proxy rejects plain token arrays (its
  structural mode only accepts the rigid LINK_TEMPLATE schema) — so the
  only working query shape was undiscoverable and das-retrieve NEVER
  returned data (live evidence iters 25-28: 12/12 attempts failed, the one
  exactly-compliant attempt got HTTP 400 at the proxy).
- RESPONSE: accept the proxy's actual success schema
  ``{"mode", "answers", "count", "truncated"}`` (``mode`` optional for
  forward compatibility). v1 required exactly
  ``{answers, count, truncated}`` and rejected every successful response
  (the proxy always includes ``mode``), so even a 200 would have failed.
- ERRORS: proxy error bodies (``{"error": "..."}`` on HTTP 400/502) are
  surfaced to the caller so the agent can self-correct instead of seeing
  a bare code.
- TIMEOUT: 10 s (was 5 s; live metta queries complete in 1.3-4+ s).
"""

from __future__ import annotations

import json
import math
import os
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit


DEFAULT_PROXY_ORIGIN = "http://read-proxy:8080"
QUERY_PATH = "/v1/query"
MAX_REQUEST_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_TOKENS = 128
MAX_TOKEN_CHARS = 512
MAX_METTA_CHARS = 1024  # mirrors the proxy's PROXY_MAX_METTA_CHARS
MAX_ANSWERS = 50
DEFAULT_ANSWERS = 10
REQUEST_TIMEOUT_SECONDS = 10
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 10_000
MAX_RESULT_STRING_CHARS = 16_384
MAX_ERROR_DETAIL_CHARS = 2048


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


def is_enabled() -> bool:
    """Return true only for the single explicit opt-in value."""
    return os.environ.get("OMEGA_DAS_ENABLED", "") == "1"


def _endpoint() -> str:
    origin = os.environ.get("OMEGA_DAS_PROXY_ORIGIN", DEFAULT_PROXY_ORIGIN)
    if not isinstance(origin, str) or not origin or origin.strip() != origin:
        raise ValueError("proxy origin is not canonical")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("proxy origin is invalid") from exc
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.netloc != f"{parsed.hostname}:{port}"
        or origin != f"http://{parsed.hostname}:{port}"
    ):
        raise ValueError("proxy origin must be an exact http origin with an explicit port")
    return origin + QUERY_PATH


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _request_bytes(query_json: str) -> tuple[bytes, int]:
    if not isinstance(query_json, str):
        raise ValueError("query must be a JSON string")
    try:
        encoded = query_json.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("query is not valid UTF-8 text") from exc
    if not encoded or len(encoded) > MAX_REQUEST_BYTES:
        raise ValueError(f"query must be 1..{MAX_REQUEST_BYTES} UTF-8 bytes")
    try:
        payload = json.loads(
            query_json,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON constant: {value}")),
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"query is not valid JSON: {exc.msg}") from exc
    except RecursionError as exc:
        raise ValueError("query JSON is too deeply nested") from exc
    if not isinstance(payload, dict):
        raise ValueError("query must be a JSON object")
    allowed = {"metta", "query", "tokens", "max_answers"}
    if set(payload) - allowed:
        raise ValueError(f"query may contain only: {sorted(allowed)}")
    modes = [key for key in ("metta", "query", "tokens") if key in payload]
    if len(modes) != 1:
        raise ValueError(
            'provide exactly one of metta (recommended: {"metta": "(Inheritance (Concept \\"x402\\") $X)", "max_answers": 10}), '
            "query (alias for metta), or tokens (LINK_TEMPLATE structural schema)"
        )
    max_answers = payload.get("max_answers", DEFAULT_ANSWERS)
    if type(max_answers) is not int or not 1 <= max_answers <= MAX_ANSWERS:
        raise ValueError(f"max_answers must be an integer from 1 to {MAX_ANSWERS}")
    mode = modes[0]
    if mode in ("metta", "query"):
        expression = payload[mode]
        if not isinstance(expression, str) or not expression or len(expression) > MAX_METTA_CHARS:
            raise ValueError(f"{mode} must be a non-empty string of at most {MAX_METTA_CHARS} characters")
        stripped = expression.strip()
        if not stripped.startswith("("):
            raise ValueError(
                f'{mode} must be a single parenthesized MeTTa expression, e.g. (Inheritance (Concept "x402") $X)'
            )
        if "$" not in stripped:
            raise ValueError(
                'ground (variable-free) MeTTa patterns never complete in the pinned engine; '
                'bind at least one target to a $variable, e.g. (Inheritance (Concept "x402") $X)'
            )
        normalized_payload = {"metta": stripped, "max_answers": max_answers}
    else:
        tokens = payload["tokens"]
        if (
            not isinstance(tokens, list)
            or not 1 <= len(tokens) <= MAX_TOKENS
            or not all(isinstance(token, str) and 1 <= len(token) <= MAX_TOKEN_CHARS for token in tokens)
        ):
            raise ValueError(f"tokens must be 1..{MAX_TOKENS} non-empty strings of at most {MAX_TOKEN_CHARS} characters")
        normalized_payload = {"tokens": tokens, "max_answers": max_answers}
    normalized = json.dumps(normalized_payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(normalized) > MAX_REQUEST_BYTES:
        raise ValueError(f"normalized query exceeds {MAX_REQUEST_BYTES} bytes")
    return normalized, max_answers


def _validate_json_value(value: Any, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
        raise ValueError("response JSON is too complex")
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("response number is not finite")
        return
    if isinstance(value, str):
        if len(value) > MAX_RESULT_STRING_CHARS:
            raise ValueError("response string is too long")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth + 1, counter)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ValueError("response object key is invalid")
            _validate_json_value(item, depth + 1, counter)
        return
    raise ValueError("response contains an unsupported JSON value")


def _read_response(response: Any, max_answers: int) -> tuple[list[Any], bool]:
    content_type = response.headers.get_content_type()
    if content_type != "application/json":
        raise ValueError("proxy response is not application/json")
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON constant: {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("proxy response is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("proxy response has an invalid schema")
    required = {"answers", "count", "truncated"}
    if not required <= set(payload) or set(payload) - (required | {"mode"}):
        raise ValueError("proxy response has an invalid schema")
    if "mode" in payload and payload["mode"] not in ("metta", "structural"):
        raise ValueError("proxy response has an invalid mode")
    answers = payload["answers"]
    if not isinstance(answers, list) or len(answers) > max_answers:
        raise ValueError("proxy returned too many answers")
    if type(payload["count"]) is not int or payload["count"] != len(answers):
        raise ValueError("proxy response count is invalid")
    if type(payload["truncated"]) is not bool:
        raise ValueError("proxy response truncated flag is invalid")
    _validate_json_value(answers)
    return answers, payload["truncated"]


def _proxy_error_detail(exc: urllib.error.HTTPError) -> str:
    """Best-effort extraction of the proxy's {"error": ...} body."""
    try:
        body = exc.read(MAX_ERROR_DETAIL_CHARS + 1)
        if len(body) > MAX_ERROR_DETAIL_CHARS:
            return ""
        detail = json.loads(body.decode("utf-8"))
        if isinstance(detail, dict) and isinstance(detail.get("error"), str):
            return detail["error"][:MAX_ERROR_DETAIL_CHARS]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        pass
    return ""


def das_retrieve(query_json: str) -> str:
    """Retrieve bounded DAS answers; all returned content is untrusted data."""
    if not is_enabled():
        return "DAS_RETRIEVE_FAILED: adapter is disabled"
    try:
        data, max_answers = _request_bytes(query_json)
        endpoint = _endpoint()
        request = urllib.request.Request(
            endpoint,
            data=data,
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        opener = urllib.request.build_opener(_NoRedirects())
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            answers, truncated = _read_response(response, max_answers)
        normalized = json.dumps(answers, ensure_ascii=True, separators=(",", ":"))
        return f"DAS_RETRIEVE_OK untrusted=true count={len(answers)} truncated={str(truncated).lower()} results={normalized}"
    except urllib.error.HTTPError as exc:
        detail = _proxy_error_detail(exc)
        return f"DAS_RETRIEVE_FAILED: proxy returned HTTP {exc.code}" + (f": {detail}" if detail else "")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return "DAS_RETRIEVE_FAILED: proxy request timed out"
        return "DAS_RETRIEVE_FAILED: proxy request failed"
    except (TimeoutError, socket.timeout):
        return "DAS_RETRIEVE_FAILED: proxy request timed out"
    except OSError:
        return "DAS_RETRIEVE_FAILED: proxy request failed"
    except ValueError as exc:
        return f"DAS_RETRIEVE_FAILED: {exc}"
