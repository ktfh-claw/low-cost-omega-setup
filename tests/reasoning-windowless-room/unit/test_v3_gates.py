"""Unit tests for the v3 gates: E-gate (extraction), attestation lane,
facts-index parsing, the v17 byte-compare lane, and sequential-mode
helpers.

Deterministic only — no LLM, no network. Attestation-lane tests exercise
grading.gate_case logic with synthetic attestation dicts and
reconstruction payloads (plain dicts — the Phase-4 script is exercised
by test_reconstruct_sources.py; here the v4 harness contract is pinned:
payload in, conditions out).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from facts import TEST_CASES
from grading import (
    CaseBlock,
    gate_case,
    normalize_expression,
    parse_answers_v2,
    parse_facts_index,
    parse_facts_line,
    parse_reasoning_trace,
    index_literals,
    query_literals,
    gate_summary,
)


# v15b: the A-gate substance check is the LLM judge; offline unit tests
# stub it deterministically (the real judge is exercised by live runs)
def _judge_ok(case, final_answer):
    return True, {"judge_verdict": "CORRECT", "stub": True}


def _judge_wrong(case, final_answer):
    return False, {"judge_verdict": "INCORRECT", "stub": True}


def _case(case_id):
    for c in TEST_CASES:
        if c["id"] == case_id:
            return c
    return None


def _ok_reissue(query):
    return {"count": 1}


# --- v17 reconstruction payloads (the script's --json shape; plain dicts) ---
BKGD_URL = ("https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/"
            "main/tests/reasoning-windowless-room/background/spatial-knowledge.md")


def _resolved_source(ref=BKGD_URL, sha256="e" * 64):
    return {"commit": "f" * 40, "ref": ref, "sha256": sha256,
            "entry_date": "2026-10-28T00:00:00Z", "resolved": True,
            "legacy": False, "conditions": []}


def _stored_row(expr='(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                sources=None, conditions=None):
    return {"expr": expr, "top_handle": "t" * 32, "stored": True,
            "classification": "stored_fact",
            "sources": sources if sources is not None else [_resolved_source()],
            "conditions": conditions or []}


def _payload(rows, handles_conditions=None):
    return {
        "per_expression": rows,
        "per_predicate": {},
        "handles_check": {"claimed": [], "derived": [],
                          "conditions": handles_conditions or []},
        "missing": [],
        "conditions": [],
        "source_paths": [],
    }


OK_RECONSTRUCTION = _payload([_stored_row()])
UNSOLVABLE_RECONSTRUCTION = _payload([
    {"expr": '(Inheritance (Concept "australia") $X)', "top_handle": None,
     "stored": False, "classification": "query_clause", "sources": [],
     "conditions": []},
    {"expr": '(Inheritance $X (Concept "australia"))', "top_handle": None,
     "stored": False, "classification": "variable", "sources": [],
     "conditions": []},
])


FACTS_INDEX = """# Extraction record

(Inheritance (Concept "room") (Concept "enclosed-space"))
(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))
(Evaluation (Predicate "visible-when-looking-up") (Concept "observer-inside-room") (Concept "ceiling"))
"""

INDEX = parse_facts_index(FACTS_INDEX)
assert len(INDEX) == 3, INDEX


def _block(case_id, query, facts, handles="h1", count=1, reasoning=None,
           answer="the ceiling"):
    if reasoning is None:
        # v6 R-gate: default trace = question clause; a stored fact step
        # (verbatim INDEX expression); the executed derivation step quoting
        # the interpreter (stv ...) output (scenario-A/A2 executed-trace
        # standard, 2026-10-25)
        reasoning = (f"{query}; "
                     '(Evaluation (Predicate "visible-when-looking-up") '
                     '(Concept "observer-inside-room") (Concept "ceiling")); '
                     '((Evaluation (Predicate "visible-when-looking-up") '
                     '(Concept "observer-inside-room") (Concept "ceiling")) '
                     '(stv 0.9 0.888888888888889))')
    text = f"""### CASE {case_id}

