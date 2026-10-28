"""Unit tests for grading.py v2 — the strict GATE (A/Q/P), deterministic, no LLM.

Covers: answers.md parsing (### CASE blocks), degenerate-query detection,
per-case answer grading, and the full gate_case logic with synthetic
history/reissue inputs and reconstruction payloads (v17: the P/H-gate
maps the reconstruct_sources.py JSON to conditions), plus the
wr-20261021-2355 regression (the real run-2 answers must FAIL the gate —
it had no real queries).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from facts import TEST_CASES
from grading import (
    parse_answers_v2,
    query_is_degenerate,
    grade_answer,
    gate_case,
    gate_summary,
    CaseBlock,
)

# v15b: the A-gate substance check is the LLM judge; offline unit tests
# stub it deterministically (the real judge is exercised by live runs)
def _judge_ok(case, final_answer):
    return True, {"judge_verdict": "TRUE", "stub": True}


def _judge_wrong(case, final_answer):
    return False, {"judge_verdict": "FALSE", "stub": True}


def _case(case_id):
    for c in TEST_CASES:
        if c["id"] == case_id:
            return c
    return None


# ---------------------------------------------------------------------------
# answers.md v2 parsing
# ---------------------------------------------------------------------------

GOOD_ANSWERS = """# Benchmark answers

### CASE original

QUERY: (Inheritance $X (Concept "ceiling"))
DAS_RETRIEVE_OK untrusted=true count=1 truncated=false results=[...]
HANDLES: h1 h2
REASONING: (Inheritance $X (Concept "ceiling")); (Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))
FINAL ANSWER (original): the ceiling

### CASE unsolvable

QUERY: (Inheritance (Concept "australia") $X)
DAS_RETRIEVE_OK untrusted=true count=0 truncated=false results=[]
REASONING: (Inheritance (Concept "australia") $X); (Inheritance $X (Concept "australia"))
FINAL ANSWER (unsolvable): cannot answer from stored knowledge
"""


def test_parse_answers_v2_blocks():
    blocks = parse_answers_v2(GOOD_ANSWERS)
    assert set(blocks.keys()) == {"original", "unsolvable"}
    assert blocks["original"].final_answer == "the ceiling"
    assert blocks["original"].queries == ['(Inheritance $X (Concept "ceiling"))']
    assert blocks["original"].receipt_counts == [1]
    assert blocks["original"].handles_raw == "h1 h2"
    assert blocks["unsolvable"].handles_raw == ""


def test_parse_answers_v2_handles_line():
    """v17: the HANDLES: line is captured verbatim (whitespace-stripped),
    mirroring the FACTS capture exactly."""
    text = ('### CASE original\n\n'
            'FACTS: (Inheritance (Concept "room") (Concept "enclosed-space"))\n'
            'HANDLES: h1 h2\n'
            'REASONING: (Inheritance $X (Concept "ceiling"))\n'
            'FINAL ANSWER (original): the ceiling\n')
    blocks = parse_answers_v2(text)
    assert blocks["original"].handles_raw == "h1 h2"


def test_parse_answers_v2_receipt_count():
    blocks = parse_answers_v2(GOOD_ANSWERS)
    assert blocks["unsolvable"].receipt_counts == [0]


def test_parse_answers_v2_bare_final_answer_compatibility():
    """FINAL ANSWER lines outside ### CASE blocks still parse (v1 shape)."""
    text = "FINAL ANSWER (original): the ceiling"
    blocks = parse_answers_v2(text)
    assert blocks["original"].final_answer == "the ceiling"


def test_parse_answers_v2_query_quoted_form():
    text = '### CASE original\n\nQUERY: "(Inheritance $X (Concept \\"ceiling\\"))"\nFINAL ANSWER (original): the ceiling\n'
    blocks = parse_answers_v2(text)
    assert blocks["original"].queries == ['(Inheritance $X (Concept "ceiling"))']


# ---------------------------------------------------------------------------
# degenerate query detection
# ---------------------------------------------------------------------------

def test_query_placeholder_degenerate():
    assert query_is_degenerate("$_131542") == "Q_PLACEHOLDER"
    assert query_is_degenerate("(Inheritance $X $_9") == "Q_PLACEHOLDER"


def test_query_no_variable_degenerate():
    assert query_is_degenerate('(Inheritance (Concept "ceiling") (Concept "x"))') == "Q_DEGENERATE_PATTERN"


def test_query_bare_variables_degenerate():
    assert query_is_degenerate("($X $Y $Z)") == "Q_DEGENERATE_PATTERN"


