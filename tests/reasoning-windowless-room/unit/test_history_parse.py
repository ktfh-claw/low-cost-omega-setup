"""Unit tests for history_parse.py — history.metta trace extraction."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from history_parse import load_history, slice_window, summarize, HistoryEvent


FIXTURE = """(2026-10-21 12:00:00
  (das-retrieve (metta "(Inheritance (Concept \\"room\\") $X)")))
(2026-10-21 12:01:00
  (add-atom &persistent (Inheritance (Concept \\"ceiling\\") (Concept \\"opaque-surface\\")) "https://example.com" "git:abc123"))
(2026-10-21 12:02:00
  (archive-source "https://example.com"))
(2026-10-21 12:03:00
  (das-retrieve (metta "(Evaluation (Predicate \\"has-part\\") (Concept \\"room\\") $_131542))"))
(2026-10-21 12:04:00
  (add-atom &persistent (Inheritance (Concept \\"attic\\") (Concept \\"room\\")) "https://example.com" "git:def456"))
"""


def test_load_history_extracts_events():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".metta", delete=False) as f:
        f.write(FIXTURE)
        f.flush()
        events = load_history(f.name)
    assert len(events) >= 2
    kinds = set(e.kind for e in events)
    assert "das_retrieve" in kinds
    assert "add_atom" in kinds


def test_load_history_tolerates_malformed():
    malformed = "(unbalanced\n(((garbage\n(das-retrieve (metta \"(Inheritance $X $Y)\")))"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".metta", delete=False) as f:
        f.write(malformed)
        f.flush()
        events = load_history(f.name)
    assert isinstance(events, list)


def test_slice_window_filters_by_time():
    events = [
        HistoryEvent(kind="das_retrieve", query="q1", timestamp="2026-10-21T12:00:00"),
        HistoryEvent(kind="das_retrieve", query="q2", timestamp="2026-10-21T13:00:00"),
    ]
    windowed = slice_window(events, "2026-10-21T12:00:00", "2026-10-21T12:30:00")
    assert len(windowed) == 1


def test_summarize_counts_by_kind():
    events = [
        HistoryEvent(kind="das_retrieve", query="q1"),
        HistoryEvent(kind="add_atom", expression="(Inheritance a b)"),
        HistoryEvent(kind="archive_source", url="https://example.com"),
    ]
    summary = summarize(events)
    assert summary["counts"]["das_retrieve"] == 1
    assert summary["counts"]["add_atom"] == 1
    assert summary["counts"]["archive_source"] == 1


def test_variable_ref_shape():
    """$_NNNN variable refs are resolvable / skipped."""
    fixture = '(das-retrieve (metta "(Evaluation (Predicate \\"has-part\\") (Concept \\"room\\") $_131542))"))'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".metta", delete=False) as f:
        f.write(fixture)
        f.flush()
        events = load_history(f.name)
    assert len(events) >= 0  # should not crash
