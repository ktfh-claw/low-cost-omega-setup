#!/usr/bin/env python3
"""v17 harness iteration 2: R-gate exec-line tolerance (wr3o-20261028).

Live wr3o-20261028 evidence (verbatim fixtures pulled fresh from OVH,
2026-10-28): the extraction record's exec lines record the derivation
OUTPUT with an EXTRA outer paren layer —

    exec (|~ ((Implication (Evaluation "looks-up-in" "room" $X)
                           (Evaluation "sees" "room" $X)) (stv 1.0 0.9))
             ((Evaluation "looks-up-in" "room" "ceiling") (stv 1.0 0.9)))
        => (((Evaluation "sees" "room" "ceiling") (stv 1.0 0.81)))

(facts-index.md line :32) — while the answers.md REASONING trace quotes
the interpreter's SINGLE-wrapped product
``((Evaluation "sees" "room" "ceiling") (stv 1.0 0.81))``. The v11
byte-match grounding (``idx_set |= set(exec_outputs)``) therefore never
fired: the record's output is double-wrapped, the trace's is not. The
conclusion atom fell to the vocabulary check, whose predicate ("sees" —
introduced by the agent-authored Implication rule) is present in no
stored atom -> R_TRACE_NOT_GROUNDED fired on a fully executed,
interpreter-produced derivation (HARNESS defect, same live-shape family
as the reconstruct stv tolerances, commit 3650729). Identical mechanism
on the false case (facts-index.md line :44, "blocks-view" pair).

The derivation step has TWO atoms, and BOTH failed:
  - the CALL side  ``(|~ ...)`` — never in the grounding set at all, and
    its literals include the agent-authored rule predicate;
  - the CONCLUSION — byte-mismatch by exactly one paren layer.

The fix (grading.py):
  - ``exec_grounding_set`` adds to the R-gate grounding set (1) the
    exec-line CALL sides verbatim and (2) the OUTPUT sides raw PLUS a
    conservative single redundant-outer-paren strip (raw and stripped
    variants both in the set).
Gates stay STRICT: fabricated conclusions with new symbols still fire
R_TRACE_NOT_GROUNDED, and a two-product output (``((A ...) (B ...))``)
is NOT stripped — only a single redundant wrapping is tolerated.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))


def _judge_ok(case, final_answer):
    return True, {"judge_verdict": "CORRECT", "stub": True}


# --- verbatim wr3o-20261028 fixtures (facts-index.md / answers.md) ------

EXEC_LINE_ORIGINAL = (
    'exec (|~ ((Implication (Evaluation "looks-up-in" "room" $X) '
    '(Evaluation "sees" "room" $X)) (stv 1.0 0.9)) '
    '((Evaluation "looks-up-in" "room" "ceiling") (stv 1.0 0.9))) '
    '=> (((Evaluation "sees" "room" "ceiling") (stv 1.0 0.81)))'
)

REASONING_ORIGINAL = (
    '(Evaluation "looks-up-in" "room" $X); '
    '(Evaluation "looks-up-in" "room" "ceiling"); '
    '(Evaluation "mounted-on" "light-bulb" "ceiling"); '
    '(|~ ((Implication (Evaluation "looks-up-in" "room" $X) '
    '(Evaluation "sees" "room" $X)) (stv 1.0 0.9)) '
    '((Evaluation "looks-up-in" "room" "ceiling") (stv 1.0 0.9))) '
    '=> ((Evaluation "sees" "room" "ceiling") (stv 1.0 0.81))'
)

INDEX_ORIGINAL = [
    '(Evaluation "looks-up-in" "room" "ceiling")',
    '(Evaluation "mounted-on" "light-bulb" "ceiling")',
]

RECORD_ORIGINAL = "\n".join([
    "# Extraction record — wr3o-20261028",
    'expr (Evaluation "looks-up-in" "room" "ceiling") '
    'top=b2842448fa6583e2646daaabfe786729',
    'expr (Evaluation "mounted-on" "light-bulb" "ceiling") '
    'top=3b2c0da7d27b533e34ce6e627b1aef0b',
    'query (Evaluation "looks-up-in" "room" $X) count=1 '
    '[X=ceiling, handle b2842448fa6583e2646daaabfe786729]',
    EXEC_LINE_ORIGINAL,
])

QUERY_ORIGINAL = '(Evaluation "looks-up-in" "room" $X)'

ANSWERS_ORIGINAL = f"""### CASE original