def test_query_good_not_degenerate():
    assert query_is_degenerate('(Inheritance $X (Concept "ceiling"))') is None


# ---------------------------------------------------------------------------
# answer grading (v15b: presence + LLM judge, stubbed offline)
# ---------------------------------------------------------------------------

def test_grade_answer_missing():
    case = _case("original")
    conds, detail = grade_answer(case, "", _judge_ok)
    assert conds == ["A_MISSING"]
    assert detail == {}


def test_grade_answer_judge_ok_passes():
    case = _case("original")
    conds, detail = grade_answer(case, "the ceiling", _judge_ok)
    assert conds == []
    assert detail["judge"]["judge_verdict"] == "TRUE"


def test_grade_answer_judge_wrong_fails():
    case = _case("original")
    conds, detail = grade_answer(case, "a lamp", _judge_wrong)
    assert conds == ["A_WRONG"]
    assert detail["judge"]["judge_verdict"] == "FALSE"


def test_grade_answer_no_judge_never_passes():
    case = _case("original")
    conds, detail = grade_answer(case, "the ceiling", None)
    assert conds == ["A_JUDGE_UNAVAILABLE"]


def test_grade_answer_judge_exception_fails_case():
    def _boom(case, final_answer):
        raise RuntimeError("api down")
    conds, detail = grade_answer(_case("original"), "the ceiling", _boom)
    assert conds == ["A_JUDGE_UNAVAILABLE"]
    assert "api down" in detail["judge_error"]


# ---------------------------------------------------------------------------
# gate_case
# ---------------------------------------------------------------------------

def _pass_reissue(query):
    return {"count": 1}


# --- v17 reconstruction payloads (the script's --json shape; plain dicts) ---

BKGD_URL = ("https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/"
            "main/tests/reasoning-windowless-room/background/spatial-knowledge.md")
HAS_PART_EXPR = '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))'
INHERITANCE_EXPR = '(Inheritance (Concept "ceiling") (Concept "opaque-surface"))'


def _resolved_source(ref=BKGD_URL, sha256="e" * 64):
    """A fully ledger-resolved source entry."""
    return {"commit": "f" * 40, "ref": ref, "sha256": sha256,
            "entry_date": "2026-10-28T00:00:00Z", "resolved": True,
            "legacy": False, "conditions": []}


def _no_attrs_source():
    """A stored link's source entry when it carries no provenance attrs."""
    return {"commit": None, "ref": None, "sha256": None, "entry_date": None,
            "resolved": False, "legacy": False,
            "conditions": ["NO_PROVENANCE_ATTRS"]}


def _stored_row(expr=HAS_PART_EXPR, sources=None, conditions=None):
    """A stored_fact per_expression row."""
    return {"expr": expr, "top_handle": "t" * 32, "stored": True,
            "classification": "stored_fact",
            "sources": sources if sources is not None else [_resolved_source()],
            "conditions": conditions if conditions is not None else
            [c for s in (sources or []) for c in s["conditions"]]}


def _query_row(expr):
    """An exempt (non-stored) per_expression row (query clause / variable)."""
    return {"expr": expr, "top_handle": None, "stored": False,
            "classification": "query_clause", "sources": [], "conditions": []}


def _payload(rows=None, handles_conditions=None, blocking=None):
    """A reconstruction payload (reconstruct_sources.py --json shape)."""
    return {
        "per_expression": rows if rows is not None else [_stored_row()],
        "per_predicate": {},
        "handles_check": {"claimed": [], "derived": [],
                          "conditions": handles_conditions or []},
        "missing": [],
        "conditions": blocking or [],
        "source_paths": [],
    }


def _ok_reconstruction():
    """A clean payload: one stored fact, fully resolved source, no H_*."""
    return _payload()


def _unsolvable_reconstruction():
    """An absence-probe payload: exempt rows only, no stored facts."""
    return _payload(rows=[
        _query_row('(Inheritance (Concept "australia") $X)'),
        {"expr": '(Inheritance $X (Concept "australia"))', "top_handle": None,
         "stored": False, "classification": "variable", "sources": [],
         "conditions": []},
    ])


