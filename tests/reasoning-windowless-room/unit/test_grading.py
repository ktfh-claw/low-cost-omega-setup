"""Unit tests for grading.py v2 — the strict GATE (A/Q/P), deterministic, no LLM.

Covers: answers.md parsing (### CASE blocks), degenerate-query detection,
per-case answer grading, and the full gate_case logic with synthetic
history/reissue/citation inputs, plus the wr-20261021-2355 regression
(the real run-2 answers must FAIL the gate — it had no real queries).
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
    parse_citations,
    CaseBlock,
)


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
REASONING: (Inheritance $X (Concept "ceiling")); (Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))
FINAL ANSWER (original): the ceiling
SOURCES: git:8ffa0b35049c1b9545b08700c0594dc5eb68043e https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/main/tests/reasoning-windowless-room/background/spatial-knowledge.md

### CASE unsolvable

QUERY: (Inheritance (Concept "australia") $X)
DAS_RETRIEVE_OK untrusted=true count=0 truncated=false results=[]
REASONING: (Inheritance (Concept "australia") $X); (Inheritance $X (Concept "australia"))
FINAL ANSWER (unsolvable): cannot answer from stored knowledge
SOURCES: none (absence case)
"""


def test_parse_answers_v2_blocks():
    blocks = parse_answers_v2(GOOD_ANSWERS)
    assert set(blocks.keys()) == {"original", "unsolvable"}
    assert blocks["original"].final_answer == "the ceiling"
    assert blocks["original"].queries == ['(Inheritance $X (Concept "ceiling"))']
    assert blocks["original"].receipt_counts == [1]
    assert "git:8ffa0b35" in blocks["original"].sources_raw


def test_parse_answers_v2_receipt_count():
    blocks = parse_answers_v2(GOOD_ANSWERS)
    assert blocks["unsolvable"].receipt_counts == [0]


def test_parse_answers_v2_bare_final_answer_compatibility():
    """FINAL ANSWER lines outside ### CASE blocks still parse (v1 shape)."""
    text = "FINAL ANSWER (easy): the ceiling"
    blocks = parse_answers_v2(text)
    assert blocks["easy"].final_answer == "the ceiling"


def test_parse_answers_v2_query_quoted_form():
    text = '### CASE easy\n\nQUERY: "(Inheritance $X (Concept \\"ceiling\\"))"\nFINAL ANSWER (easy): the ceiling\n'
    blocks = parse_answers_v2(text)
    assert blocks["easy"].queries == ['(Inheritance $X (Concept "ceiling"))']


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
# answer grading (substantive)
# ---------------------------------------------------------------------------

def test_grade_answer_ceiling_cases():
    for cid in ("original", "uncertainty", "easy"):
        assert grade_answer(cid, "the ceiling") == []
        assert grade_answer(cid, "the sky") == ["A_SKY"]
        assert grade_answer(cid, "a lamp") == ["A_WRONG"]
        assert grade_answer(cid, "") == ["A_MISSING"]


def test_grade_answer_difficult():
    assert grade_answer("difficult", "the sloped ceiling (underside of the roof)") == []
    assert grade_answer("difficult", "the sky") == ["A_SKY"]
    assert grade_answer("difficult", "the ceiling") == ["A_WRONG"]


def test_grade_answer_true_false():
    assert grade_answer("true", "true") == []
    assert grade_answer("true", "false") == ["A_WRONG"]
    assert grade_answer("false", "false") == []
    assert grade_answer("false", "true") == ["A_WRONG"]


def test_grade_answer_unsolvable():
    assert grade_answer("unsolvable", "cannot answer from stored knowledge") == []
    assert grade_answer("unsolvable", "Canberra") == ["A_FABRICATED"]
    assert grade_answer("unsolvable", "maybe something") == ["A_NO_INABILITY"]


# ---------------------------------------------------------------------------
# gate_case
# ---------------------------------------------------------------------------

def _pass_reissue(query):
    return {"count": 1}


