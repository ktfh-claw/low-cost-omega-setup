"""v10 gate tests: wr3i grader-false-positive fixes + attestation regex.

2026-10-26 night directive (wr3i close-out, state.md branch-5). Live wr3i
evidence: all 6 fired conditions on the uncertainty case were grader-side —
A_SKY (honest negation "no sky visible" tripped the keyword), Q_DEGENERATE_
PATTERN (bare MeTTa symbols not counted as literals), Q_NOT_IN_HISTORY
($_-collapse, informational lane), R_TRACE_NOT_GROUNDED (whole-line vs
atom-set comparison on the EXECUTED derivation line), P URL_MISMATCH x2
(diagnosed agent-side: sha/url mispair — fixed prompt-side, not here), and
the proved harness regex over-escape that zeroed the attested-retrieve lane
all run (fixed in run_benchmark._agent_query_count_in_window).

v10 keeps gates STRICT: negation still fails unnegated keywords, structural
keywords still do not count as literals, fabricated trace atoms still fail.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from grading import (
    _bare_content_symbols,
    _split_derivation_atoms,
    query_is_degenerate,
)

FAKE_SHA = "git:" + "a" * 40


# v15b: the A-gate substance check is the LLM judge; offline unit tests
# stub it deterministically (the real judge is exercised by live runs)
def _judge_ok(case, final_answer):
    return True, {"judge_verdict": "CORRECT", "stub": True}


def _judge_wrong(case, final_answer):
    return False, {"judge_verdict": "INCORRECT", "stub": True}
FAKE_URL = "https://example.com/spatial-knowledge.md"


# ---------------------------------------------------------------------------
# v10 fix 2: bare MeTTa symbols count as query literals (wr3i query rejected)
# ---------------------------------------------------------------------------

def test_wr3i_query_not_degenerate():
    q = "(--> (looking-up windowless-room) $X)"
    assert query_is_degenerate(q) is None


def test_bare_symbol_query_not_degenerate():
    assert query_is_degenerate("(Inheritance ceiling $X)") is None


def test_structural_symbols_only_still_degenerate():
    # structural keywords carry no content: still a tautology probe
    assert query_is_degenerate("(Evaluation $X $Y)") == "Q_DEGENERATE_PATTERN"


def test_quoted_literal_queries_unchanged():
    assert query_is_degenerate('(Inheritance $X (Concept "ceiling"))') is None
    assert query_is_degenerate("(Inheritance $X $Y $Z)") == "Q_DEGENERATE_PATTERN"
    assert query_is_degenerate("$_131542") == "Q_PLACEHOLDER"


def test_bare_content_symbols_helper():
    assert _bare_content_symbols("(--> (looking-up windowless-room) $X)") == {
        "looking-up", "windowless-room"}
    assert _bare_content_symbols('(Inheritance (Concept "x") $Y)') == set()


# ---------------------------------------------------------------------------
# v10 fix 3: executed-derivation trace grounding (atom-wise, not whole-line)
# ---------------------------------------------------------------------------

WR3I_TRACE_STEP = ("(|- ((--> (looking-up windowless-room) sees-ceiling) "
                   "(stv 0.9 0.8)) ((--> (looking-up windowless-room) "
                   "sees-ceiling) (stv 0.9 0.8))) => ((--> (looking-up "
                   "windowless-room) sees-ceiling) (stv 0.9 0.888888888888889))")


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


def test_wr3i_executed_derivation_step_grounded():
    index = ["((--> (looking-up windowless-room) sees-ceiling) (stv 0.9 0.8))"]
    query = "(--> (looking-up windowless-room) $X)"
    reasoning = (query + "; " + index[0] + "; " + WR3I_TRACE_STEP)
    r = _gate("original", index, query, reasoning)
    assert "R_TRACE_NOT_GROUNDED" not in r.conditions, r.detail


def test_fabricated_conclusion_atoms_still_fail():
    index = ["((--> (looking-up windowless-room) sees-ceiling) (stv 0.9 0.8))"]
    query = "(--> (looking-up windowless-room) $X)"
    fabricated = "((--> (gazing-upwards attic-space) beholds-roof-window) (stv 0.7 0.5))"
    reasoning = (query + "; " + index[0] + "; " + fabricated)
    r = _gate("original", index, query, reasoning)
    assert "R_TRACE_NOT_GROUNDED" in r.conditions


def test_split_derivation_atoms_shape():
    atoms = _split_derivation_atoms(WR3I_TRACE_STEP)
    # the 2-arg NAL call ``(|- premise premise)`` parses as ONE balanced
    # s-expression (its output balances via ``=>``) -> call + output = 2 atoms
    assert len(atoms) == 2, atoms
    assert atoms[0].startswith("(|- ")
    assert atoms[-1].endswith("(stv 0.9 0.888888888888889))")
    # non-derivation steps are single atoms (pre-v10 shape)
    assert _split_derivation_atoms("(Inheritance $X $Y)") == ["(Inheritance $X $Y)"]


# ---------------------------------------------------------------------------
# v10 fix 4: attestation regex de-escape (proved-always-zero lane)
# ---------------------------------------------------------------------------

def test_query_post_regex_matches_real_access_log_line():
    import run_benchmark
    # real live read-proxy access-log format (wr3i, 00:00:07.562Z line):
    # `http <ip> "POST /v1/query HTTP/1.1" 200 -`
    line = 'http 172.20.0.6 "POST /v1/query HTTP/1.1" 200 -'
    logs = ('noise\n'
            'http 172.20.0.6 "POST /v1/query HTTP/1.1" 500 -\n'
            f'{line}\n')
    n = run_benchmark._count_query_posts(logs, "172.20.0.6")
    assert n == 1, n  # exactly the one 2xx from the agent IP; 5xx ignored


def test_query_post_regex_agent_ip_specific():
    import run_benchmark
    # host-IP reissue probes (172.20.0.1) must not count as agent queries
    logs = 'http 172.20.0.1 "POST /v1/query HTTP/1.1" 200 -'
    assert run_benchmark._count_query_posts(logs, "172.20.0.6") == 0


def test_query_post_regex_requires_2xx():
    import run_benchmark
    logs = 'http 172.20.0.6 "POST /v1/query HTTP/1.1" 404 -'
    assert run_benchmark._count_query_posts(logs, "172.20.0.6") == 0


# ---------------------------------------------------------------------------
# v10 fix 5 (prompt-side): anti-mispair line is in the template
# (v17 re-point: sha/url pair copying → handle copying, spec §8 item 1)
# ---------------------------------------------------------------------------

def test_prompt_copies_handles_verbatim():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "agent_prompt_template.md")) as f:
        t = f.read()
    # v17: the anti-mispair rule now covers HANDLES — every handle is a
    # character-for-character copy from a receipt the agent holds (the
    # write receipt's `top=` or a das-retrieve receipt's `results=`
    # handles), never re-typed, never re-ordered, never composed, and
    # anything outside a held receipt is fabricated
    assert "never re-type a handle from memory" in t
    assert "never re-typed, never re-ordered, never composed" in t
    assert "A handle that appears in no receipt you hold is fabricated" in t