def _block_for(case_id, query='(Inheritance $X (Concept "ceiling"))', count=1,
               handles="h1", answer="the ceiling", order="query_first", reasoning=None):
    q_line = f"QUERY: {query}"
    r_line = f"DAS_RETRIEVE_OK untrusted=true count={count} truncated=false results=[]"
    a_line = f"FINAL ANSWER ({case_id}): {answer}"
    h_line = f"HANDLES: {handles}\n" if handles is not None else ""
    # v6 R-gate: the REASONING line carries the executed MeTTa trace, not
    # prose; the final step quotes the interpreter (stv ...) output
    # (scenario-A/A2 executed-trace standard, 2026-10-25)
    if reasoning is None:
        reasoning = (f"{query}; "
                     '(Evaluation (Predicate "has-part") '
                     '(Concept "room") (Concept "ceiling")); '
                     '((Evaluation (Predicate "visible-when-looking-up") '
                     '(Concept "observer-inside-room") (Concept "ceiling")) '
                     '(stv 0.9 0.888888888888889))')
    reason_line = f"REASONING: {reasoning}"
    if order == "query_first":
        text = f"{q_line}\n{r_line}\n{h_line}{reason_line}\n{a_line}\n"
    else:
        text = f"{a_line}\n{q_line}\n{r_line}\n{h_line}{reason_line}\n"
    return parse_answers_v2(f"### CASE {case_id}\n\n{text}")[case_id]


def test_gate_case_full_pass():
    case = _case("original")
    block = _block_for("original")
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  reconstruction=_ok_reconstruction(), judge_fn=_judge_ok)
    assert r.verdict == "PASS", r.conditions
    assert r.conditions == []


def test_gate_case_query_not_in_history_fails():
    case = _case("original")
    block = _block_for("original")
    r = gate_case(case, block,
                  history_queries=[],  # nothing real in the window
                  history_placeholder_calls=3,  # only $_ placeholder calls
                  reissue_fn=lambda q: {"count": 1},
                  reconstruction=_ok_reconstruction(), judge_fn=_judge_ok)
    assert r.verdict == "FAIL"
    assert "Q_NOT_IN_HISTORY" in r.conditions
    assert "Q_PLACEHOLDER" in r.conditions


def test_gate_case_placeholder_query_fails():
    case = _case("original")
    block = _block_for("original", query="$_131542")
    r = gate_case(case, block,
                  history_queries=["$_131542"],
                  history_placeholder_calls=1,
                  reissue_fn=lambda q: {"count": 1},
                  reconstruction=_ok_reconstruction(), judge_fn=_judge_ok)
    assert r.verdict == "FAIL"
    assert "Q_PLACEHOLDER" in r.conditions


def test_gate_case_degenerate_query_fails():
    case = _case("original")
    block = _block_for("original", query="(Inheritance $X $Y)")
    r = gate_case(case, block,
                  history_queries=["(Inheritance $X $Y)"],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  reconstruction=_ok_reconstruction(), judge_fn=_judge_ok)
    assert r.verdict == "FAIL"
    assert "Q_DEGENERATE_PATTERN" in r.conditions


def test_gate_case_reissue_mismatch_fails():
    case = _case("original")
    block = _block_for("original", count=5)
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},  # quoted 5, reissue 1
                  reconstruction=_ok_reconstruction(), judge_fn=_judge_ok)
    assert r.verdict == "FAIL"
    assert "Q_REISSUE_MISMATCH" in r.conditions


def test_gate_case_no_receipt_fails():
    case = _case("original")
    block = _block_for("original")
    block.receipt_counts = []
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  reconstruction=_ok_reconstruction(), judge_fn=_judge_ok)
    assert r.verdict == "FAIL"
    assert "Q_NO_RECEIPT" in r.conditions


def test_gate_case_answer_after_query_order_fails():
    case = _case("original")
    block = _block_for("original", order="answer_first")
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  reconstruction=_ok_reconstruction(), judge_fn=_judge_ok)
    assert r.verdict == "FAIL"
    assert "Q_NOT_QUERY_FIRST" in r.conditions


def test_gate_case_missing_sources_fails():
    # v17 P_MISSING: reconstruction finds no used stored facts carrying
    # any provenance attributes — nothing citable on a knowledge case
    case = _case("original")
    block = _block_for("original")
    payload = _payload(rows=[_stored_row(
        sources=[_no_attrs_source()],
        conditions=["NO_PROVENANCE_ATTRS"])])
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  reconstruction=payload, judge_fn=_judge_ok)
    assert r.verdict == "FAIL"
    assert "P_MISSING" in r.conditions


