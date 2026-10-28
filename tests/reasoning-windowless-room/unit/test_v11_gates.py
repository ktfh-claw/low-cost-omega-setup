"""v11 gate tests: mid-trace atom-wise grounding (wr3j grader defect #4).

2026-10-26 night directive (wr3j close-out, state.md v11 queue). Live wr3j
evidence: the uncertainty case produced the pipeline's first clean answer —
executed PLN derivation, correct conclusion, fully green provenance — but
R_TRACE_NOT_GROUNDED fired on MID-trace steps. Those steps were executed-
derivation outputs the interpreter produced (``atom (stv s c)``); v10's
atom-wise grounding applies only to the FINAL trace step (i==last), so mid
steps fell back to byte comparison and flagged although every atom grounds
under the same literal/bare-symbol rule (all flagged literals were subsets
of the stored vocabulary — they ground under the grader's own rule).

v11 applies atom-wise grounding to EVERY non-first trace step. Gates stay
STRICT: step0 must still be the exact query clause, fabricated mid steps
with new symbols still fire, and a step that is neither recorded nor
derivable from stored vocabulary still fails the case.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

FAKE_SHA = "git:" + "a" * 40


# v15b: the A-gate substance check is the LLM judge; offline unit tests
# stub it deterministically (the real judge is exercised by live runs)
def _judge_ok(case, final_answer):
    return True, {"judge_verdict": "CORRECT", "stub": True}


def _judge_wrong(case, final_answer):
    return False, {"judge_verdict": "INCORRECT", "stub": True}
FAKE_URL = "https://example.com/spatial-knowledge.md"

INDEX_EXPR = ("((--> (looking-up windowless-room) sees-ceiling) (stv 0.9 0.8))")
QUERY = "(--> (looking-up windowless-room) $X)"
# wr3j shape: a mid-trace executed-derivation output — an interpreter
# product (stronger confidence than the stored premise), NOT byte-identical
# to any index expression, NOT the final step.
MID_DERIVATION = ("((--> (looking-up windowless-room) sees-ceiling) "
                  "(stv 0.9 0.888888888888889))")
FINAL_EXEC_STEP = ("(|- ((--> (looking-up windowless-room) sees-ceiling) "
                   "(stv 0.9 0.8)) ((--> (looking-up windowless-room) "
                   "sees-ceiling) (stv 0.9 0.8))) => ((--> (looking-up "
                   "windowless-room) sees-ceiling) (stv 0.9 0.9216))")


def _gate(case_id, index, query, reasoning, **kw):
    kw.setdefault("judge_fn", _judge_ok)
    from facts import TEST_CASES
    from grading import gate_case, normalize_expression

    case = next(c for c in TEST_CASES if c["id"] == case_id)
    text = f"""### CASE {case_id}

QUERY: {query}
DAS_RETRIEVE_OK untrusted=true count=1 truncated=false results=[...]
FACTS: {index[0]}
REASONING: {reasoning}
FINAL ANSWER ({case_id}): the ceiling
SOURCES: {FAKE_SHA} {FAKE_URL}
"""
    from grading import parse_answers_v2
    block = parse_answers_v2(text)[case_id]
    return gate_case(
        case, block, [normalize_expression(query)], 0,
        (lambda q: {"count": 1}),
        [(FAKE_SHA, FAKE_URL, [])],
        facts_index=index,
        window_persist_receipts=1,
        **kw,
    )


def test_wr3j_mid_trace_derivation_output_grounded():
    # the exact wr3j shape: query; stored premise; MID derivation output;
    # final executed line. v10 flagged the mid step (byte comparison);
    # v11 grounds it atom-wise over the stored vocabulary.
    index = [INDEX_EXPR]
    reasoning = QUERY + "; " + INDEX_EXPR + "; " + MID_DERIVATION + "; " + FINAL_EXEC_STEP
    r = _gate("original", index, QUERY, reasoning)
    assert "R_TRACE_NOT_GROUNDED" not in r.conditions, r.detail


def test_mid_derivation_not_last_step():
    # fixture guard: the mid derivation sits at position -2, NOT last —
    # v10 would ground it only via the i==last branch; v11 must ground it
    # via the every-step atom-wise rule
    steps = [s.strip() for s in (QUERY + "; " + INDEX_EXPR + "; " + MID_DERIVATION
                                 + "; " + FINAL_EXEC_STEP).split("; ")]
    assert len(steps) == 4, steps
    assert steps[-1] == FINAL_EXEC_STEP
    assert steps[-2] == MID_DERIVATION
    assert steps[0] == QUERY


def test_fabricated_mid_step_still_fails():
    # STRICTNESS: a fabricated mid step introduces a NEW symbol pair absent
    # from every stored vocabulary -> must still fire R_TRACE_NOT_GROUNDED
    index = [INDEX_EXPR]
    fabricated = "((--> (gazing-upwards attic-space) beholds-roof-window) (stv 0.7 0.5))"
    reasoning = QUERY + "; " + INDEX_EXPR + "; " + fabricated
    r = _gate("original", index, QUERY, reasoning)
    assert "R_TRACE_NOT_GROUNDED" in r.conditions


def test_first_step_query_rule_unchanged():
    # step0 must still be the exact formalized question clause
    index = [INDEX_EXPR]
    reasoning = INDEX_EXPR + "; " + MID_DERIVATION
    r = _gate("original", index, QUERY, reasoning)
    assert "R_TRACE_NOT_GROUNDED" in r.conditions
