"""history.metta window extraction v2 for the windowless-room gating test.

The benchmark window is defined by snapshots taken around the agent phase:

  - ``history.pre-benchmark-<run-id>.metta`` — copied by setup BEFORE the
    agent was restarted into benchmark mode,
  - ``history.post-benchmark-<run-id>.metta`` — copied by the agent phase
    right after all answers were present (or on timeout).

history.metta is append-only in practice, so the pre snapshot is a prefix of
the current file and the post snapshot bounds the window's end:

  window = history[len(pre) : len(post)]    (mode "pre+post")
  window = history[len(pre):]               (mode "pre-only" if no post)
  window = history                          (mode "full" if no usable pre)

das-retrieve calls appear in history with a quoted argument that is either
a raw MeTTa pattern or a JSON payload (``{"query"|"metta": ...,
"tokens": n, "max_answers": n}``). Both are normalized to the embedded
query pattern so the grader can match the agent's quoted QUERY: lines
against what actually executed.
"""
from __future__ import annotations

import json
import re

# das-retrieve with a quoted argument (raw or JSON-escaped), optionally
# wrapped as (das-retrieve (metta "..."))
RETRIEVE_CALL_RE = re.compile(
    r'das[-_]retrieve\s+(?:\(\s*metta\s+\s*)?"((?:[^"\\]|\\.)*)"', re.IGNORECASE
)
# a $_ placeholder inside a das-retrieve argument
PLACEHOLDER_RE = re.compile(r"\$_")
ADD_ATOM_SHA_RE = re.compile(r'git:([0-9a-f]{40})')


def window_from_texts(
    full_text: str, pre_text: str | None, post_text: str | None
) -> tuple[str, str]:
    """Return (window_text, mode) for the benchmark window.

    Callers on the OVH host read the (root-owned) files via sudo and pass
    the texts in; tests can pass texts directly.
    """
    if pre_text and full_text.startswith(pre_text):
        base = len(pre_text)
        if (
            post_text
            and full_text.startswith(post_text)
            and len(post_text) >= base
        ):
            return full_text[base : len(post_text)], "pre+post"
        return full_text[base:], "pre-only"
    return full_text, "full"


def _unescape(arg: str) -> str:
    """Unescape a quoted metta argument: try JSON, fall back to manual."""
    try:
        val = json.loads(f'"{arg}"')
        if isinstance(val, str):
            return val
    except (ValueError, TypeError):
        pass
    return (
        arg.replace('\\"', '"')
        .replace("\\\\", "\\")
        .replace("\\n", "\n")
    )


def normalize_query(arg: str) -> str:
    """Normalize a das-retrieve argument to the query pattern it carries.

    JSON payloads ({"query"|"metta": ...}) reduce to the embedded pattern;
    everything else is stripped whitespace.
    """
    arg = arg.strip()
    if arg.startswith("{"):
        try:
            d = json.loads(arg)
            if isinstance(d, dict):
                for key in ("metta", "query"):
                    val = d.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
        except (ValueError, TypeError):
            pass
    return arg


def extract_retrieve_args(window_text: str) -> list[str]:
    """Extract + normalize the arguments of das-retrieve calls in the window."""
    args: list[str] = []
    for m in RETRIEVE_CALL_RE.finditer(window_text):
        args.append(normalize_query(_unescape(m.group(1))))
    return args


def count_placeholder_retrieves(window_text: str) -> int:
    """Count das-retrieve calls whose argument carries a $_ placeholder."""
    count = 0
    for m in RETRIEVE_CALL_RE.finditer(window_text):
        if PLACEHOLDER_RE.search(m.group(1)):
            count += 1
    return count


def extract_add_atom_shas(window_text: str) -> list[str]:
    """Extract git:<sha> provenance citations from add-atom calls."""
    shas: list[str] = []
    for line in window_text.splitlines():
        if "add-atom" in line or "add_atom" in line:
            shas.extend(f"git:{s}" for s in ADD_ATOM_SHA_RE.findall(line))
    return shas


def extract_persist_receipts(window_text: str) -> list[str]:
    """Extract BRIDGE-PERSIST-OK receipt lines from the window."""
    return [ln.strip() for ln in window_text.splitlines() if "BRIDGE-PERSIST-OK" in ln]


def extract_archive_receipts(window_text: str) -> list[str]:
    """Extract ARCHIVE-OK receipt lines from the window."""
    return [ln.strip() for ln in window_text.splitlines() if "ARCHIVE-OK" in ln]