QUERY: {query}
DAS_RETRIEVE_OK untrusted=true count={count} truncated=false results=[...]
FACTS: {facts}
HANDLES: {handles}
REASONING: {reasoning}
FINAL ANSWER ({case_id}): {answer}
"""
    blocks = parse_answers_v2(text)
    return blocks[case_id]


# ---------------------------------------------------------------------------
# facts-index parsing
# ---------------------------------------------------------------------------

def test_parse_facts_index_plain_and_bullets():
    text = '# Extraction record\n(Inheritance (Concept "room") $X)\n- (Evaluation (Predicate "p") $Y $Z)\nnot an expression\n'
    exprs = parse_facts_index(text)
    assert exprs == ['(Inheritance (Concept "room") $X)',
                     '(Evaluation (Predicate "p") $Y $Z)']


def test_parse_facts_index_normalizes_whitespace():
    text = '(Inheritance    (Concept "room")   (Concept "enclosed-space"))\n'
    exprs = parse_facts_index(text)
    assert exprs == ['(Inheritance (Concept "room") (Concept "enclosed-space"))']


def test_index_and_query_literals():
    assert index_literals(INDEX) == {
        "room", "enclosed-space", "has-part", "ceiling",
        "visible-when-looking-up", "observer-inside-room",
    }
    assert query_literals('(Inheritance $X (Concept "ceiling"))') == ["ceiling"]


def test_parse_facts_line():
    facts = parse_facts_line(
        '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling")); (Inheritance (Concept "room") (Concept "enclosed-space"))'
    )
    assert facts == [
        '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
        '(Inheritance (Concept "room") (Concept "enclosed-space"))',
    ]
    assert parse_facts_line("") == []


# ---------------------------------------------------------------------------
# E-gate
# ---------------------------------------------------------------------------

def _gate(case_id, block, **kw):
    kw.setdefault("reconstruction", OK_RECONSTRUCTION)
    kw.setdefault("judge_fn", _judge_ok)
    return gate_case(
        _case(case_id), block,
        history_queries=[normalize_expression(block.queries[0])] if block and block.queries else [],
        history_placeholder_calls=0,
        reissue_fn=_ok_reissue,
        **kw,
    )


def test_e_gate_empty_index_fails_every_case():
    r = _gate("original", _block("original", '(Inheritance $X (Concept "ceiling"))',
                                 '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
              facts_index=[])
    assert r.verdict == "FAIL"
    assert "E_NO_EXTRACTION" in r.conditions


def test_e_gate_none_index_skips_e_gate():
    r = _gate("original", _block("original", '(Inheritance $X (Concept "ceiling"))',
                                 '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
              facts_index=None)
    assert r.verdict == "PASS"
    assert not any(c.startswith("E_") for c in r.conditions)


def test_e_gate_good_extraction_passes():
    r = _gate("original", _block("original", '(Inheritance $X (Concept "ceiling"))',
                                 '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "PASS", r.conditions


def test_e_gate_missing_facts_line_fails():
    block = _block("original", '(Inheritance $X (Concept "ceiling"))', "")
    r = _gate("original", block, facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "FAIL"
    assert "E_NO_FACTS" in r.conditions


def test_e_gate_facts_not_in_index_fails():
    r = _gate("original", _block("original", '(Inheritance $X (Concept "ceiling"))',
                             '(Inheritance (Concept "made-up") $X)'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "FAIL"
    assert "E_FACTS_NOT_IN_INDEX" in r.conditions


def test_e_gate_foreign_query_literal_fails():
    # query reformulates the extracted vocabulary -> mechanical-trap rule
    r = _gate("original", _block("original", '(Inheritance $X (Concept "roome"))',
                             '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "FAIL"
    assert "E_LITERAL_NOT_EXTRACTED" in r.conditions
    assert r.detail.get("foreign_literals") == ["roome"]


def test_e_gate_reused_literal_passes():
    r = _gate("original", _block("original", '(Inheritance $X (Concept "ceiling"))',
                             '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "PASS", r.conditions


def test_e_gate_no_ingest_first_case_fails_without_receipts():
    r = _gate("original", _block("original", '(Inheritance $X (Concept "ceiling"))',
                                 '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
              facts_index=INDEX,
              window_persist_receipts=0)
    assert r.verdict == "FAIL"
    assert "E_NO_INGEST" in r.conditions


def test_e_gate_later_case_ingest_not_required():
    # "false" is not the first case: no fresh ingest required
    r = _gate("false", _block("false", '(Inheritance $X (Concept "ceiling"))',
                              '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                              answer="false — you see the ceiling, not the sky"),
              facts_index=INDEX,
              window_persist_receipts=0)
    assert r.verdict == "PASS", r.conditions


def test_e_gate_unsolvable_exempt_from_facts_line():
    text = """### CASE unsolvable

