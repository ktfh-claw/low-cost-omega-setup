"""Interception module for the ``&persistent`` hook (iterations 11 + 21).

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

v2 (2026-10-21, provenance campaign): the add-atom form accepts an
optional PROVENANCE SUFFIX after the fact expression::

    (add-atom &persistent (Fact ...) "https://source-url" "git:<40hex>" (stv 0.9 0.8))

- quoted URL: the http(s) source the fact was derived from (archived
  first via the ``archive-source`` skill, which returns the git commit);
- quoted ``git:<40 hex>``: the commit hash of the archived source in the
  provenance git repo (host-side, bind-mounted into the facade);
- optional ``(stv <strength> <confidence>)``: PLN truth value, both
  floats in [0,1] — the epistemic status the campaign-import lane
  dropped.

Rules: url and git commit must appear together (archive first); the stv
form may appear alone. Without any suffix the v1 behavior is unchanged.

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
      violations, HTTP errors, timeouts, JSON errors)
    - ``BRIDGE-PERSIST-OK: ...`` — verified DAS write
    - ``BRIDGE-PERSIST-REMOVE-UNSUPPORTED: ...`` — remove-atom is not
      bridged in v1

    The module never raises; all failures surface as returned status
    strings (matching the contract in
    deploy/omega/plugins/das-write/das-write.metta).
"""

from __future__ import annotations

import json
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
ARCHIVE_PATH = "/v1/archive"

# Size limit for the metta expression (mirrors WRITE_MAX_METTA_CHARS).
MAX_METTA_CHARS = 2048

# v2 provenance suffix limits.
MAX_PROV_URL_CHARS = 480
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


def _validate_origin(origin: str) -> str:
    """Validate the origin; return the endpoint URL (origin + /v1/write)."""
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


