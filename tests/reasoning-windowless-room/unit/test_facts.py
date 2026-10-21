"""Unit tests for facts.py — the canonical fact set.

Run with: python3 -m pytest tests/reasoning-windowless-room/unit -q
Or via the stdlib shim: python3 unit/run_tests.py
"""
import re
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from facts import CANONICAL_FACTS, TEST_CASES, SOURCE_URLS, ALL_BACKGROUND_FILES

def test_facts_count():
    """Target ~25-35 facts."""
    assert 25 <= len(CANONICAL_FACTS) <= 35, f"expected 25-35 facts, got {len(CANONICAL_FACTS)}"

def test_all_facts_have_required_fields():
    for fact in CANONICAL_FACTS:
        assert "id" in fact
        assert "metta" in fact
        assert "source_file" in fact
        assert "stv" in fact
        assert "requires" in fact
        assert "notes" in fact

def test_source_urls_well_formed():
    for fname, url in SOURCE_URLS.items():
        assert url.startswith("https://raw.githubusercontent.com/"), fname
        assert fname in url, fname

def test_required_facts_non_empty():
    for case in TEST_CASES:
        assert len(case["required_facts"]) > 0, case["id"]

def test_required_facts_exist():
    all_ids = set(f["id"] for f in CANONICAL_FACTS)
    for case in TEST_CASES:
        for fid in case["required_facts"]:
            assert fid in all_ids, f"{fid} not in CANONICAL_FACTS"

def test_fact_metta_balanced():
    for fact in CANONICAL_FACTS:
        expr = fact["metta"]
        depth = 0
        in_string = False
        for ch in expr:
            if ch == '"':
                in_string = not in_string
            elif ch == "(" and not in_string:
                depth += 1
            elif ch == ")" and not in_string:
                depth -= 1
        assert depth == 0, f"unbalanced parens in {fact['id']}"

def test_fact_metta_max_length():
    for fact in CANONICAL_FACTS:
        assert len(fact["metta"]) <= 2048, fact["id"]

def test_source_file_in_background():
    """Every fact's source_file must be one of the background files."""
    for fact in CANONICAL_FACTS:
        assert fact["source_file"] in ALL_BACKGROUND_FILES, \
            f"{fact['id']}: source_file '{fact['source_file']}' not in background files"

def test_fact_ids_unique():
    ids = [f["id"] for f in CANONICAL_FACTS]
    assert len(ids) == len(set(ids))

def test_fact_metta_single_expression():
    """Each fact is a single parenthesized expression (starts with '(')."""
    for fact in CANONICAL_FACTS:
        assert fact["metta"].startswith("("), fact["id"]

def test_stv_valid():
    """Each fact's stv is [strength, confidence] with values in [0,1]."""
    for fact in CANONICAL_FACTS:
        stv = fact["stv"]
        assert len(stv) == 2
        assert 0.0 <= stv[0] <= 1.0
        assert 0.0 <= stv[1] <= 1.0

def test_test_case_ids():
    expected = {"original", "uncertainty", "unsolvable", "true", "false", "easy", "difficult"}
    actual = set(c["id"] for c in TEST_CASES)
    assert actual == expected

def test_no_metta_operators():
    """Facts must not contain MeTTa operators (:-, ->, etc.)."""
    for fact in CANONICAL_FACTS:
        assert ":-" not in fact["metta"], fact["id"]
        assert "->" not in fact["metta"], fact["id"]


def test_concept_name_consistency():
    """Key concepts must be spelled consistently for query joins."""
    # Collect all quoted concept names
    import re
    all_names = set()
    for fact in CANONICAL_FACTS:
        for m in re.finditer(r'\(Concept "([^"]+)"\)', fact["metta"]):
            all_names.add(m.group(1))
    # Key concepts that must exist (join points)
    expected = {"room", "ceiling", "windowless-room", "attic", "sky", "wall", "floor"}
    for name in expected:
        assert name in all_names, f"concept '{name}' not found in any fact"
    # No near-duplicates (e.g., 'ceiling' vs 'Ceiling' vs 'ceilings')
    lower = {n.lower() for n in all_names}
    assert len(lower) == len(all_names), "case-insensitive duplicates found"


def test_requires_field_valid():
    """Each fact's requires field lists valid prompt ids."""
    valid_ids = {c["id"] for c in TEST_CASES}
    for fact in CANONICAL_FACTS:
        for pid in fact["requires"]:
            assert pid in valid_ids, f"{fact['id']}: unknown prompt id '{pid}'"
