"""Checkpoint manifest writer for the das-extract-knowledge plugin (R3).

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
from datetime import datetime, timezone
from typing import Any

# The checkpoint manifest directory (inside the Omega memory volume).
CHECKPOINT_DIR = "/PeTTa/repos/Omega/memory/knowledge-checkpoints"

# Size limits for the manifest data.
MAX_MANIFEST_BYTES = 256 * 1024
MAX_PREDICATES = 1024
MAX_EXPRESSION_CHARS = 2048
MAX_HANDLE_CHARS = 256
MAX_SOURCE_CHARS = 480


def is_enabled() -> bool:
    """Return True iff OMEGA_DAS_ENABLED == 1 (same gate as das-read)."""
    return os.environ.get("OMEGA_DAS_ENABLED", "") == "1"


def _manifest_path(corpus_id: str) -> str:
    """Return the manifest path for a corpus ID."""
    # Sanitize the corpus ID (no path separators, no whitespace).
    safe = "".join(c for c in corpus_id if c.isalnum() or c in "-_")
    return os.path.join(CHECKPOINT_DIR, f"{safe}.md")


def _format_manifest_entry(predicate: dict[str, Any]) -> str:
    """Format a predicate entry for the manifest."""
    expression = predicate.get("expression", "")
    handle = predicate.get("handle", "")
    source = predicate.get("source", "")
    return f"expr {expression} top={handle} ref={source}"


def handle(body: Any) -> str:
    """Handle a das-extract-knowledge skill invocation.

    Actions:
    - "checkpoint": append the manifest data (predicates + receipts +
      sources + timestamp) to the checkpoint manifest for the corpus.
    - "describe": return the procedure text (a pointer to the skill
      description).

    Returns a receipt string (never raises).
    """
    try:
        data = json.loads(body) if isinstance(body, str) else body
    except (ValueError, TypeError):
        return "DAS-EXTRACT-KNOWLEDGE-FAILED: invalid JSON body"

    if not isinstance(data, dict):
        return "DAS-EXTRACT-KNOWLEDGE-FAILED: invalid JSON body"

    action = data.get("action", "describe")

    if action == "describe":
        return ("See the das-extract-knowledge skill description for the "
                "full procedure (read corpus once, extract predicates, "
                "persist via das-write, write checkpoint manifest).")

    if action == "checkpoint":
        corpus_id = data.get("corpus", "")
        if not corpus_id or not isinstance(corpus_id, str):
            return "DAS-EXTRACT-KNOWLEDGE-FAILED: corpus ID required"

        predicates = data.get("predicates", [])
        if not isinstance(predicates, list):
            return "DAS-EXTRACT-KNOWLEDGE-FAILED: predicates must be a list"

        # Write the manifest (append-only).
        manifest_path = _manifest_path(corpus_id)
        try:
            os.makedirs(CHECKPOINT_DIR, exist_ok=True)
        except OSError:
            return "DAS-EXTRACT-KNOWLEDGE-FAILED: could not create checkpoint directory"

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries = []
        for p in predicates:
            if not isinstance(p, dict):
                continue
            expression = p.get("expression", "")
            handle_ = p.get("handle", "")
            source = p.get("source", "")
            entries.append(f"expr {expression} top={handle_} ref={source}")

        with open(manifest_path, "a") as f:
            f.write(f"# Knowledge checkpoint: {corpus_id}\n")
            f.write(f"# Written: {timestamp}\n")
            for entry in entries:
                f.write(entry + "\n")

        return f"CHECKPOINT-WRITTEN: {manifest_path}"

    return "DAS-EXTRACT-KNOWLEDGE-FAILED: unknown action"