def _parse_suffix(remainder: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Parse the optional v2 provenance suffix after the fact expression.

    ``remainder`` is the text between the end of the balanced fact
    expression and the add-atom wrapper's closing paren (the caller has
    NOT yet stripped the closing paren; it must be the last non-space
    character). Returns (provenance, tv, error) — provenance/tv are None
    when absent; error is a status reason string on shape violations.
    """
    i = 0
    n = len(remainder)
    url: str | None = None
    git_commit: str | None = None
    tv: dict[str, Any] | None = None

    def skip_ws(idx: int) -> int:
        while idx < n and remainder[idx] in (" ", "\t", "\n", "\r"):
            idx += 1
        return idx

    i = skip_ws(i)
    # Optional quoted URL.
    scanned = _scan_quoted_string(remainder, i)
    if scanned is not None:
        token, i = scanned
        value = token[1:-1]
        if value.startswith(("http://", "https://")):
            if len(value) > MAX_PROV_URL_CHARS or any(ch.isspace() for ch in value):
                return None, None, f"provenance url must be at most {MAX_PROV_URL_CHARS} chars without whitespace"
            url = value
        else:
            # Not a URL: the only other allowed quoted token is the git commit.
            if value.startswith("git:") and len(value) == 44 and all(
                ch in "0123456789abcdef" for ch in value[4:]
            ):
                git_commit = value
            else:
                return None, None, "quoted suffix must be the source URL or \"git:<40 hex>\""
        i = skip_ws(i)
    # Optional quoted git commit (also tolerated directly after a URL).
    scanned = _scan_quoted_string(remainder, i)
    if scanned is not None:
        token, i = scanned
        value = token[1:-1]
        if value.startswith("git:") and len(value) == 44 and all(
            ch in "0123456789abcdef" for ch in value[4:]
        ):
            if git_commit is not None:
                return None, None, "git commit given twice"
            git_commit = value
        else:
            return None, None, "second quoted suffix must be \"git:<40 hex>\""
        i = skip_ws(i)
    # Optional (stv strength confidence).
    parsed = _parse_stv(remainder, i)
    if parsed is not None:
        (strength, confidence), i = parsed
        tv = {"strength": strength, "confidence": confidence}
        i = skip_ws(i)
    # Only the add-atom closing paren may remain.
    if i >= n or remainder[i] != ")" or remainder[i + 1 :].strip():
        return None, None, "unexpected content after the provenance suffix"
    if (url is None) != (git_commit is None):
        return None, None, "provenance requires both url and git commit (archive the source first)"
    provenance = None
    if url is not None and git_commit is not None:
        provenance = {"url": url, "git_commit": git_commit}
    return provenance, tv, None


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
        # optionally followed by the v2 provenance suffix.
        remainder = after_persistent[1:].lstrip()  # skip the whitespace char
        span = _balanced_span(remainder)
        if span is None:
            return [STATUS_WRITE_FAILED + ": expected one balanced expression after &persistent"]
        expr = remainder[span[0]:span[1]]
        after_expr = remainder[span[1]:]
        # v1 shape: nothing but the closing paren after the expression.
        if after_expr.strip() == ")":
            # Payload size check.
            if len(expr) > MAX_METTA_CHARS:
                return [STATUS_WRITE_FAILED + ": expression exceeds 2048 characters"]
            return _post_to_facade(expr)
        # v2 shape: provenance suffix before the closing paren.
        if after_expr.strip() == "":
            return [STATUS_WRITE_FAILED + ": missing add-atom closing paren"]
        provenance, tv, error = _parse_suffix(after_expr)
        if error is not None:
            return [STATUS_WRITE_FAILED + ": " + error]
        if len(expr) > MAX_METTA_CHARS:
            return [STATUS_WRITE_FAILED + ": expression exceeds 2048 characters"]
        return _post_to_facade(expr, provenance=provenance, tv=tv)
    # Not a target — fall through to stock MeTTa eval.
    return []


def _post_to_facade(
    payload: str,
    provenance: dict[str, Any] | None = None,
    tv: dict[str, Any] | None = None,
) -> list[str]:
    """POST the payload to the write-bridge facade; return [status]."""
    origin = config_get_by_key("dasWriteOrigin", DEFAULT_ORIGIN)
    try:
        endpoint = _validate_origin(origin)
    except ValueError:
        return [STATUS_WRITE_FAILED + ": invalid dasWriteOrigin"]

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
                first3 = ",".join(str(h) for h in handles[:3])
                status = STATUS_OK + f": verified={n} handles={first3}"
                provenance_link = payload_json.get("provenance_link")
                if provenance_link:
                    status += f" provenance={provenance_link}"
                if provenance is not None:
                    status += " source=archived"
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


# ---------------------------------------------------------------- archive-source
# v2: the research-time source capture skill. Fetches URL content, hands it
# to the facade's git archive (/v1/archive), and returns the commit hash the
# agent then attaches to every fact derived from that source. This closes
# the URL-level provenance gap: the stock websearch skill drops URLs, so
# nothing downstream could reconstruct WHERE a fact came from.


def archive_source(url: Any) -> str:
    """Fetch ``url`` and archive its content via the facade; return a status.

    Returns ``ARCHIVE-OK git:<sha> sha256:<blob> path=<repo path>`` on
    success or ``ARCHIVE-FAILED: <reason>`` on any failure. Never raises.
    """
    if not is_enabled():
        return "ARCHIVE-FAILED: das-write plugin disabled (dasWriteEnabled != 1)"
    if not isinstance(url, str) or not url.strip():
        return "ARCHIVE-FAILED: url must be a non-empty string"
    url = url.strip()
    if url.startswith('"') and url.endswith('"') and len(url) >= 2:
        url = url[1:-1]
    if len(url) > MAX_PROV_URL_CHARS or any(ch.isspace() for ch in url):
        return "ARCHIVE-FAILED: url must be at most 480 chars without whitespace"
    if not url.startswith(("http://", "https://")):
        return "ARCHIVE-FAILED: url must be an http(s) URL"

    # 1. Fetch the content (bounded).
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "omega-research-agent/1.0 (+provenance-archiver)"},
        )
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return f"ARCHIVE-FAILED: HTTP {response.status} fetching the url"
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not (
                content_type.startswith(_TEXT_CONTENT_PREFIXES)
                or content_type in _TEXT_CONTENT_TYPES
                or content_type == ""
            ):
                return f"ARCHIVE-FAILED: unsupported content type {content_type or 'unknown'} (text only)"
            raw = response.read(MAX_FETCH_CHARS + 1)
            if len(raw) > MAX_FETCH_CHARS:
                return "ARCHIVE-FAILED: content exceeds the 2,000,000 character limit"
        content = raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return f"ARCHIVE-FAILED: HTTP {exc.code} fetching the url"
    except urllib.error.URLError as exc:
        reason = "timed out" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else str(exc.reason)
        return f"ARCHIVE-FAILED: fetch failed ({reason})"
    except (TimeoutError, socket.timeout):
        return "ARCHIVE-FAILED: fetch timed out"
    except Exception:
        return "ARCHIVE-FAILED: fetch failed"

    if not content.strip():
        return "ARCHIVE-FAILED: fetched content is empty"

    # 2. Archive it via the facade.
    origin = config_get_by_key("dasWriteOrigin", DEFAULT_ORIGIN)
    try:
        endpoint = _validate_origin(origin)[: -len(WRITE_PATH)] + ARCHIVE_PATH
    except ValueError:
        return "ARCHIVE-FAILED: invalid dasWriteOrigin"
    body = json.dumps(
        {"url": url, "content": content, "content_type": content_type or "text/plain"}
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_RESPONSE_BYTES:
                return "ARCHIVE-FAILED: archive response exceeds 64 KiB"
            result = json.loads(response_body)
            if not isinstance(result, dict) or "commit" not in result:
                return "ARCHIVE-FAILED: invalid archive response"
            commit = result["commit"]
            blob = result.get("blob_sha256", "")
            path = result.get("path", "")
            deduped = "deduped" if result.get("deduped") else "new"
            return f"ARCHIVE-OK {commit} sha256:{blob} path={path} ({deduped})"
    except urllib.error.HTTPError as exc:
        try:
            error_json = json.loads(exc.read())
            error_field = error_json.get("error") if isinstance(error_json, dict) else None
            if error_field:
                return f"ARCHIVE-FAILED: {error_field}"
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass
        return f"ARCHIVE-FAILED: HTTP {exc.code} from the archive"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return "ARCHIVE-FAILED: archive request timed out"
        return "ARCHIVE-FAILED: archive request failed"
    except (TimeoutError, socket.timeout):
        return "ARCHIVE-FAILED: archive request timed out"
    except json.JSONDecodeError:
        return "ARCHIVE-FAILED: invalid JSON from the archive"
    except Exception:
        return "ARCHIVE-FAILED: archive request failed"
