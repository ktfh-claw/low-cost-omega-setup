"""Checkpoint manifest reader for the das-grounded-reasoning plugin (R3).

The checkpoint manifest is the phase boundary between the extraction and
reasoning phases: the extraction phase writes it (recording the extracted
predicates, their write receipts/handles, sources, and a timestamp), and
the reasoning phase reads it as its entry point into the knowledge base.

Path convention: /PeTTa/repos/Omega/memory/knowledge-checkpoints/<corpus-id>.md
(one manifest per corpus, append-only across runs).
"""

from __future__ import annotations

import json
import os
from typing import Any

# The checkpoint manifest directory (inside the Omega memory volume).
CHECKPOINT_DIR = "/PeTTa/repos/Omega/memory/knowledge-checkpoints"


def is_enabled() -> bool:
    """Return True iff OMEGA_DAS_ENABLED == 1 (same gate as das-read)."""
    return os.environ.get("OMEGA_DAS_ENABLED", "") == "1"


def _latest_manifest() -> str | None:
    """Return the latest checkpoint manifest path (mtime-desc), or None."""
    try:
        files = [f for f in os.listdir(CHECKPOINT_DIR) if f.endswith(".md")]
    except OSError:
        return None
    if not files:
        return None
    # Sort by mtime, descending.
    files.sort(key=lambda f: os.path.getmtime(os.path.join(CHECKPOINT_DIR, f)), reverse=True)
    return os.path.join(CHECKPOINT_DIR, files[0])


def _manifest_path(corpus_id: str) -> str:
    """Return the manifest path for a corpus ID."""
    safe = "".join(c for c in corpus_id if c.isalnum() or c in "-_")
    return os.path.join(CHECKPOINT_DIR, f"{safe}.md")


def handle(body: Any) -> str:
    """Handle a das-grounded-reasoning skill invocation.

    Actions:
    - "read_checkpoint": read the checkpoint manifest (latest or by
      corpus ID) and return its content (predicates verbatim).
    - "describe": return the procedure text (a pointer to the skill
      description).

    Returns the manifest content or an error string (never raises).
    """
    try:
        data = json.loads(body) if isinstance(body, str) else body
    except (ValueError, TypeError):
        return "DAS-GROUNDED-REASONING-FAILED: invalid JSON body"

    if not isinstance(data, dict):
        return "DAS-GROUNDED-REASONING-FAILED: invalid JSON body"

    action = data.get("action", "describe")

    if action == "describe":
        return ("See the das-grounded-reasoning skill description for the "
                "full procedure (read checkpoint, formalize question, "
                "retrieve from DAS, answer strictly from stored facts).")

    if action == "read_checkpoint":
        corpus = data.get("corpus")
        if corpus:
            manifest_path = _manifest_path(corpus)
        else:
            manifest_path = _latest_manifest()
        if not manifest_path or not os.path.exists(manifest_path):
            return "DAS-GROUNDED-REASONING-FAILED: no checkpoint manifest found"
        try:
            with open(manifest_path) as f:
                content = f.read()
            return content
        except OSError:
            return "DAS-GROUNDED-REASONING-FAILED: could not read checkpoint manifest"

    return "DAS-GROUNDED-REASONING-FAILED: unknown action"