def test_gate_case_unresolved_source_fails():
    # v17: a stored fact's failed resolution condition maps to
    # P_UNRESOLVED:<expr12>:<COND> (expr12 = the expr's raw first 12 chars)
    case = _case("original")
    block = _block_for("original")
    payload = _payload(rows=[_stored_row(
        expr=INHERITANCE_EXPR,
        sources=[_resolved_source()],
        conditions=["COMMIT_NOT_IN_REPO"])],
        blocking=["COMMIT_NOT_IN_REPO"])
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  reconstruction=payload, judge_fn=_judge_ok)
    assert r.verdict == "FAIL"
    assert "P_UNRESOLVED:(Inheritance:COMMIT_NOT_IN_REPO" in r.conditions


def test_gate_case_unsolvable_requires_proven_absence():
    case = _case("unsolvable")
    block = _block_for(
        "unsolvable",
        query='(Inheritance (Concept "australia") $X)',
        count=0,
        handles=None,
        answer="cannot answer from stored knowledge",
    )
    r = gate_case(case, block,
                  history_queries=['(Inheritance (Concept "australia") $X)'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 0},
                  reconstruction=_unsolvable_reconstruction(), judge_fn=_judge_ok)
    assert r.verdict == "PASS", r.conditions


def test_gate_case_unsolvable_fabricated_answer_fails():
    """v15b: a hallucinated capital is caught by the LLM judge (the
    v2-v14 A_FABRICATED keyword lexicon is gone). The stub encodes the
    judge's verdict: 'Canberra' is INCORRECT for the unsolvable case."""
    case = _case("unsolvable")
    block = _block_for(
        "unsolvable",
        query='(Inheritance (Concept "australia") $X)',
        count=0,
        handles=None,
        answer="Canberra",
    )
    r = gate_case(case, block,
                  history_queries=['(Inheritance (Concept "australia") $X)'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 0},
                  reconstruction=_unsolvable_reconstruction(), judge_fn=_judge_wrong)
    assert r.verdict == "FAIL"
    assert "A_WRONG" in r.conditions


def test_gate_case_unsolvable_count_positive_fails():
    """Unsolvable case with count>0 hasn't PROVEN absence."""
    case = _case("unsolvable")
    block = _block_for(
        "unsolvable",
        query='(Inheritance (Concept "australia") $X)',
        count=1,
        handles=None,
        answer="cannot answer from stored knowledge",
    )
    r = gate_case(case, block,
                  history_queries=['(Inheritance (Concept "australia") $X)'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  reconstruction=_unsolvable_reconstruction(), judge_fn=_judge_ok)
    assert r.verdict == "FAIL"
    assert "Q_ABSENCE_UNPROVEN" in r.conditions


def test_gate_case_missing_block_quad_fail():
    case = _case("original")
    r = gate_case(case, None, [], 0, None)
    assert r.verdict == "FAIL"
    assert set(r.conditions) == {"A_MISSING", "Q_MISSING", "P_MISSING", "R_MISSING"}


def test_gate_summary_aggregates():
    ok = gate_case(_case("original"),
                   _block_for("original"),
                   ['(Inheritance $X (Concept "ceiling"))'],
                   0, lambda q: {"count": 1},
                   reconstruction=_ok_reconstruction(),
                   judge_fn=_judge_ok)
    bad = gate_case(_case("original"), None, [], 0, None)
    summary = gate_summary([ok, bad])
    assert summary["gate_verdict"] == "FAIL"
    assert summary["cases_passed"] == 1
    assert summary["cases_total"] == 2


# ---------------------------------------------------------------------------
# E_NO_INGEST (v17 receipts-only, resolution 6): the first case must show
# a real ingest — a BRIDGE-PERSIST-OK receipt in its window; the retired
# facade-log census never substitutes for it
# ---------------------------------------------------------------------------

_E_INDEX = ['(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))']


def test_e_no_ingest_first_case_zero_persist_receipts():
    # (a) first case, no in-window BRIDGE-PERSIST-OK receipt, no
    # attestation -> blocking E_NO_INGEST
    r = gate_case(
        _case("original"), _block_for("original"),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 1},
        reconstruction=_ok_reconstruction(),
        facts_index=_E_INDEX,
        window_persist_receipts=0,
        attestation=None,
        judge_fn=_judge_ok,
    )
    assert "E_NO_INGEST" in r.conditions


