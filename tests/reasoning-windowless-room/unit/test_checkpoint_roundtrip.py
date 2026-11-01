"""Checkpoint round-trip test (skill-split T04, R3).

Write a checkpoint manifest via the extraction skill's checkpoint writer,
read it back via the reasoning skill's checkpoint reader, and assert the
predicates round-trip verbatim (expressions character-for-character).

The test monkey-patches the CHECKPOINT_DIR to a temporary directory
(the production path /PeTTa/repos/Omega/memory/knowledge-checkpoints/
only exists inside the agent container).
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACT_DIR = os.path.join(HERE, "..", "..", "..", "deploy", "omega", "plugins", "das-extract-knowledge")
GROUNDED_DIR = os.path.join(HERE, "..", "..", "..", "deploy", "omega", "plugins", "das-grounded-reasoning")

sys.path.insert(0, EXTRACT_DIR)
sys.path.insert(0, GROUNDED_DIR)

import das_extract_knowledge
import das_grounded_reasoning


# ---------------------------------------------------------------------------
# round-trip: write → read → verbatim predicate reuse
# ---------------------------------------------------------------------------

def _with_tmpdir(fn):
    """Run fn with CHECKPOINT_DIR monkey-patched to a temp directory."""
    tmpdir = tempfile.mkdtemp(prefix="checkpoint-test-")
    das_extract_knowledge.CHECKPOINT_DIR = tmpdir
    das_grounded_reasoning.CHECKPOINT_DIR = tmpdir
    try:
        return fn(tmpdir)
    finally:
        das_extract_knowledge.CHECKPOINT_DIR = "/PeTTa/repos/Omega/memory/knowledge-checkpoints"


def test_roundtrip_verbatim_predicates():
    predicates = [
        {"expression": '(Inheritance (Concept "room") (Concept "enclosed-space"))', "handle": "h1", "source": "https://example.com/source-1"},
        {"expression": '(Evaluation (Predicate "has-part") (Concept "room") (Concept "wall"))', "handle": "h2", "source": "https://example.com/source-2"},
    ]
    def run(tmpdir):
        result = das_extract_knowledge.handle({
            "action": "checkpoint",
            "corpus": "test-corpus",
            "predicates": predicates,
        })
        assert "CHECKPOINT-WRITTEN" in result
        content = das_grounded_reasoning.handle({
            "action": "read_checkpoint",
            "corpus": "test-corpus",
        })
        for p in predicates:
            assert p["expression"] in content
            assert p["handle"] in content
    _with_tmpdir(run)


def test_reader_no_checkpoint():
    def run(tmpdir):
        result = das_grounded_reasoning.handle({
            "action": "read_checkpoint",
            "corpus": "nonexistent-corpus",
        })
        assert "FAILED" in result
    _with_tmpdir(run)


def test_writer_invalid_action():
    result = das_extract_knowledge.handle({"action": "invalid"})
    assert "FAILED" in result