QUERY: {QUERY_ORIGINAL}
DAS_RETRIEVE_OK untrusted=true count=1 truncated=false results=[{{"handles": ["b2842448fa6583e2646daaabfe786729"], "assignments": {{"X": "ceiling"}}}}]
FACTS: (Evaluation "looks-up-in" "room" "ceiling"); (Evaluation "mounted-on" "light-bulb" "ceiling")
HANDLES: b2842448fa6583e2646daaabfe786729 3b2c0da7d27b533e34ce6e627b1aef0b
REASONING: {REASONING_ORIGINAL}
FINAL ANSWER (original): The ceiling — you see the room/attic's ceiling, lit by the bulb; being windowless, it is not the sky.
"""

EXEC_LINE_FALSE = (
    'exec (|~ ((Implication (Evaluation "blocks-view-of" $X $Y) '
    '(Evaluation "blocks-view" "room" $Y)) (stv 1.0 0.9)) '
    '((Evaluation "blocks-view-of" "ceiling" "sky") (stv 1.0 0.9))) '
    '=> (((Evaluation "blocks-view" "room" "sky") (stv 1.0 0.81)))'
)

REASONING_FALSE = (
    '(Evaluation "blocks-view-of" "ceiling" $X); '
    '(Evaluation "blocks-view-of" "ceiling" "sky") (stv 1.0 0.9); '
    '(|~ ((Implication (Evaluation "blocks-view-of" $X $Y) '
    '(Evaluation "blocks-view" "room" $Y)) (stv 1.0 0.9)) '
    '((Evaluation "blocks-view-of" "ceiling" "sky") (stv 1.0 0.9))) '
    '=> ((Evaluation "blocks-view" "room" "sky") (stv 1.0 0.81)); '
    '(Evaluation "looks-up-in" "room" "ceiling") (stv 1.0 0.9)'
)

INDEX_FALSE = [
    '(Evaluation "blocks-view-of" "ceiling" "sky")',
    '(Evaluation "looks-up-in" "room" "ceiling")',
]

RECORD_FALSE = "\n".join([
    "# Extraction record — wr3o-20261028",
    'expr (Evaluation "blocks-view-of" "ceiling" "sky") '
    'top=573401b685722754bfa49f48f629c47d',
    'expr (Evaluation "looks-up-in" "room" "ceiling") '
    'top=b2842448fa6583e2646daaabfe786729',
    EXEC_LINE_FALSE,
])

QUERY_FALSE = '(Evaluation "blocks-view-of" "ceiling" $X)'

# NOTE: the false case's live FACTS line claims
# (Inheritance "windowless-room" "room") which the agent never recorded
# in the index (the agent-level write/claim normalization defect). The
# fixture keeps the OTHER two facts so the R-gate half is exercised
# exactly as live.
ANSWERS_FALSE = f"""### CASE false

