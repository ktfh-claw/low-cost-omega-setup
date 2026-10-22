"""Unit tests for history_parse.py v2 — benchmark window + retrieval extraction."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from history_parse import (
    window_from_texts,
    extract_retrieve_args,
    count_placeholder_retrieves,
    extract_add_atom_shas,
    normalize_query,
)


PRE = '''(2026-10-21 12:00:00 (das-retrieve (metta "(Inheritance $X $Y)")))
(2026-10-21 12:01:00 (add-atom &persistent (Inheritance (Concept "room") $X) "https://example.com"))
'''

WINDOW = '''(2026-10-21 23:36:00 (das-retrieve "(Inheritance $X (Concept \\"ceiling\\"))"))
(2026-10-21 23:37:00 (das-retrieve (metta "(Inheritance (Concept \\"attic\\") $X)")))
(2026-10-21 23:38:00 (das-retrieve (metta "(Evaluation (Predicate \\"has-part\\") (Concept \\"room\\") $_131542))"))
(2026-10-21 23:39:00 (add-atom &persistent (Inheritance (Concept "ceiling") (Concept "opaque-surface")) "https://raw.githubusercontent.com/x/y" "git:8ffa0b35049c1b9545b08700c0594dc5eb68043e")
'''


def test_window_pre_post_suffix():
    full = PRE + WINDOW
    window, mode = window_from_texts(full, PRE, full)
    assert mode == "pre+post"
    assert window == full[len(PRE):]
    assert "ceiling" in window


def test_window_pre_only_when_no_post():
    full = PRE + WINDOW
    window, mode = window_from_texts(full, PRE, None)
    assert mode == "pre-only"
    assert window.startswith("(2026-10-21 23:36")


def test_window_full_when_no_pre():
    _, mode = window_from_texts(PRE + WINDOW, None, None)
    assert mode == "full"


def test_window_full_when_pre_not_prefix():
    # history rewritten/truncated: pre no longer a prefix -> reduced-strength
    _, mode = window_from_texts("garbage", PRE, None)
    assert mode == "full"


def test_extract_retrieve_args_normalizes():
    args = extract_retrieve_args(WINDOW)
    assert "(Inheritance $X (Concept \"ceiling\"))" in args
    assert "(Inheritance (Concept \"attic\") $X)" in args


def test_extract_retrieve_args_json_payload():
    text = '(das-retrieve "{\\"query\\":\\"(Inheritance $X $Y)\\",\\"tokens\\":8,\\"max_answers\\":3}")'
    args = extract_retrieve_args(text)
    assert args == ["(Inheritance $X $Y)"]


def test_count_placeholder_retrieves():
    assert count_placeholder_retrieves(WINDOW) == 1
    assert count_placeholder_retrieves(PRE) == 0


def test_extract_add_atom_shas():
    shas = extract_add_atom_shas(WINDOW)
    assert shas == ["git:8ffa0b35049c1b9545b08700c0594dc5eb68043e"]


def test_normalize_query_passthrough():
    assert normalize_query("  (Inheritance $X $Y) ") == "(Inheritance $X $Y)"