def _ok_citations():
    SHA = "git:8ffa0b35049c1b9545b08700c0594dc5eb68043e"
    return [(SHA, "https://example.com/spatial-knowledge.md", [])]


def _block_for(case_id, query='(Inheritance $X (Concept "ceiling"))', count=1,
               sources="git:8ffa0b35049c1b9545b08700c0594dc5eb68043e https://example.com/spatial-knowledge.md",
               answer="the ceiling", order="query_first", reasoning=None):
    q_line = f"QUERY: {query}"
    r_line = f"DAS_RETRIEVE_OK untrusted=true count={count} truncated=false results=[]"
    a_line = f"FINAL ANSWER ({case_id}): {answer}"
    s_line = f"SOURCES: {sources}"
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
        text = f"{q_line}\n{r_line}\n{reason_line}\n{a_line}\n{s_line}\n"
    else:
        text = f"{a_line}\n{q_line}\n{r_line}\n{reason_line}\n{s_line}\n"
    return parse_answers_v2(f"### CASE {case_id}\n\n{text}")[case_id]


def test_gate_case_full_pass():
    case = _case("original")
    block = _block_for("original")
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  citation_checks=_ok_citations())
    assert r.verdict == "PASS", r.conditions
    assert r.conditions == []


def test_gate_case_query_not_in_history_fails():
    case = _case("original")
    block = _block_for("original")
    r = gate_case(case, block,
                  history_queries=[],  # nothing real in the window
                  history_placeholder_calls=3,  # only $_ placeholder calls
                  reissue_fn=lambda q: {"count": 1},
                  citation_checks=_ok_citations())
    assert r.verdict == "FAIL"
    assert "Q_NOT_IN_HISTORY" in r.conditions
    assert "Q_PLACEHOLDER" in r.conditions


def test_gate_case_placeholder_query_fails():
    case = _case("easy")
    block = _block_for("easy", query="$_131542")
    r = gate_case(case, block,
                  history_queries=["$_131542"],
                  history_placeholder_calls=1,
                  reissue_fn=lambda q: {"count": 1},
                  citation_checks=_ok_citations())
    assert r.verdict == "FAIL"
    assert "Q_PLACEHOLDER" in r.conditions


def test_gate_case_degenerate_query_fails():
    case = _case("easy")
    block = _block_for("easy", query="(Inheritance $X $Y)")
    r = gate_case(case, block,
                  history_queries=["(Inheritance $X $Y)"],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  citation_checks=_ok_citations())
    assert r.verdict == "FAIL"
    assert "Q_DEGENERATE_PATTERN" in r.conditions


def test_gate_case_reissue_mismatch_fails():
    case = _case("easy")
    block = _block_for("easy", count=5)
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},  # quoted 5, reissue 1
                  citation_checks=_ok_citations())
    assert r.verdict == "FAIL"
    assert "Q_REISSUE_MISMATCH" in r.conditions


def test_gate_case_no_receipt_fails():
    case = _case("easy")
    block = _block_for("easy")
    block.receipt_counts = []
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  citation_checks=_ok_citations())
    assert r.verdict == "FAIL"
    assert "Q_NO_RECEIPT" in r.conditions


def test_gate_case_answer_after_query_order_fails():
    case = _case("easy")
    block = _block_for("easy", order="answer_first")
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  citation_checks=_ok_citations())
    assert r.verdict == "FAIL"
    assert "Q_NOT_QUERY_FIRST" in r.conditions


def test_gate_case_missing_sources_fails():
    case = _case("easy")
    block = _block_for("easy", sources="")
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  citation_checks=_ok_citations())
    assert r.verdict == "FAIL"
    assert "P_MISSING" in r.conditions