def test_e_no_ingest_census_attestation_no_longer_substitutes():
    # (b) the retired write/archive facade-log census no longer attests
    # the ingest — E_NO_INGEST is receipts-only
    r = gate_case(
        _case("original"), _block_for("original"),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 1},
        reconstruction=_ok_reconstruction(),
        facts_index=_E_INDEX,
        window_persist_receipts=0,
        attestation={"qe_pattern_match": True, "access_count": 1,
                     "write_count": 2, "archive_count": 2},
        judge_fn=_judge_ok,
    )
    assert "E_NO_INGEST" in r.conditions
    assert "E_INGEST_ATTESTED_VIA_FACADE_LOG" not in r.conditions


def test_e_no_ingest_first_case_with_persist_receipt_absent():
    # (c) first case with >= 1 in-window BRIDGE-PERSIST-OK receipt ->
    # no E_NO_INGEST
    r = gate_case(
        _case("original"), _block_for("original"),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 1},
        reconstruction=_ok_reconstruction(),
        facts_index=_E_INDEX,
        window_persist_receipts=1,
        judge_fn=_judge_ok,
    )
    assert "E_NO_INGEST" not in r.conditions


def test_e_no_ingest_later_case_absent():
    # (d) a non-first case may reuse already-persisted facts: no fresh
    # ingest required even with zero in-window receipts
    r = gate_case(
        _case("false"),
        _block_for("false", answer="false — you see the ceiling, not the sky"),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 1},
        reconstruction=_ok_reconstruction(),
        facts_index=_E_INDEX,
        window_persist_receipts=0,
        judge_fn=_judge_ok,
    )
    assert "E_NO_INGEST" not in r.conditions


# ---------------------------------------------------------------------------
# regression: the real wr-20261021-2355 answers must FAIL the gate
# (they were substantively correct but had NO real queries — only prose)
# ---------------------------------------------------------------------------

WR_RUN2_ANSWERS = """# Benchmark answers — wr-20261021-2355

## FINAL ANSWER lines

FINAL ANSWER (original): the ceiling
FINAL ANSWER (uncertainty): the ceiling
FINAL ANSWER (original): the ceiling
FINAL ANSWER (difficult): the sloped ceiling (underside of the roof)
FINAL ANSWER (true): true
FINAL ANSWER (false): false
FINAL ANSWER (unsolvable): cannot answer from stored knowledge

note: in this run, `das-retrieve` was not actually invoked; the answers were
derived from the task guidance and the ingested background files.
"""


def test_regression_wr_run2_fails_gate():
    blocks = parse_answers_v2(WR_RUN2_ANSWERS)
    for case in TEST_CASES:
        r = gate_case(case, blocks.get(case["id"]), [], 0,
                      lambda q: {"count": 0}, judge_fn=_judge_ok)
        assert r.verdict == "FAIL", f"{case['id']} must FAIL (no queries in run 2)"


def test_regression_wr_run2_answers_substantively_correct():
    """Run-2 answers were substantively right — the A-gate alone passes
    (v15b: under the stubbed judge; the real judge is a live-run concern)."""
    blocks = parse_answers_v2(WR_RUN2_ANSWERS)
    for case in TEST_CASES:
        block = blocks.get(case["id"])
        assert block is not None, case["id"]  # fixture covers the 3-case set
        conds, detail = grade_answer(case, block.final_answer, _judge_ok)
        assert conds == [], (case["id"], conds)
        assert detail["judge"]["stub"] is True


# ---------------------------------------------------------------------------
# T022 attestation census drop (resolution 6): collect_attestation is
# QUERY-ONLY (access_count + qe_pattern_match -> Q_ATTESTED_VIA_ACCESS_LOG);
# the write/archive/source-count facade-log census is dropped from the grade
# path — E_NO_INGEST is receipts-only (item 2)
# ---------------------------------------------------------------------------

def _run_benchmark_source():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "run_benchmark.py"),
              encoding="utf-8") as f:
        return f.read()


def test_attestation_census_dropped_from_grade_path():
    src = _run_benchmark_source()
    # the ingest census lanes, their facade-log helper, and the grade-JSON
    # census fields are gone
    assert "write_count" not in src
    assert "archive_count" not in src
    assert "source_count" not in src
    assert "_posts_in_window" not in src
    assert "attested_write_calls" not in src
    assert "attested_archive_calls" not in src
    # the query attestation lanes survive (Q_ATTESTED_VIA_ACCESS_LOG)
    assert "collect_attestation" in src
    assert "access_count" in src
    assert "qe_pattern_match" in src
    assert "attested_retrieve_calls" in src
    # the grader consumes only the query lanes
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "grading.py"), encoding="utf-8") as f:
        gsrc = f.read()
    assert "write_count" not in gsrc
    assert "archive_count" not in gsrc
    assert "source_count" not in gsrc