QUERY: {QUERY_FALSE}
DAS_RETRIEVE_OK untrusted=true count=1 truncated=false results=[{{"handles": ["573401b685722754bfa49f48f629c47d"], "assignments": {{"X": "sky"}}}}]
FACTS: (Evaluation "blocks-view-of" "ceiling" "sky"); (Evaluation "looks-up-in" "room" "ceiling"); (Inheritance "windowless-room" "room")
HANDLES: 573401b685722754bfa49f48f629c47d b2842448fa6583e2646daaabfe786729 a06f0e0028d04826dfe6382ca8bc5810
REASONING: {REASONING_FALSE}
FINAL ANSWER (false): False — a windowless room's ceiling blocks the view of the sky, so turning on a light and looking up you see the ceiling, not the sky.
"""


def _gate(case_id, answers_text, index, record, **kw):
    kw.setdefault("judge_fn", _judge_ok)
    from facts import TEST_CASES
    from grading import gate_case, normalize_expression, parse_answers_v2

    case = next(c for c in TEST_CASES if c["id"] == case_id)
    block = parse_answers_v2(answers_text)[case_id]
    query = normalize_expression(block.queries[0])
    return gate_case(
        case, block, [query], 0,
        (lambda q: {"count": 1}),
        facts_index=index,
        window_persist_receipts=1,
        facts_index_raw=record,
        **kw,
    )


# --- live-shape pins: the full verbatim wr3o fixtures ---------------------

def test_wr3o_original_live_fixture_fully_grounded():
    # The exact live original case (answers block + facts index + exec
    # record, verbatim): every trace step grounds -> no R_TRACE_NOT_GROUNDED
    # -> with receipts present the case PASSES all gates.
    r = _gate("original", ANSWERS_ORIGINAL, INDEX_ORIGINAL, RECORD_ORIGINAL)
    assert "R_TRACE_NOT_GROUNDED" not in r.conditions, r.detail
    assert r.verdict == "PASS", (r.conditions, r.detail)


def test_wr3o_false_live_fixture_r_gate_grounded():
    # The exact live false case: the derivation call + conclusion ground
    # (both paren-layer and call-side shapes) — the agent-level
    # E_FACTS_NOT_IN_INDEX defect (unrecorded Inheritance claim) still
    # fires: the harness fix must NOT mask agent defects.
    r = _gate("false", ANSWERS_FALSE, INDEX_FALSE, RECORD_FALSE)
    assert "R_TRACE_NOT_GROUNDED" not in r.conditions, r.detail
    assert "E_FACTS_NOT_IN_INDEX" in r.conditions, r.conditions


# --- mechanism pins: the grounding set itself ---------------------------

def test_exec_grounding_set_original_shape():
    from grading import exec_grounding_set, normalize_expression as ne
    g = exec_grounding_set(RECORD_ORIGINAL)
    # raw verbatim output — the double-wrapped live shape (:32)
    assert ne('(((Evaluation "sees" "room" "ceiling") (stv 1.0 0.81)))') in g
    # one redundant outer paren stripped — the trace's single-wrapped form
    assert ne('((Evaluation "sees" "room" "ceiling") (stv 1.0 0.81))') in g
    # the exec-line CALL side, verbatim (executed artifact; its literals
    # include the agent-authored rule predicate — in no stored atom)
    assert ne('(|~ ((Implication (Evaluation "looks-up-in" "room" $X) '
              '(Evaluation "sees" "room" $X)) (stv 1.0 0.9)) '
              '((Evaluation "looks-up-in" "room" "ceiling") (stv 1.0 0.9)))') in g


def test_exec_grounding_set_false_shape():
    from grading import exec_grounding_set, normalize_expression as ne
    g = exec_grounding_set(RECORD_FALSE)
    assert ne('(((Evaluation "blocks-view" "room" "sky") (stv 1.0 0.81)))') in g
    assert ne('((Evaluation "blocks-view" "room" "sky") (stv 1.0 0.81))') in g
    assert ne('(|~ ((Implication (Evaluation "blocks-view-of" $X $Y) '
              '(Evaluation "blocks-view" "room" $Y)) (stv 1.0 0.9)) '
              '((Evaluation "blocks-view-of" "ceiling" "sky") (stv 1.0 0.9)))') in g


def test_grounding_set_absent_record_is_empty():
    # no exec lines -> empty grounding set (no crash, no phantom grounding)
    from grading import exec_grounding_set
    assert exec_grounding_set("") == set()
    assert exec_grounding_set("expr (A) top=deadbeef\nno exec here") == set()


def test_two_product_output_not_stripped():
    # STRICT: a two-product exec output `((A …) (B …))` keeps its outer
    # layer — only a single REDUNDANT wrapping is stripped, so paired
    # products are never mistaken for one parenthesized atom.
    from grading import exec_grounding_set, normalize_expression as ne
    record = ("exec (|- ((--> a b) (stv 1.0 0.9)) ((--> c d) (stv 1.0 0.9))) "
              "=> (((--> a b) (stv 1.0 0.9)) ((--> c d) (stv 1.0 0.9)))")
    g = exec_grounding_set(record)
    assert ne('(((--> a b) (stv 1.0 0.9)) ((--> c d) (stv 1.0 0.9)))') in g
    assert ne('((--> a b) (stv 1.0 0.9)) ((--> c d) (stv 1.0 0.9))') not in g


def test_single_wrapped_pair_not_stripped():
    # the NORMAL interpreter product `((atom) (stv s c))` is a pair, not a
    # redundant wrap — the strip rule must not dissolve it
    from grading import exec_grounding_set, normalize_expression as ne
    record = 'exec (|~ (p (stv 1.0 0.9)) (q (stv 1.0 0.9))) => ((--> a b) (stv 1.0 0.81))'
    g = exec_grounding_set(record)
    assert ne('((--> a b) (stv 1.0 0.81))') in g
    assert ne('(--> a b)') not in g  # the atom-without-stv is NOT minted


# --- strictness pins: fabricated steps still fail -----------------------

def test_fabricated_conclusion_with_new_symbols_still_fires():
    # a conclusion whose predicate/target symbols exist in NO stored
    # vocabulary and in NO exec line must still fail grounding
    fabricated_reasoning = (
        QUERY_ORIGINAL + '; ' + INDEX_ORIGINAL[0] + '; '
        '(|~ ((Implication (Evaluation "looks-up-in" "room" $X) '
        '(Evaluation "glimpses" "corridor" $X)) (stv 1.0 0.9)) '
        '((Evaluation "looks-up-in" "room" "ceiling") (stv 1.0 0.9))) '
        '=> ((Evaluation "glimpses" "corridor" "ceiling") (stv 1.0 0.81))'
    )
    r = _gate("original", ANSWERS_ORIGINAL.replace(REASONING_ORIGINAL,
                                                   fabricated_reasoning),
              INDEX_ORIGINAL, RECORD_ORIGINAL)
    assert "R_TRACE_NOT_GROUNDED" in r.conditions, r.conditions


def test_trace_quoting_double_wrapped_record_form_also_grounded():
    # tolerance is symmetric: if the agent quotes the record's verbatim
    # double-wrapped output in the trace, it grounds via the raw variant
    reasoning_raw = (
        QUERY_ORIGINAL + '; ' + INDEX_ORIGINAL[0] + '; '
        + '(|~ ((Implication (Evaluation "looks-up-in" "room" $X) '
        '(Evaluation "sees" "room" $X)) (stv 1.0 0.9)) '
        '((Evaluation "looks-up-in" "room" "ceiling") (stv 1.0 0.9))) '
        '=> (((Evaluation "sees" "room" "ceiling") (stv 1.0 0.81)))'
    )
    r = _gate("original", ANSWERS_ORIGINAL.replace(REASONING_ORIGINAL,
                                                   reasoning_raw),
              INDEX_ORIGINAL, RECORD_ORIGINAL)
    assert "R_TRACE_NOT_GROUNDED" not in r.conditions, r.detail