QUERY: (Inheritance (Concept "australia") $X)
DAS_RETRIEVE_OK untrusted=true count=0 truncated=false results=[]
REASONING: (Inheritance (Concept "australia") $X); (Inheritance $X (Concept "australia"))
FINAL ANSWER (unsolvable): cannot answer from stored knowledge
SOURCES: none (absence case)
"""
    blocks = parse_answers_v2(text)
    r = gate_case(
        _case("unsolvable"), blocks["unsolvable"],
        history_queries=['(Inheritance (Concept "australia") $X)'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 0},
        reconstruction=UNSOLVABLE_RECONSTRUCTION,
        facts_index=INDEX,
        window_persist_receipts=1,
        judge_fn=_judge_ok,
    )
    assert r.verdict == "PASS", r.conditions


# ---------------------------------------------------------------------------
# R-gate (reasoning trace — campaign-grade standard, 2026-10-24 directive)
# ---------------------------------------------------------------------------

def test_parse_reasoning_trace_steps_and_prose():
    steps, prose = parse_reasoning_trace(
        '(Inheritance $X (Concept "ceiling")); (Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))')
    assert prose is False
    assert steps == ['(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))']
    steps, prose = parse_reasoning_trace('scene construction: windowless room; looking up intersects the ceiling.')
    assert prose is True and steps == []
    steps, prose = parse_reasoning_trace('')
    assert prose is False and steps == []


def test_r_gate_prose_reasoning_fails():
    # generated text instead of the MeTTa trace — the exact failure the
    # 2026-10-24 directive prohibits ("it should not be some generated text")
    r = _gate("original",
              _block("original", '(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                     reasoning="scene construction: windowless room; looking up intersects the ceiling."),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "FAIL"
    assert "R_NOT_METTA" in r.conditions


def test_r_gate_missing_reasoning_line_fails():
    block = _block("original", '(Inheritance $X (Concept "ceiling"))',
                   '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))')
    block.reasoning_raw = ""
    r = _gate("original", block, facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "FAIL"
    assert "R_MISSING" in r.conditions


def test_r_gate_single_step_fails():
    # a trace needs at least the question clause + one derivation step
    r = _gate("original",
              _block("original", '(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                     reasoning='(Inheritance $X (Concept "ceiling"))'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert "R_NOT_METTA" in r.conditions


def test_r_gate_first_step_must_be_the_query():
    r = _gate("original",
              _block("original", '(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                     reasoning='(Evaluation (Predicate "visible-when-looking-up") (Concept "observer-inside-room") (Concept "ceiling")); (Inheritance $X (Concept "ceiling"))'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "FAIL"
    assert "R_TRACE_NOT_GROUNDED" in r.conditions


def test_r_gate_ungrounded_middle_step_fails():
    # a step that is neither the query nor an extraction-record atom nor a
    # derived conclusion over stored vocabulary = fabricated reasoning
    r = _gate("original",
              _block("original", '(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                     reasoning='(Inheritance $X (Concept "ceiling")); (Evaluation (Predicate "made-up-relation") (Concept "room") (Concept "ceiling")); (Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "FAIL"
    assert "R_TRACE_NOT_GROUNDED" in r.conditions
    assert r.detail.get("trace_not_grounded") == ['(Evaluation (Predicate "made-up-relation") (Concept "room") (Concept "ceiling"))']


def test_r_gate_derived_conclusion_over_stored_vocab_passes():
    # the campaign 06-appendix form: final step is a DERIVED clause (e.g. an
    # Implication) whose literals all come from the stored vocabulary.
    # v6 executed-trace standard: exec evidence comes from the extraction
    # record's `exec` lines (the harness-side lane — scenario A: real
    # derivations existed but were never carried into the artifact).
    derived = '(Implication (Inheritance $X (Concept "enclosed-space")) (Evaluation (Predicate "visible-when-looking-up") $X (Concept "ceiling")))'
    facts_index_raw = FACTS_INDEX + "\n" + (
        'exec (|~ ((Implication (Inheritance $X (Concept "enclosed-space")) '
        '(Evaluation (Predicate "visible-when-looking-up") $X (Concept "ceiling"))) (stv 1.0 0.9)) '
        '((Inheritance (Concept "windowless-room") (Concept "enclosed-space")) (stv 0.81 0.5184))) '
        '=> ((Evaluation (Predicate "visible-when-looking-up") (Concept "windowless-room") (Concept "ceiling")) (stv 0.81 0.4665))\n')
    r = _gate("original",
              _block("original", '(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                     reasoning=f'(Inheritance $X (Concept "ceiling")); (Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling")); {derived}'),
              facts_index=INDEX,
              facts_index_raw=facts_index_raw,
              window_persist_receipts=1)
    assert r.verdict == "PASS", r.conditions


def test_r_gate_derived_conclusion_with_foreign_literal_fails():
    derived = '(Evaluation (Predicate "visibility") (Concept "gazer") (Concept "ceiling"))'
    r = _gate("original",
              _block("original", '(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                     reasoning=f'(Inheritance $X (Concept "ceiling")); (Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling")); {derived}'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert "R_TRACE_NOT_GROUNDED" in r.conditions


def test_r_gate_good_trace_passes():
    # question clause + verbatim stored fact step — the default fixture shape
    r = _gate("original",
              _block("original", '(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "PASS", r.conditions
    assert not any(c.startswith("R_") for c in r.conditions)


def test_r_gate_unsolvable_shape_only():
    # unsolvable: trace shape still required (question + probe clause), but
    # exempt from index grounding (no facts to ground against)
    text = """### CASE unsolvable

