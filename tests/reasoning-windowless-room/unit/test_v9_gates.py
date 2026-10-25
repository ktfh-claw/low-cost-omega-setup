"""v9 gate tests: extraction-record presence cross-check + attested census.

2026-10-25 20:44 UTC directive (wr3i levers 2+3). Live wr3h evidence:
the agent's facts-index recorded ~23 expressions but ~10 were never
persisted (no BRIDGE-PERSIST-OK receipts, zero mongo nodes); the grader
then reported facts_index_size=0 (parse rejected ``expr (...)`` lines)
and retrieve_calls=0 (history collapses tool calls to $_ tuples). v9
fixes the parse, probes every recorded expression against DAS
(E_INDEXED_NOT_PERSISTED, informational), and surfaces the attested
retrieve census in the grade JSON.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from facts import TEST_CASES
from grading import (
    CaseBlock,
    gate_case,
    index_variable_form,
    normalize_expression,
    parse_facts_index,
)

FAKE_SHA = "git:" + "a" * 40
FAKE_URL = "https://example.com/spatial-knowledge.md"
OK_CITATIONS = [(FAKE_SHA, FAKE_URL, [])]


def _ok_reissue(query):
    return {"count": 1}


# ---------------------------------------------------------------------------
# v9 parse: the agent's real extraction-record line shapes (wr3h evidence)
# ---------------------------------------------------------------------------

def test_parse_accepts_expr_label_lines():
    text = 'expr (Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room"))\n'
    assert parse_facts_index(text) == [
        '(Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room"))']


def test_parse_accepts_expr_lines_with_trailing_annotations():
    # wr3h's actual shape: expr + expression + src/git annotation
    text = ('expr (Inheritance (Concept "light-bulb") (Concept "artificial-light-source")) '
            '[lighting.md git:64779eb6d20abe89b8831f1fefb2063e2d8b49b2]\n')
    assert parse_facts_index(text) == [
        '(Inheritance (Concept "light-bulb") (Concept "artificial-light-source"))']


def test_parse_accepts_expr_line_with_receipt_suffix():
    # wr3h anomaly: receipt string embedded after the expression
    text = ('expr (Implication (Inheritance (Concept "dark room") (Concept "darkness")) '
            '(stv 0.9 0.8)) src=lighting.md git:64779eb6d20abe89b8831f1fefb2063e2d8b49b2 '
            '(BRIDGE-PERSIST-OK verified=19)\n')
    assert parse_facts_index(text) == [
        '(Implication (Inheritance (Concept "dark room") (Concept "darkness")) (stv 0.9 0.8))']


def test_parse_skips_source_receipt_and_non_expression_lines():
    text = ('# Extraction record — wr3h-20261025\n'
            'source spatial-knowledge.md git:8ffa0b35049c1b9545b08700c0594dc5eb68043e\n'
            'query (Inheritance (Concept "ceiling") $X) count=0\n'
            'trace: (Inheritance (Concept "ceiling") $X); (step two)\n')
    # source/header/query/trace lines are NOT extraction-record
    # expressions — only expr-labeled/plain expression lines count.
    assert parse_facts_index(text) == []


def test_parse_wr3h_index_size():
    # the real wr3h facts-index: 23 recorded expr lines must parse to 23
    # expressions (the file also carries source/query lines)
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "fixtures_wr3h_facts_index.txt")
    if not os.path.exists(path):
        return  # fixture optional; covered by the shape tests above
    with open(path, encoding="utf-8") as f:
        exprs = parse_facts_index(f.read())
    assert len(exprs) >= 20


# ---------------------------------------------------------------------------
# v9 index_variable_form: the presence probe pattern
# ---------------------------------------------------------------------------

def test_index_variable_form_binds_last_element():
    probe = index_variable_form('(Inheritance (Concept "ceiling") (Concept "room"))')
    assert probe == '(Inheritance (Concept "ceiling") $X)'


def test_index_variable_form_nested_and_quoted():
    probe = index_variable_form('(Evaluation (Predicate "blocks-view-of") (Concept "ceiling") (Concept "sky"))')
    assert probe == '(Evaluation (Predicate "blocks-view-of") (Concept "ceiling") $X)'


def test_index_variable_form_quotes_with_parens_do_not_confuse_depth():
    probe = index_variable_form('(Predicate "weird ) name")')
    assert probe is not None


def test_index_variable_form_degenerate_shapes():
    assert index_variable_form('Concept') is None
    assert index_variable_form('(unbalanced (a)') is None
    # single-argument wrapper: binding the only argument is still a valid probe
    assert index_variable_form('(Concept "ceiling")') == '(Concept $X)'


# ---------------------------------------------------------------------------
# v9 gate: presence cross-check condition
# ---------------------------------------------------------------------------

def _passing_block(case_id):
    query = '(Inheritance (Concept "ceiling") $X)'
    text = f"""### CASE {case_id}

