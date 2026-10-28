"""Unit tests for the HANDLES gate (issue #2 Phase 5 item 5, SDD T024).

The dedicated Phase-6 fixture home for the H-gate (spec §2.6-§2.7, §8
item 5, §9; GATES-REFERENCE §12 rows H_MISSING / H_COUNT_MISMATCH /
H_MISMATCH — ADD, blocking per D4, knowledge-case triggers): block
parsing of the HANDLES: line, the script-core cross-check semantics
(rs._handles_check — FACTS-aligned deterministic handle re-derivation),
the blocking gate mapping, the unsolvable exemption, and alignment
evidence. The CLI-seam tests (script exit code never carries H_*,
--json payload shape) live in test_reconstruct_sources.py and are NOT
duplicated here.

Stdlib-only shim (no pytest — plain asserts, test_* functions,
auto-discovered by unit/run_tests.py; this host has neither pytest nor
hyperon_das — rs._factories() yields the formula-identical fallback
Node/Link classes, so handle derivation is deterministic either way).
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = REPO_ROOT / "deploy" / "das" / "write-bridge" / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import reconstruct_sources as rs  # noqa: E402 (sys.path set above)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from facts import TEST_CASES  # noqa: E402
from grading import (  # noqa: E402
    gate_case,
    parse_answers_v2,
    INFORMATIONAL_CONDITIONS,
)

# Pinned mirror-formula handles (fallback factories; the same values
# test_reconstruct_sources.py pins against the live-verified client).
X402 = '(Inheritance (Concept "x402") (Concept "payment-protocol"))'
TOP_HANDLE = "67293e82ab2162d2d9d5a1578670f678"
OTHER = '(Inheritance (Concept "x402") (Concept "money"))'
OTHER_HANDLE = "09155ce2dea69ce956a78986008606c7"

NODE, LINK = rs._factories()


def _judge_ok(case, final_answer):
    return True, {"judge_verdict": "TRUE", "stub": True}


def _case(case_id):
    for c in TEST_CASES:
        if c["id"] == case_id:
            return c
    return None


# ---------------------------------------------------------------------------
# block parsing: parse_answers_v2 extracts handles_raw
# ---------------------------------------------------------------------------

def _handles_block(case_id="original", handles_line="HANDLES: h1 h2"):
    body = (
        f'QUERY: (Inheritance $X (Concept "ceiling"))\n'
        'DAS_RETRIEVE_OK untrusted=true count=1 truncated=false results=[]\n'
        'FACTS: (Inheritance (Concept "room") (Concept "enclosed-space"))\n'
    )
    if handles_line is not None:
        body += handles_line + "\n"
    body += (
        'REASONING: (Inheritance $X (Concept "ceiling"))\n'
        f'FINAL ANSWER ({case_id}): the ceiling\n'
    )
    return parse_answers_v2(f"### CASE {case_id}\n\n{body}")[case_id]


def test_handles_raw_present_multi_token_line():
    block = _handles_block(handles_line="HANDLES: h1 h2 h3")
    assert block.handles_raw == "h1 h2 h3"


def test_handles_raw_internal_whitespace_preserved():
    # the block parser captures the line verbatim (whitespace-stripped at
    # the edges only); token splitting is the script's job
    block = _handles_block(handles_line="HANDLES: h1  h2")
    assert block.handles_raw == "h1  h2"


def test_handles_raw_empty_line():
    block = _handles_block(handles_line="HANDLES:")
    assert block.handles_raw == ""


def test_handles_raw_whitespace_only_line():
    block = _handles_block(handles_line="HANDLES:   ")
    assert block.handles_raw == ""


def test_handles_raw_absent_when_no_line():
    block = _handles_block(handles_line=None)
    assert block.handles_raw == ""


# ---------------------------------------------------------------------------
# script core: rs._handles_check direct calls (fallback factories)
# ---------------------------------------------------------------------------

def test_handles_check_clean_aligned_roundtrip():
    hc = rs._handles_check(X402, TOP_HANDLE, NODE, LINK)
    assert hc == {"claimed": [TOP_HANDLE], "derived": [TOP_HANDLE],
                  "conditions": []}


def test_handles_check_missing_when_facts_have_no_handles():
    for handles in (None, "", "   "):
        hc = rs._handles_check(X402, handles, NODE, LINK)
        assert hc["conditions"] == ["H_MISSING"], handles
        assert hc["claimed"] == []
        assert hc["derived"] == [TOP_HANDLE]


def test_handles_check_count_mismatch_claimed_exceeds_facts():
    hc = rs._handles_check(X402, f"{TOP_HANDLE} extra", NODE, LINK)
    assert hc["conditions"] == ["H_COUNT_MISMATCH"]


def test_handles_check_count_mismatch_claimed_below_facts():
    hc = rs._handles_check(f"{X402};{OTHER}", TOP_HANDLE, NODE, LINK)
    assert hc["conditions"] == ["H_COUNT_MISMATCH"]
    assert hc["derived"] == [TOP_HANDLE, OTHER_HANDLE]


def test_handles_check_count_mismatch_and_wrong_handle_both_fire():
    # documented behavior: a count mismatch does NOT suppress the
    # positionally-aligned handle comparison — both codes fire
    hc = rs._handles_check(X402, "wrong extra", NODE, LINK)
    assert hc["conditions"] == ["H_COUNT_MISMATCH", "H_MISMATCH"]


def test_handles_check_fabricated_handle_at_aligned_position():
    fabricated = "f" * 32
    hc = rs._handles_check(X402, fabricated, NODE, LINK)
    assert hc["conditions"] == ["H_MISMATCH"]
    assert hc["claimed"] == [fabricated]
    assert hc["derived"] == [TOP_HANDLE]


def test_handles_check_unparseable_fact_derives_none():
    hc = rs._handles_check("(broken", TOP_HANDLE, NODE, LINK)
    assert hc["derived"] == [None]
    assert hc["conditions"] == ["H_MISMATCH"]


def test_handles_check_no_conditions_without_facts():
    # the structural unsolvable path: no FACTS expressions -> nothing is
    # derived and no H_* condition can fire, whatever the HANDLES line
    # carried
    for facts in (None, "", "   "):
        hc = rs._handles_check(facts, "h1 h2", NODE, LINK)
        assert hc["conditions"] == [], facts
        assert hc["claimed"] == ["h1", "h2"]
        assert hc["derived"] == []
    hc = rs._handles_check(None, None, NODE, LINK)
    assert hc == {"claimed": [], "derived": [], "conditions": []}


def test_handles_check_tokens_split_on_whitespace():
    hc = rs._handles_check(None, "h1  h2\t h3", NODE, LINK)
    assert hc["claimed"] == ["h1", "h2", "h3"]
    assert hc["conditions"] == []


def test_handles_check_semicolon_facts_empty_segments_ignored():
    hc = rs._handles_check(f";; {X402} ;; {OTHER} ;;",
                          f"{TOP_HANDLE} {OTHER_HANDLE}", NODE, LINK)
    assert hc["derived"] == [TOP_HANDLE, OTHER_HANDLE]
    assert hc["claimed"] == [TOP_HANDLE, OTHER_HANDLE]
    assert hc["conditions"] == []


# ---------------------------------------------------------------------------
# gate mapping: handles_check conditions -> blocking gate conditions (D4)
# ---------------------------------------------------------------------------

def _resolved_source(ref="https://example.com/spatial-knowledge.md"):
    return {"commit": "f" * 40, "ref": ref, "sha256": "e" * 64,
            "entry_date": "2026-10-28T00:00:00Z", "resolved": True,
            "legacy": False, "conditions": []}


def _stored_row(expr='(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                sources=None):
    return {"expr": expr, "top_handle": "t" * 32, "stored": True,
            "classification": "stored_fact",
            "sources": sources if sources is not None else [_resolved_source()],
            "conditions": []}


def _exempt_row(expr, classification):
    return {"expr": expr, "top_handle": None, "stored": False,
            "classification": classification, "sources": [],
            "conditions": []}


def _payload(rows=None, handles_conditions=None, handles_check=None):
    """A reconstruction payload (reconstruct_sources.py --json shape)."""
    if handles_check is None:
        handles_check = {"claimed": [], "derived": [],
                         "conditions": handles_conditions or []}
    return {
        "per_expression": rows if rows is not None else [_stored_row()],
        "per_predicate": {},
        "handles_check": handles_check,
        "missing": [],
        "conditions": [],
        "source_paths": [],
    }


def _unsolvable_reconstruction(handles_conditions=None):
    """Absence-probe payload idiom: exempt rows only, no stored facts."""
    return _payload(rows=[
        _exempt_row('(Inheritance (Concept "australia") $X)', "query_clause"),
        _exempt_row('(Inheritance $X (Concept "australia"))', "variable"),
    ], handles_conditions=handles_conditions)


def _block_for(case_id, query='(Inheritance $X (Concept "ceiling"))', count=1,
               handles="h1", answer="the ceiling", reasoning=None):
    if reasoning is None:
        reasoning = (f"{query}; "
                     '(Evaluation (Predicate "has-part") '
                     '(Concept "room") (Concept "ceiling")); '
                     '((Evaluation (Predicate "visible-when-looking-up") '
                     '(Concept "observer-inside-room") (Concept "ceiling")) '
                     '(stv 0.9 0.888888888888889))')
    text = (f"QUERY: {query}\n"
            f"DAS_RETRIEVE_OK untrusted=true count={count} truncated=false results=[]\n"
            + (f"HANDLES: {handles}\n" if handles is not None else "")
            + f"REASONING: {reasoning}\n"
            + f"FINAL ANSWER ({case_id}): {answer}\n")
    return parse_answers_v2(f"### CASE {case_id}\n\n{text}")[case_id]


def _gate_knowledge(handles_conditions=None, handles_check=None, rows=None):
    return gate_case(
        _case("original"),
        _block_for("original"),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 1},
        reconstruction=_payload(rows=rows, handles_conditions=handles_conditions,
                                handles_check=handles_check),
        judge_fn=_judge_ok,
    )


def _gate_unsolvable(payload):
    return gate_case(
        _case("unsolvable"),
        _block_for("unsolvable", query='(Inheritance (Concept "australia") $X)',
                   count=0, handles=None,
                   answer="cannot answer from stored knowledge"),
        history_queries=['(Inheritance (Concept "australia") $X)'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 0},
        reconstruction=payload,
        judge_fn=_judge_ok,
    )


def test_gate_h_missing_blocks():
    r = _gate_knowledge(handles_conditions=["H_MISSING"])
    assert r.verdict == "FAIL"
    assert r.conditions == ["H_MISSING"]


def test_gate_h_count_mismatch_blocks():
    r = _gate_knowledge(handles_conditions=["H_COUNT_MISMATCH"])
    assert r.verdict == "FAIL"
    assert r.conditions == ["H_COUNT_MISMATCH"]


def test_gate_h_mismatch_blocks():
    r = _gate_knowledge(handles_conditions=["H_MISMATCH"])
    assert r.verdict == "FAIL"
    assert r.conditions == ["H_MISMATCH"]


def test_h_codes_are_blocking_not_informational():
    for code in ("H_MISSING", "H_COUNT_MISMATCH", "H_MISMATCH"):
        assert code not in INFORMATIONAL_CONDITIONS, code


# ---------------------------------------------------------------------------
# unsolvable exemption (knowledge-case triggers, parallel to P_MISSING)
# ---------------------------------------------------------------------------

def test_gate_unsolvable_exempt_from_h_missing():
    r = _gate_unsolvable(_unsolvable_reconstruction(["H_MISSING"]))
    assert r.verdict == "PASS", r.conditions
    assert r.conditions == []
    # the evidence still rides into the detail verbatim — only the
    # blocking mapping is exempt
    assert r.detail["p_gate"]["handles_check"]["conditions"] == ["H_MISSING"]


def test_gate_unsolvable_exempt_from_h_mismatch():
    r = _gate_unsolvable(_unsolvable_reconstruction(["H_MISMATCH"]))
    assert r.verdict == "PASS", r.conditions
    assert not [c for c in r.conditions if c.startswith("H_")]


def test_gate_knowledge_case_not_exempt_h_missing():
    # the mirror: the SAME payload blocks the knowledge case
    payload = _unsolvable_reconstruction(["H_MISSING"])
    r = gate_case(
        _case("original"),
        _block_for("original"),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 1},
        reconstruction=payload,
        judge_fn=_judge_ok,
    )
    assert r.verdict == "FAIL"
    assert "H_MISSING" in r.conditions


# ---------------------------------------------------------------------------
# alignment semantics: payload handles_check blocks + detail verbatim
# ---------------------------------------------------------------------------

def test_alignment_mismatch_blocks_and_detail_carries_handles_check():
    hc = {"claimed": ["h1", "WRONG"], "derived": ["h1", "h2"],
          "conditions": ["H_MISMATCH"]}
    r = _gate_knowledge(handles_check=hc)
    assert r.verdict == "FAIL"
    assert r.conditions == ["H_MISMATCH"]
    assert r.detail["p_gate"]["handles_check"] == hc
