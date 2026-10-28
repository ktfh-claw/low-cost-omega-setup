"""Interception module for the ``&persistent`` hook (iterations 11 + 21 + v4).

This module is a drop-in Omega plugin component (config-only bridge, no
source forks). The stock Omega ``metta`` skill parses the skill string
with ``sread`` and evaluates it with ``eval``/``swrite``; when
``add-atom &persistent X`` reaches that stock evaluation, PeTTa asserts
Prolog clauses into a space named ``persistent`` — durable only for the
container lifetime, never reaching history.metta or DAS. When
``remove-atom &persistent X`` reaches it, PeTTa removes clauses from
that same space. This module intercepts the skill string before stock
evaluation and, for expressions addressed to ``&persistent``, routes
the balanced payload expression to the write-bridge facade (already
deployed as a compose service on the ``omega-das-integration-client``
network) for a durable, verified DAS write.

v3/v4 (2026-10-28, transparent-provenance campaign): the add-atom form
accepts an optional SOURCE REFERENCE suffix after the fact expression::

    (add-atom &persistent (Fact ...) "https://source-url" (stv 0.9 0.8))

- quoted source ref: the http(s) URL OR the absolute container path the
  fact was derived from (path refs enabled only when the
  ``dasWriteSourceRoots`` configuration key lists an allowed root);
- optional ``(stv <strength> <confidence>)``: PLN truth value, both
  floats in [0,1].

Provenance is TRANSPARENT to the agent: the agent passes ONLY the
source reference. The plugin fetches (URL) or reads (path) the source,
computes sha256 of the content itself, appends the ``(ref, sha256)``
pair to the git source ledger via the facade's ``POST /v1/source``
(the commit hash is the provenance anchor), and then performs the
gated DAS write via ``POST /v1/write``. The agent never handles a git
commit, no separate source-capture skill is needed, and the agent is
unaware
of the provenance mechanics. A per-process cache (ref → sha256 +
commit) skips the fetch and the ledger append for subsequent writes
citing the same source. The v2 shape (quoted ``git:<sha>`` citations)
is rejected with an actionable message. Without any suffix the v1
behavior is unchanged when ``dasWriteRequireRef`` is unset; when it is
set to 1 (this deployment), suffix-less writes are rejected with an
actionable message and never reach DAS.

Contract:
    ``is_enabled() -> bool`` gates the whole path on the Omega configuration
    key ``dasWriteEnabled`` (resolved through the stock ``config`` machinery:
    command line > environment > config.yaml > default; the stock image
    entrypoint scrubs the agent environment down to an allowlist, so raw
    ``os.environ`` keys set at ``docker create`` time never survive to the
    agent process — the config API is the only launch-time path that
    reaches the plugin); ``intercept(text) -> list[str]``
    returns ``[]`` when the expression is NOT an interception target
    (the MeTTa wrapper in das-write.metta falls through to stock
    evaluation for everything else), and a single-element status list
    when handled. Statuses carry the reason in the string:

    - ``BRIDGE-PERSIST-WRITE-FAILED: ...`` — any failure routing to
      the facade (parse/shape violations, size violations, origin
      violations, source fetch/read failures, ledger append failures,
      HTTP errors, timeouts, JSON errors); under ``dasWriteRequireRef=1``
      a suffix-less (v1) write is rejected with the pinned ``a source
      reference is required on persistent writes — append the source
      URL or allowed path after the expression, e.g. (add-atom
      &persistent <expr> "<ref>")`` reason (missing source reference)
      before any facade POST
    - ``BRIDGE-PERSIST-OK: verified=<n> top=<handle> [stv=(s,c)]`` —
      verified DAS write (``top=`` is the fact's top-link handle from
      the facade response)
    - ``BRIDGE-PERSIST-REMOVE-UNSUPPORTED: ...`` — remove-atom is not
      bridged

    The module never raises; all failures surface as returned status
    strings (matching the contract in
    deploy/omega/plugins/das-write/das-write.metta).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

# Omega stock configuration API (``src/config.py``; importable because the
# plugin loader puts this plugin's directory on ``sys.path`` and the stock
# entrypoint exports ``PYTHONPATH`` with the Omega root and ``src`` on it).
# Resolution order is stock: command line > environment (OMEGA_<key>) >
# config.yaml > default. Import failure is intentional fail-closed: the
# plugin cannot load without the config API, the loader logs the error,
# and the agent keeps stock behavior.
from config import config_get_by_key

# Stock space name used by the metta skill for persistent atoms. The
# write-bridge facade is already deployed on the docker network
# omega-das-integration-client, listening on the default origin below.
DEFAULT_ORIGIN = "http://write-bridge:8080"

# Paths on the write-bridge facade.
WRITE_PATH = "/v1/write"
SOURCE_PATH = "/v1/source"

# Size limit for the metta expression (mirrors WRITE_MAX_METTA_CHARS).
MAX_METTA_CHARS = 2048

# v3 provenance suffix limits.
MAX_REF_CHARS = 480
MAX_FETCH_CHARS = 2_000_000
FETCH_TIMEOUT_SECONDS = 20

_TEXT_CONTENT_PREFIXES = ("text/",)
_TEXT_CONTENT_TYPES = ("application/json", "application/xml", "application/xhtml+xml", "application/javascript")

# Bounded response read (64 KiB).
MAX_RESPONSE_BYTES = 64 * 1024

# Request timeout for the facade POST.
REQUEST_TIMEOUT_SECONDS = 15

# Status prefixes.
STATUS_OK = "BRIDGE-PERSIST-OK"
STATUS_WRITE_FAILED = "BRIDGE-PERSIST-WRITE-FAILED"
STATUS_REMOVE_UNSUPPORTED = "BRIDGE-PERSIST-REMOVE-UNSUPPORTED"

# v2 rejection (pinned status string).
GIT_REJECTED = "git citations are no longer accepted — pass the source reference; archiving is automatic"
BAD_REF = "source ref must be an http(s) URL or an allowed absolute path (≤480 chars, no whitespace)"

# v1 rejection under dasWriteRequireRef=1 (pinned status reason).
REF_REQUIRED = "a source reference is required on persistent writes — append the source URL or allowed path after the expression, e.g. (add-atom &persistent <expr> \"<ref>\")"

# Per-process source cache: ref -> {"sha256": <64hex>, "commit": <40hex>}.
# A cache hit skips BOTH the source fetch and the ledger append; dedup on
# the facade makes cross-process re-POSTs idempotent end-to-end.
_source_cache: dict[str, dict[str, str]] = {}


def is_enabled() -> bool:
    """Return true only for the single explicit opt-in value.

    Reads the ``dasWriteEnabled`` configuration key through the stock
    Omega config machinery (command line ``dasWriteEnabled=1``, config.yaml
    ``dasWriteEnabled: 1``, or environment ``OMEGA_dasWriteEnabled=1``).
    ``str()`` normalization accepts both the string "1" (command line /
    environment) and the int 1 (config.yaml). Any other value keeps the
    stock persistence behavior untouched.
    """
    return str(config_get_by_key("dasWriteEnabled", "")) == "1"


def _require_ref() -> bool:
    """Return true when the dasWriteRequireRef opt-in is set.

    Reads the ``dasWriteRequireRef`` configuration key through the stock
    Omega config machinery. When ``1``, suffix-less (v1) persistent
    writes are rejected with the REF_REQUIRED failure reason.
    """
    return str(config_get_by_key("dasWriteRequireRef", "")) == "1"


def _validate_origin(origin: str) -> str:
    """Validate the origin; return the /v1/write endpoint URL."""
    if not isinstance(origin, str) or not origin or origin.strip() != origin:
        raise ValueError("write origin is not canonical")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("write origin is invalid") from exc
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
        raise ValueError("write origin must be an exact http origin with an explicit port")
    return origin + WRITE_PATH


def _balanced_span(text: str) -> tuple[int, int] | None:
    """Return the (start, end) span of the first balanced expression in text.

    ``text`` is the text after the ``&persistent`` token. The span is
    found by string-aware paren counting: an expression is balanced when
    its paren depth reaches zero (quotes inside the expression are
    respected; a quote inside the expression starts/ends a string and
    does not count toward the paren depth).
    """
    start = text.find("(")
    if start < 0:
        return None
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return (start, i + 1)
        elif ch == '"':
            # Skip quoted string (with escape awareness).
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 1
                    if i < n:
                        i += 1
                    continue
                if text[i] == '"':
                    break
                i += 1
        i += 1
    return None


def _scan_quoted_string(text: str, start: int) -> tuple[str, int] | None:
    """Scan a double-quoted string starting at ``start`` (must be a quote).

    Returns (unquoted_value, end_index_exclusive) or None when the text
    at ``start`` is not a quote or the string is unterminated. Escape
    sequences ``\\`` and ``\\"`` are preserved verbatim in the value
    (MeTTa string semantics; the facade receives the raw quoted token).
    """
    if start >= len(text) or text[start] != '"':
        return None
    i = start + 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            return (text[start : i + 1], i + 1)
        i += 1
    return None


def _parse_stv(text: str, start: int) -> tuple[tuple[float, float], int] | None:
    """Parse a ``(stv <strength> <confidence>)`` form starting at ``start``.

    Returns ((strength, confidence), end_index_exclusive) or None when
    the text at ``start`` is not that exact shape.
    """
    prefix = "(stv"
    if not text.startswith(prefix, start):
        return None
    rest = text[start + len(prefix) :]
    if not rest or rest[0] not in (" ", "\t", "\n"):
        return None
    close = rest.find(")")
    if close < 0:
        return None
    inner = rest[:close].split()
    if len(inner) != 2:
        return None
    try:
        strength = float(inner[0])
        confidence = float(inner[1])
    except ValueError:
        return None
    if not (0.0 <= strength <= 1.0 and 0.0 <= confidence <= 1.0):
        return None
    return (strength, confidence), start + len(prefix) + close + 1


def _parse_suffix(remainder: str) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """Parse the optional v3 provenance suffix after the fact expression.

    ``remainder`` is the text between the end of the balanced fact
    expression and the add-atom wrapper's closing paren (the caller has
    NOT yet stripped the closing paren; it must be the last non-space
    character). Returns (ref, tv, error) — ref/tv are None when absent;
    error is a status reason string on shape violations.
    """
    i = 0
    n = len(remainder)
    ref: str | None = None
    tv: dict[str, Any] | None = None

    def skip_ws(idx: int) -> int:
        while idx < n and remainder[idx] in (" ", "\t", "\n", "\r"):
            idx += 1
        return idx

    i = skip_ws(i)
    # Optional quoted source ref.
    scanned = _scan_quoted_string(remainder, i)
    if scanned is not None:
        token, i = scanned
        value = token[1:-1]
        if value.startswith("git:"):
            return None, None, GIT_REJECTED
        if value.startswith(("http://", "https://", "/")):
            if len(value) > MAX_REF_CHARS or any(ch.isspace() for ch in value):
                return None, None, BAD_REF
            ref = value
        else:
            return None, None, BAD_REF
        i = skip_ws(i)
        # A second quoted token is only possible in the retired v2 shape
        # (url + git citation) — both halves are rejected.
        scanned = _scan_quoted_string(remainder, i)
        if scanned is not None:
            token2, _ = scanned
            if token2[1:-1].startswith("git:"):
                return None, None, GIT_REJECTED
            return None, None, "unexpected content after the source reference"
    # Optional (stv strength confidence).
    parsed = _parse_stv(remainder, i)
    if parsed is not None:
        (strength, confidence), i = parsed
        tv = {"strength": strength, "confidence": confidence}
        i = skip_ws(i)
    # Only the add-atom closing paren may remain.
    if i >= n or remainder[i] != ")" or remainder[i + 1 :].strip():
        return None, None, "unexpected content after the source reference"
    return ref, tv, None


def _allowed_path_roots() -> list[str]:
    """Parse the dasWriteSourceRoots config key (comma/whitespace-separated)."""
    raw = config_get_by_key("dasWriteSourceRoots", "")
    if not isinstance(raw, str):
        return []
    return [root for root in re.split(r"[\s,]+", raw.strip()) if root]


def _resolve_source(ref: str) -> tuple[str, str | None]:
    """Resolve a source ref to its content; return (content, None) or (None, error).

    URL refs are fetched with the bounded fetch (User-Agent header, 20 s
    timeout, 2,000,000 character cap, text-only content types). Absolute
    path refs are allowed only when ``dasWriteSourceRoots`` is configured
    and ``realpath(ref)`` resolves inside one of its roots; the file is
    read with the same cap. Never raises.
    """
    if ref.startswith(("http://", "https://")):
        try:
            request = urllib.request.Request(
                ref,
                headers={"User-Agent": "omega-research-agent/1.0 (+provenance-archiver)"},
            )
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    return None, f"source fetch failed (HTTP {response.status})"
                content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if not (
                    content_type.startswith(_TEXT_CONTENT_PREFIXES)
                    or content_type in _TEXT_CONTENT_TYPES
                    or content_type == ""
                ):
                    return None, f"unsupported content type {content_type or 'unknown'} (text only)"
                raw = response.read(MAX_FETCH_CHARS + 1)
                if len(raw) > MAX_FETCH_CHARS:
                    return None, "source exceeds the 2,000,000 character limit"
            content = raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return None, f"source fetch failed (HTTP {exc.code})"
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                return None, "fetch timed out"
            return None, f"source fetch failed ({exc.reason})"
        except (TimeoutError, socket.timeout):
            return None, "fetch timed out"
        except Exception:
            return None, "source fetch failed"
        if not content.strip():
            return None, "source content empty"
        return content, None

    # Absolute container path: allowed only within the configured roots.
    roots = _allowed_path_roots()
    try:
        real = os.path.realpath(ref)
    except (OSError, ValueError):
        return None, "source path outside the configured roots (dasWriteSourceRoots)"
    inside = any(
        real == root.rstrip("/") or real.startswith(root.rstrip("/") + "/")
        for root in roots
        if root
    )
    if not inside:
        return None, "source path outside the configured roots (dasWriteSourceRoots)"
    try:
        with open(real, "rb") as f:
            raw = f.read(MAX_FETCH_CHARS + 1)
        if len(raw) > MAX_FETCH_CHARS:
            return None, "source exceeds the 2,000,000 character limit"
        content = raw.decode("utf-8", errors="replace")
    except (IOError, OSError):
        return None, f"source unreadable at {ref}"
    if not content.strip():
        return None, "source content empty"
    return content, None


def _post_source(origin_base: str, ref: str, sha256: str) -> tuple[str, str | None]:
    """Append (ref, sha256) to the ledger via POST /v1/source.

    Returns (commit, None) or (None, error) where the error is the inner
    facade reason for the ``ledger append failed (...)`` status.
    """
    request = urllib.request.Request(
        origin_base + SOURCE_PATH,
        data=json.dumps({"ref": ref, "sha256": sha256}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                return None, "response exceeds 64 KiB"
            result = json.loads(body)
            if not isinstance(result, dict) or not isinstance(result.get("commit"), str) or not result["commit"]:
                return None, "invalid response from facade"
            return result["commit"], None
    except urllib.error.HTTPError as exc:
        try:
            error_json = json.loads(exc.read())
            error_field = error_json.get("error") if isinstance(error_json, dict) else None
            if error_field:
                return None, str(error_field)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass
        return None, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return None, "request timed out"
        return None, "request failed"
    except (TimeoutError, socket.timeout):
        return None, "request timed out"
    except json.JSONDecodeError:
        return None, "invalid JSON response"
    except Exception:
        return None, "request failed"


def intercept(text: Any) -> list[str]:
    """Intercept the metta skill string; return [] for fall-through, [status] for handled."""
    if not is_enabled():
        return []
    if not isinstance(text, str) or not text.strip():
        return []

    stripped = text.strip()
    # Tolerate one optional leading "!" prefix character followed by
    # whitespace (the eval prefix on some skill strings).
    if stripped.startswith("!"):
        stripped = stripped[1:].lstrip()

    # Check for (add-atom or (remove-atom prefix (case-sensitive).
    for marker in ("add-atom", "remove-atom"):
        prefix = f"({marker}"
        if not stripped.startswith(prefix):
            continue
        rest = stripped[len(prefix):].lstrip()
        # After (add-atom or (remove-atom, expect whitespace, then
        # the exact token &persistent, then whitespace.
        if not rest.startswith("&persistent"):
            continue
        # Exact token check: &persistent must be followed by whitespace.
        after_persistent = rest[len("&persistent"):]
        if not after_persistent or after_persistent[0] not in (" ", "\t", "\n"):
            continue
        # Interception target detected.
        if marker == "remove-atom":
            return [STATUS_REMOVE_UNSUPPORTED + ": remove-atom &persistent is not bridged yet; nothing was removed from DAS"]
        # add-atom path: the remainder after &persistent must start with
        # exactly ONE balanced expression (string-aware paren counting)
        # optionally followed by the v3 provenance suffix.
        remainder = after_persistent[1:].lstrip()  # skip the whitespace char
        span = _balanced_span(remainder)
        if span is None:
            return [STATUS_WRITE_FAILED + ": expected one balanced expression after &persistent"]
        expr = remainder[span[0]:span[1]]
        after_expr = remainder[span[1]:]
        # v1 shape: nothing but the closing paren after the expression.
        if after_expr.strip() == ")":
            # dasWriteRequireRef=1 gate: a suffix-less write reaches DAS
            # with no provenance attrs and no ledger commit — reject
            # BEFORE the size check so the actionable guidance always wins.
            if _require_ref():
                return [STATUS_WRITE_FAILED + ": " + REF_REQUIRED]
            # Payload size check.
            if len(expr) > MAX_METTA_CHARS:
                return [STATUS_WRITE_FAILED + ": expression exceeds 2048 characters"]
            return _post_to_facade(expr)
        # v3 shape: provenance suffix before the closing paren.
        if after_expr.strip() == "":
            return [STATUS_WRITE_FAILED + ": missing add-atom closing paren"]
        ref, tv, error = _parse_suffix(after_expr)
        if error is not None:
            return [STATUS_WRITE_FAILED + ": " + error]
        # stv-alone suffix parses to ref=None — the same dasWriteRequireRef
        # gate, again BEFORE the size check so the guidance always wins.
        if ref is None and _require_ref():
            return [STATUS_WRITE_FAILED + ": " + REF_REQUIRED]
        if len(expr) > MAX_METTA_CHARS:
            return [STATUS_WRITE_FAILED + ": expression exceeds 2048 characters"]
        return _post_to_facade(expr, ref=ref, tv=tv)
    # Not a target — fall through to stock MeTTa eval.
    return []


def _post_to_facade(
    payload: str,
    ref: str | None = None,
    tv: dict[str, Any] | None = None,
) -> list[str]:
    """POST the payload to the write-bridge facade; return [status].

    v3 (``ref`` given): resolve the source, sha256 it, ledger-append via
    POST /v1/source (unless cached), then POST /v1/write with the
    provenance payload ``{ref, git_commit, blob_sha256}``.
    """
    if ref is None and _require_ref():
        # Defensive double gate (the dasWriteEnabled pattern): intercept()
        # rejects suffix-less writes under dasWriteRequireRef=1 before the
        # size checks; this guard keeps the invariant local to the POSTing
        # function in case a future caller bypasses intercept().
        return [STATUS_WRITE_FAILED + ": " + REF_REQUIRED]
    origin = config_get_by_key("dasWriteOrigin", DEFAULT_ORIGIN)
    try:
        endpoint = _validate_origin(origin)
    except ValueError:
        return [STATUS_WRITE_FAILED + ": invalid dasWriteOrigin"]
    origin_base = endpoint[: -len(WRITE_PATH)]

    provenance: dict[str, Any] | None = None
    if ref is not None:
        cached = _source_cache.get(ref)
        if cached is not None:
            sha256 = cached["sha256"]
            commit = cached["commit"]
        else:
            content, error = _resolve_source(ref)
            if error is not None:
                return [STATUS_WRITE_FAILED + ": " + error]
            sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
            commit, error = _post_source(origin_base, ref, sha256)
            if error is not None:
                return [STATUS_WRITE_FAILED + f": ledger append failed ({error})"]
            _source_cache[ref] = {"sha256": sha256, "commit": commit}
        provenance = {"ref": ref, "git_commit": "git:" + commit, "blob_sha256": sha256}

    body: dict[str, Any] = {"metta": payload, "verify": True}
    if provenance is not None:
        body["provenance"] = provenance
    if tv is not None:
        body["tv"] = tv
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                return [STATUS_WRITE_FAILED + ": response exceeds 64 KiB"]
            payload_json = json.loads(body)
            if not isinstance(payload_json, dict):
                return [STATUS_WRITE_FAILED + ": invalid response from facade"]
            if payload_json.get("verified") is True:
                handles = payload_json.get("handles") or []
                n = len(handles)
                top_handle = payload_json.get("top_handle")
                if not isinstance(top_handle, str) or not top_handle:
                    return [STATUS_WRITE_FAILED + ": invalid response from facade"]
                status = STATUS_OK + f": verified={n} top={top_handle}"
                if tv is not None:
                    status += f" stv=({tv['strength']},{tv['confidence']})"
                return [status]
            elif payload_json.get("verified") is False:
                missing = payload_json.get("missing") or []
                joined = ",".join(str(h) for h in missing)
                return [STATUS_WRITE_FAILED + f": written but read-back verification missing handles: {joined}"]
            else:
                return [STATUS_WRITE_FAILED + ": invalid response from facade"]
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read()
            error_json = json.loads(error_body)
            error_field = error_json.get("error") if isinstance(error_json, dict) else None
            if error_field:
                return [STATUS_WRITE_FAILED + f": {error_field}"]
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass
        return [STATUS_WRITE_FAILED + f": HTTP {exc.code}"]
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return [STATUS_WRITE_FAILED + ": request timed out"]
        return [STATUS_WRITE_FAILED + ": request failed"]
    except (TimeoutError, socket.timeout):
        return [STATUS_WRITE_FAILED + ": request timed out"]
    except json.JSONDecodeError:
        return [STATUS_WRITE_FAILED + ": invalid JSON response"]
    except Exception:
        return [STATUS_WRITE_FAILED + ": request failed"]
