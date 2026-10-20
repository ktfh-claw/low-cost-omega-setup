"""Interception module for the ``&persistent`` hook (iteration 11).

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

# Path on the write-bridge facade for verified writes.
WRITE_PATH = "/v1/write"

# Size limit for the metta expression (mirrors WRITE_MAX_METTA_CHARS).
MAX_METTA_CHARS = 2048

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
            continue
        i += 1
    return None


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
        # add-atom path: the remainder after &persistent must be exactly
        # ONE balanced expression (string-aware paren counting; allow
        # surrounding whitespace).
        remainder = after_persistent[1:].lstrip()  # skip the whitespace char
        span = _balanced_span(remainder)
        if span is None:
            return [STATUS_WRITE_FAILED + ": expected one balanced expression after &persistent"]
        expr = remainder[span[0]:span[1]]
        # After the balanced expression, allow surrounding whitespace
        # and the add-atom wrapper’s closing paren (nothing else).
        if remainder[span[1]:].strip() != ")":
            return [STATUS_WRITE_FAILED + ": expected one balanced expression after &persistent"]
        # Payload size check.
        if len(expr) > MAX_METTA_CHARS:
            return [STATUS_WRITE_FAILED + ": expression exceeds 2048 characters"]
        # Post to the facade.
        return _post_to_facade(expr)
    # Not a target — fall through to stock MeTTa eval.
    return []


def _post_to_facade(payload: str) -> list[str]:
    """POST the payload to the write-bridge facade; return [status]."""
    origin = config_get_by_key("dasWriteOrigin", DEFAULT_ORIGIN)
    try:
        endpoint = _validate_origin(origin)
    except ValueError:
        return [STATUS_WRITE_FAILED + ": invalid dasWriteOrigin"]

    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"metta": payload, "verify": True}).encode("utf-8"),
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
                return [STATUS_OK + f": verified={n} handles={first3}"]
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