def test_gate_case_unresolved_citation_fails():
    case = _case("easy")
    block = _block_for("easy")
    SHA = "git:8ffa0b35049c1b9545b08700c0594dc5eb68043e"
    bad = [(SHA, "https://example.com/spatial-knowledge.md", ["COMMIT_NOT_IN_REPO"])]
    r = gate_case(case, block,
                  history_queries=['(Inheritance $X (Concept "ceiling"))'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  citation_checks=bad)
    assert r.verdict == "FAIL"
    assert "P_UNRESOLVED:COMMIT_NOT_IN_REPO" in r.conditions


def test_gate_case_unsolvable_requires_proven_absence():
    case = _case("unsolvable")
    block = _block_for(
        "unsolvable",
        query='(Inheritance (Concept "australia") $X)',
        count=0,
        sources="none (absence case)",
        answer="cannot answer from stored knowledge",
    )
    r = gate_case(case, block,
                  history_queries=['(Inheritance (Concept "australia") $X)'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 0},
                  citation_checks=[])
    assert r.verdict == "PASS", r.conditions


def test_gate_case_unsolvable_fabricated_fails():
    case = _case("unsolvable")
    block = _block_for(
        "unsolvable",
        query='(Inheritance (Concept "australia") $X)',
        count=0,
        sources="none",
        answer="Canberra",
    )
    r = gate_case(case, block,
                  history_queries=['(Inheritance (Concept "australia") $X)'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 0},
                  citation_checks=[])
    assert r.verdict == "FAIL"
    assert "A_FABRICATED" in r.conditions


def test_gate_case_unsolvable_count_positive_fails():
    """Unsolvable case with count>0 hasn't PROVEN absence."""
    case = _case("unsolvable")
    block = _block_for(
        "unsolvable",
        query='(Inheritance (Concept "australia") $X)',
        count=1,
        sources="none",
        answer="cannot answer from stored knowledge",
    )
    r = gate_case(case, block,
                  history_queries=['(Inheritance (Concept "australia") $X)'],
                  history_placeholder_calls=0,
                  reissue_fn=lambda q: {"count": 1},
                  citation_checks=[])
    assert r.verdict == "FAIL"
    assert "Q_ABSENCE_UNPROVEN" in r.conditions


def test_gate_case_missing_block_quad_fail():
    case = _case("original")
    r = gate_case(case, None, [], 0, None, [])
    assert r.verdict == "FAIL"
    assert set(r.conditions) == {"A_MISSING", "Q_MISSING", "P_MISSING", "R_MISSING"}


def test_gate_summary_aggregates():
    ok = gate_case(_case("easy"),
                   _block_for("easy"),
                   ['(Inheritance $X (Concept "ceiling"))'],
                   0, lambda q: {"count": 1}, _ok_citations())
    bad = gate_case(_case("original"), None, [], 0, None, [])
    summary = gate_summary([ok, bad])
    assert summary["gate_verdict"] == "FAIL"
    assert summary["cases_passed"] == 1
    assert summary["cases_total"] == 2


# ---------------------------------------------------------------------------
# regression: the real wr-20261021-2355 answers must FAIL the gate
# (they were substantively correct but had NO real queries — only prose)
# ---------------------------------------------------------------------------

WR_RUN2_ANSWERS = """# Benchmark answers — wr-20261021-2355

## FINAL ANSWER lines

FINAL ANSWER (original): the ceiling
FINAL ANSWER (uncertainty): the ceiling
FINAL ANSWER (easy): the ceiling
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
                      lambda q: {"count": 0}, [])
        assert r.verdict == "FAIL", f"{case['id']} must FAIL (no queries in run 2)"


def test_regression_wr_run2_all_answers_substantively_correct():
    """Run-2 answers were substantively right — the A-gate alone passes."""
    blocks = parse_answers_v2(WR_RUN2_ANSWERS)
    expected = {
        "original": [], "uncertainty": [], "easy": [],
        "difficult": [], "true": [], "false": [],
        "unsolvable": [],
    }
    for case in TEST_CASES:
        block = blocks.get(case["id"])
        answer = block.final_answer if block else ""
        assert grade_answer(case["id"], answer) == expected[case["id"]], case["id"]
