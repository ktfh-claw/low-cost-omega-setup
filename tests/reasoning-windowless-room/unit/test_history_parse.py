"""Unit tests for history_parse.py v2 — benchmark window + retrieval extraction.

extract_add_atom_shas / extract_archive_receipts are LEGACY-format parsers
(spec §8 item 6; resolution 4): they still work on legacy history texts but
are NOT called by the v4 grade path — v4 write receipts carry ``top=<handle>``,
not ``git:`` shas, and ARCHIVE-OK retired with the archive skill (spec §2.5).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from history_parse import (
    window_from_texts,
    extract_retrieve_args,
    count_placeholder_retrieves,
    extract_add_atom_shas,
    extract_archive_receipts,
    extract_persist_receipts,
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


def test_extract_archive_receipts_parses_legacy_window():
    # LEGACY lane (archive skill retired with v4, spec §2.5): the parser
    # stays for legacy history texts — multiple receipts, strip behavior
    text = (
        '(2026-10-21 23:40:00 (shell "ARCHIVE-OK: archived=3 ref=https://example.com"))\n'
        '(2026-10-21 23:41:00 (shell "no receipt here"))\n'
        '   ARCHIVE-OK: archived=1   \n'
    )
    receipts = extract_archive_receipts(text)
    assert len(receipts) == 2
    assert receipts[0] == '(2026-10-21 23:40:00 (shell "ARCHIVE-OK: archived=3 ref=https://example.com"))'
    # surrounding whitespace stripped
    assert receipts[1] == "ARCHIVE-OK: archived=1"


def test_v4_receipt_window_yields_no_legacy_artifacts():
    # retirement contract (spec §8 item 6; resolution 4): a window with
    # ONLY v4 receipts has no git: shas and no ARCHIVE-OK lines — v4
    # write receipts carry top=<handle>, not git shas (spec §2.5); the
    # persist receipts themselves stay parseable (E-gate, spec §2.6)
    v4_window = (
        '(2026-10-28 09:00:00 (shell "BRIDGE-PERSIST-OK: verified=2 top=$n17 stv=(0.9,0.8)"))\n'
        '(2026-10-28 09:01:00 (shell "BRIDGE-PERSIST-OK: verified=1 top=$n42"))\n'
    )
    assert extract_add_atom_shas(v4_window) == []
    assert extract_archive_receipts(v4_window) == []
    assert extract_persist_receipts(v4_window) == [
        '(2026-10-28 09:00:00 (shell "BRIDGE-PERSIST-OK: verified=2 top=$n17 stv=(0.9,0.8)"))',
        '(2026-10-28 09:01:00 (shell "BRIDGE-PERSIST-OK: verified=1 top=$n42"))',
    ]


def test_normalize_query_passthrough():
    assert normalize_query("  (Inheritance $X $Y) ") == "(Inheritance $X $Y)"