QUERY: (Inheritance (Concept "australia") $X)
DAS_RETRIEVE_OK untrusted=true count=0 truncated=false results=[]
REASONING: (Inheritance (Concept "australia") $X); (Inheritance $X (Concept "australia"))
FINAL ANSWER (unsolvable): cannot answer from stored knowledge
SOURCES: none (absence case)
"""
    blocks = parse_answers_v2(text)
    r = gate_case(
        _case("unsolvable"), blocks["unsolvable"],
        history_queries=['(Inheritance (Concept "australia") $X)'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 0},
        reconstruction=UNSOLVABLE_RECONSTRUCTION,
        facts_index=INDEX,
        window_persist_receipts=1,
        judge_fn=_judge_ok,
    )
    assert r.verdict == "PASS", r.conditions
    assert "R_NOT_EXECUTED" not in r.conditions  # absence probes: nothing to execute


# R_NOT_EXECUTED (scenario A/A2 executed-trace standard, 2026-10-25)
# ---------------------------------------------------------------------------

def test_r_not_executed_fires_without_exec_evidence():
    # knowledge case, well-formed trace, but NO interpreter (stv ...) output
    # and no exec lines in the extraction record -> hand-composed reasoning
    r = _gate("original",
              _block("original", '(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                     reasoning='(Inheritance $X (Concept "ceiling")); '
                               '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert "R_NOT_EXECUTED" in r.conditions
    assert r.verdict == "FAIL"


def test_r_not_executed_satisfied_by_trace_stv():
    # the trace itself quotes the interpreter (stv ...) output -> executed
    # (the default fixture reasoning now carries the stv derivation step)
    r = _gate("original",
              _block("original", '(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
              facts_index=INDEX,
              window_persist_receipts=1)
    assert r.verdict == "PASS", r.conditions
    assert "R_NOT_EXECUTED" not in r.conditions


def test_r_not_executed_satisfied_by_exec_record_lines():
    # exec <call> => <output-with-stv> lines in the extraction record are
    # harness-side evidence of executed reasoning even when the trace itself
    # quotes no stv (scenario A: 39 real derivations existed but were never
    # carried into the artifact — the record is the durable evidence lane)
    facts_index_exec = FACTS_INDEX + "\n" + (
        'exec (|- ((Inheritance (Concept "windowless-room") (Concept "room")) (stv 0.9 0.8)) '
        '((Inheritance (Concept "room") (Concept "enclosed-space")) (stv 0.9 0.8))) '
        '=> ((Inheritance (Concept "windowless-room") (Concept "enclosed-space")) (stv 0.81 0.5184))\n')
    idx = parse_facts_index(facts_index_exec)
    assert len(idx) == 3  # the exec line is not an extraction expression
    r = _gate("original",
              _block("original", '(Inheritance $X (Concept "ceiling"))',
                     '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))',
                     reasoning='(Inheritance $X (Concept "ceiling")); '
                               '(Evaluation (Predicate "visible-when-looking-up") '
                               '(Concept "observer-inside-room") (Concept "ceiling"))'),
              facts_index=idx,
              facts_index_raw=facts_index_exec,
              window_persist_receipts=1)
    assert "R_NOT_EXECUTED" not in r.conditions
    assert r.verdict == "PASS", r.conditions


# ---------------------------------------------------------------------------
# attestation lane (Q_ATTESTED_VIA_ACCESS_LOG is informational)
# ---------------------------------------------------------------------------

def test_attested_query_passes_with_informational_condition():
    # query NOT in the (lossy) history, but attested by both log lanes
    r = gate_case(
        _case("original"),
        _block("original", '(Inheritance $X (Concept "ceiling"))',
               '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
        history_queries=[],  # history collapsed the tuple
        history_placeholder_calls=0,
        reissue_fn=_ok_reissue,
        reconstruction=OK_RECONSTRUCTION,
        facts_index=INDEX,
        window_persist_receipts=1,
        attestation={"qe_pattern_match": True, "access_count": 2,
                     "write_count": 1, "archive_count": 1},
        judge_fn=_judge_ok,
    )
    assert r.verdict == "PASS", r.conditions
    assert "Q_ATTESTED_VIA_ACCESS_LOG" in r.conditions


def test_unattested_missing_history_still_fails():
    r = gate_case(
        _case("original"),
        _block("original", '(Inheritance $X (Concept "ceiling"))',
               '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
        history_queries=[],
        history_placeholder_calls=0,
        reissue_fn=_ok_reissue,
        reconstruction=OK_RECONSTRUCTION,
        facts_index=INDEX,
        window_persist_receipts=1,
        attestation={"qe_pattern_match": False, "access_count": 0},
    )
    assert r.verdict == "FAIL"
    assert "Q_NOT_IN_HISTORY" in r.conditions
    assert "Q_ATTESTED_VIA_ACCESS_LOG" not in r.conditions


def test_attestation_requires_both_lanes():
    # access log shows posts but QE never logged the exact pattern -> not attested
    r = gate_case(
        _case("original"),
        _block("original", '(Inheritance $X (Concept "ceiling"))',
               '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
        history_queries=[],
        history_placeholder_calls=0,
        reissue_fn=_ok_reissue,
        reconstruction=OK_RECONSTRUCTION,
        facts_index=INDEX,
        window_persist_receipts=1,
        attestation={"qe_pattern_match": False, "access_count": 5},
    )
    assert "Q_NOT_IN_HISTORY" in r.conditions
    assert r.verdict == "FAIL"


def test_e_ingest_facade_log_census_no_longer_substitutes():
    # v17 (resolution 6): E_NO_INGEST is receipts-only — the retired
    # facade-log census (write_count/archive_count) no longer substitutes
    # for a missing BRIDGE-PERSIST-OK receipt on the first case.
    r = gate_case(
        _case("original"),
        _block("original", '(Inheritance $X (Concept "ceiling"))',
               '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=_ok_reissue,
        reconstruction=OK_RECONSTRUCTION,
        facts_index=INDEX,
        window_persist_receipts=0,  # history collapsed: no receipts
        attestation={"qe_pattern_match": True, "access_count": 1,
                     "write_count": 2, "archive_count": 1},
        judge_fn=_judge_ok,
    )
    assert "E_NO_INGEST" in r.conditions
    assert "E_INGEST_ATTESTED_VIA_FACADE_LOG" not in r.conditions
    assert r.verdict == "FAIL"


def test_e_ingest_unattested_still_fails():
    r = gate_case(
        _case("original"),
        _block("original", '(Inheritance $X (Concept "ceiling"))',
               '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=_ok_reissue,
        reconstruction=OK_RECONSTRUCTION,
        facts_index=INDEX,
        window_persist_receipts=0,
        attestation={"qe_pattern_match": True, "access_count": 1,
                     "write_count": 0, "archive_count": 0},
    )
    assert "E_NO_INGEST" in r.conditions
    assert r.verdict == "FAIL"


# ---------------------------------------------------------------------------
# v17 byte-compare lane (run_benchmark._byte_compare_rows): for each unique
# (commit, ref, sha256) among the payload's stored-atom source entries,
# sha256(background file) == entry sha256
# ---------------------------------------------------------------------------

def test_byte_compare_lane_matches_background_bytes():
    import hashlib
    import tempfile
    from pathlib import Path

    import run_benchmark

    content = "# spatial knowledge\n\nthe ceiling is above.\n"
    sha = hashlib.sha256(content.encode()).hexdigest()
    payload = _payload([_stored_row(sources=[
        _resolved_source(ref="https://x/spatial-knowledge.md", sha256=sha)])])
    with tempfile.TemporaryDirectory() as bg:
        bg_dir = Path(bg)
        (bg_dir / "spatial-knowledge.md").write_text(content, encoding="utf-8")
        rows = run_benchmark._byte_compare_rows(payload, background_dir=bg_dir)
        assert len(rows) == 1
        assert rows[0]["byte_match"] is True
        assert rows[0]["ref"] == "https://x/spatial-knowledge.md"
        assert rows[0]["sha256"] == sha
        # drift between the ledger hash and the actual bytes is visible
        drifted = _payload([_stored_row(sources=[
            _resolved_source(ref="https://x/spatial-knowledge.md",
                             sha256="0" * 64)])])
        assert run_benchmark._byte_compare_rows(
            drifted, background_dir=bg_dir)[0]["byte_match"] is False


def test_byte_compare_lane_missing_background_file_records_null():
    import tempfile
    from pathlib import Path

    import run_benchmark

    # a ref that maps to no background file is recorded with
    # byte_match=None (informational, never a condition by itself)
    payload = _payload([_stored_row(sources=[
        _resolved_source(ref="https://x/no-such-background-file.md")])])
    with tempfile.TemporaryDirectory() as bg:
        rows = run_benchmark._byte_compare_rows(payload, background_dir=Path(bg))
        assert len(rows) == 1
        assert rows[0]["byte_match"] is None
        assert rows[0]["resolved"] is True


# ---------------------------------------------------------------------------
# sequential-case helpers (facts.py questions)
# ---------------------------------------------------------------------------

def test_every_case_has_standalone_question():
    for c in TEST_CASES:
        q = c.get("question", "")
        assert isinstance(q, str) and len(q.strip()) > 20, c["id"]


def test_case_questions_no_answer_leak_words():
    # the standalone question itself must not name the expected answer
    banned = {"ceiling", "sky"}
    for c in TEST_CASES:
        if c["id"] == "unsolvable":
            continue
        q = c["question"].lower()
        # note: true/false cases legitimately quote a statement that mentions
        # ceiling/sky — the statement IS the question there. The difficult
        # case names the sloped ceiling as SCENE DESCRIPTION ("windowless
        # attic with a sloped ceiling") — the answer still requires deriving
        # that the gaze intersects it (plus the lamp/why chain), so it is not
        # a guidance leak. Only the free-form cases are checked.
        if c["id"] in ("original", "uncertainty", "easy"):
            for b in banned:
                assert b not in q, (c["id"], b)