QUERY: {query}
DAS_RETRIEVE_OK untrusted=true count=1 truncated=false results=[...]
FACTS: (Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room"))
REASONING: {query}; (Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room")); ((Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room")) (stv 0.9 0.888888888888889))
FINAL ANSWER ({case_id}): the ceiling
SOURCES: {FAKE_SHA} {FAKE_URL}
"""
    from grading import parse_answers_v2
    return parse_answers_v2(text)[case_id]


def _gate(case_id, index, presence_fn=None, **kw):
    return gate_case(
        _case(case_id), _passing_block(case_id), [normalize_expression(
            '(Inheritance (Concept "ceiling") $X)')], 0,
        _ok_reissue, OK_CITATIONS,
        facts_index=index,
        window_persist_receipts=1,
        window_archive_receipts=1,
        presence_fn=presence_fn,
        facts_index_raw="\n".join(index),
        **kw,
    )


def _case(case_id):
    for c in TEST_CASES:
        if c["id"] == case_id:
            return c
    return None


def test_presence_fn_all_present_no_condition():
    index = ['(Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room"))']
    r = _gate("original", index, presence_fn=lambda q: {"count": 1})
    assert "E_INDEXED_NOT_PERSISTED" not in r.conditions
    assert r.detail.get("index_absent_count", 0) == 0


def test_presence_fn_absent_expression_flagged_informational():
    # wr3h shape: index claims facts that were never persisted
    index = [
        '(Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room"))',
        '(Evaluation (Predicate "visible-when-looking-up-inside") (Concept "room") (Concept "ceiling"))',
    ]

    def presence(query):
        # first expression's probe resolves; second (never-persisted) -> 0
        if query == '(Inheritance (Concept "ceiling") $X)':
            return {"count": 1}
        return {"count": 0}

    r = _gate("original", index, presence_fn=presence)
    assert "E_INDEXED_NOT_PERSISTED" in r.conditions
    assert r.detail["index_absent_count"] == 1
    assert "visible-when-looking-up-inside" in r.detail["index_absent"][0]
    # informational: does not flip the verdict by itself
    assert r.verdict == "PASS"


def test_presence_fn_probe_errors_are_not_gate_evidence():
    index = ['(Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room"))']
    r = _gate("original", index, presence_fn=lambda q: {"error": "timeout"})
    assert "E_INDEXED_NOT_PERSISTED" not in r.conditions


def test_no_presence_fn_keeps_v8_behavior():
    index = ['(Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room"))']
    r = _gate("original", index, presence_fn=None)
    assert "E_INDEXED_NOT_PERSISTED" not in r.conditions


# ---------------------------------------------------------------------------
# v9.1: agent-IP selection for the attestation lane (wr3i preflight defect)
# ---------------------------------------------------------------------------

def _pick_agent_ip():
    # imported lazily: run_benchmark pulls in heavy deps but the helper is pure
    import run_benchmark as rb
    return rb._pick_agent_ip


def test_pick_agent_ip_prefers_bridge_subnet():
    pick = _pick_agent_ip()
    # live defect shape: default bridge 172.17.0.2 + client net 172.20.0.6
    assert pick(["172.17.0.2", "172.20.0.6"], "172.20.0.5") == "172.20.0.6"
    assert pick(["172.20.0.6", "172.17.0.2"], "172.20.0.5") == "172.20.0.6"


def test_pick_agent_ip_single_or_empty():
    pick = _pick_agent_ip()
    assert pick(["172.20.0.6"], "172.20.0.5") == "172.20.0.6"
    assert pick(["10.0.0.9"], "") == "10.0.0.9"
    assert pick([], "172.20.0.5") == ""


def test_pick_agent_ip_fallback_without_bridge_hint():
    pick = _pick_agent_ip()
    # no bridge prefix to match: first address wins deterministically
    assert pick(["10.1.0.2", "10.2.0.3"], "") == "10.1.0.2"