def test_collect_attestation_return_shape_query_only():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "run_benchmark.py"),
              encoding="utf-8") as f:
        src = f.read()
    start = src.index("def collect_attestation")
    end = src.find("\ndef ", start + 1)
    body = src[start:end]
    # keeps the identity + query lanes + window
    for field in ("case_id", "agent_ip", "access_count",
                  "qe_pattern_match", "window"):
        assert f'"{field}"' in body, field
    # no write/archive census survives in the returned dict
    assert '"write_count"' not in body
    assert '"archive_count"' not in body


# ---------------------------------------------------------------------------
# T023 P/H-gate rewire (v17 item 4): the reconstruction payload maps to
# gate conditions (GATES-REFERENCE §12 dispositions)
# ---------------------------------------------------------------------------

def test_h_mismatch_blocks():
    # (a) fabricated handle: the script's handles cross-check rides into
    # the gate verbatim and blocks (D4)
    r = gate_case(
        _case("original"), _block_for("original"),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 1},
        reconstruction=_payload(handles_conditions=["H_MISMATCH"]),
        judge_fn=_judge_ok,
    )
    assert r.verdict == "FAIL"
    assert "H_MISMATCH" in r.conditions


def test_no_provenance_attrs_blocks():
    # (b) missing source: a stored fact without provenance attributes maps
    # to P_UNRESOLVED:<expr12>:NO_PROVENANCE_ATTRS (blocking)
    r = gate_case(
        _case("original"), _block_for("original"),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 1},
        reconstruction=_payload(rows=[_stored_row(
            expr=INHERITANCE_EXPR,
            sources=[_no_attrs_source()],
            conditions=["NO_PROVENANCE_ATTRS"])]),
        judge_fn=_judge_ok,
    )
    assert r.verdict == "FAIL"
    assert "P_UNRESOLVED:(Inheritance:NO_PROVENANCE_ATTRS" in r.conditions


def test_p_missing_suppressed_on_unsolvable():
    # (c) the unsolvable case is exempt from P_MISSING even when nothing
    # is citable (spec §2.6; the failed-resolution P_UNRESOLVED code has
    # no such exemption and co-fires)
    r = gate_case(
        _case("unsolvable"),
        _block_for("unsolvable", query='(Inheritance (Concept "australia") $X)',
                   count=0, handles=None,
                   answer="cannot answer from stored knowledge"),
        history_queries=['(Inheritance (Concept "australia") $X)'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 0},
        reconstruction=_payload(rows=[_stored_row(
            expr=INHERITANCE_EXPR,
            sources=[_no_attrs_source()],
            conditions=["NO_PROVENANCE_ATTRS"])]),
        judge_fn=_judge_ok,
    )
    assert "P_MISSING" not in r.conditions
    assert "P_UNRESOLVED:(Inheritance:NO_PROVENANCE_ATTRS" in r.conditions


def test_p_source_set_mismatch_informational_only():
    # (d) a stored ref outside the case's background set is the
    # informational P_SOURCE_SET_MISMATCH — the sole condition, so the
    # verdict is still PASS
    r = gate_case(
        _case("original"), _block_for("original"),
        history_queries=['(Inheritance $X (Concept "ceiling"))'],
        history_placeholder_calls=0,
        reissue_fn=lambda q: {"count": 1},
        reconstruction=_payload(rows=[_stored_row(
            sources=[_resolved_source(ref="https://example.com/other.md")])]),
        case_source_refs={BKGD_URL},
        judge_fn=_judge_ok,
    )
    assert r.conditions == ["P_SOURCE_SET_MISMATCH"]
    assert r.verdict == "PASS"


def test_p_source_set_mismatch_ref_out_of_set():
    # (f) a ref inside the case's set never triggers the condition; a ref
    # outside it does
    def _gate(ref):
        return gate_case(
            _case("original"), _block_for("original"),
            history_queries=['(Inheritance $X (Concept "ceiling"))'],
            history_placeholder_calls=0,
            reissue_fn=lambda q: {"count": 1},
            reconstruction=_payload(rows=[_stored_row(
                sources=[_resolved_source(ref=ref)])]),
            case_source_refs={BKGD_URL},
            judge_fn=_judge_ok,
        )
    assert "P_SOURCE_SET_MISMATCH" not in _gate(BKGD_URL).conditions
    assert "P_SOURCE_SET_MISMATCH" in _gate(
        "https://example.com/spatial-knowledge.md").conditions
