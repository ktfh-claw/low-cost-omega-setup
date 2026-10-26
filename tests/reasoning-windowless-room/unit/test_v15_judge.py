"""v15/v16 unit tests: the A-gate LLM judge (llm_judge.py).

Introduced v15b (directive 2026-10-26 22:56 UTC), simplified in v16 to
the single-prompt TRUE/FALSE form per the follow-up directive: ONE user
message containing the test prompt (question), the Omega agent's final
answer, and the expected correct answer; the endpoint replies TRUE or
FALSE; the parsed verdict is the blocking A-gate. Design contract under
test:
  - single-prompt isolation: one user message, exactly the three
    items — never the reasoning trace, receipts, queries, citations,
    or any other gate evidence;
  - verdict parsing: first TRUE/FALSE token wins; junk raises;
  - API-key resolution precedence: arg > env (ASIONE_API_KEY /
    OPENAI_API_KEY / WR_JUDGE_API_KEY) > the Omega deployment
    runtime.env (the same key the Omega agent uses);
  - fail-safe: no resolvable key -> JudgeUnavailable at construction
    (the gate then emits A_JUDGE_UNAVAILABLE and fails the case).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import llm_judge
from facts import TEST_CASES


def _case(cid):
    return next(c for c in TEST_CASES if c["id"] == cid)


# ---------------------------------------------------------------------------
# single-prompt shape: one user message, question + expected + answer
# ---------------------------------------------------------------------------

def test_prompt_is_single_user_message():
    msgs = llm_judge.build_messages(_case("original"), "the ceiling")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_prompt_contains_question_expected_and_answer():
    case = _case("false")
    ans = "false — you see the ceiling, not the sky"
    msgs = llm_judge.build_messages(case, ans)
    content = msgs[0]["content"]
    assert case["question"] in content
    assert case["expected_answer"] in content
    assert ans in content
    # each appears exactly once (no duplicated evidence injection)
    assert content.count(case["question"]) == 1
    assert content.count(ans) == 1


def test_prompt_asks_true_or_false():
    msgs = llm_judge.build_messages(_case("original"), "the ceiling")
    assert "Reply with exactly one word: TRUE or FALSE" in msgs[0]["content"]


def test_prompt_has_no_other_inputs():
    """No grading-guidance/JSON fields, no system prompt, no evidence
    sections — the judge cannot see anything beyond the three items."""
    case = _case("original")
    msgs = llm_judge.build_messages(case, "the ceiling")
    content = msgs[0]["content"]
    assert "grading_guidance" not in content
    assert "REASONING:" not in content
    assert "SOURCES:" not in content
    assert case.get("grading", "") not in content


def test_judge_payload_carries_no_gate_evidence():
    """Evidence strings inside the agent's answer ride only as the answer
    itself — never as separate fields the judge could weigh."""
    ans = ("the ceiling. REASONING: (|- a b) => (stv 1 0); "
           "DAS_RETRIEVE_OK count=1; SOURCES: git:abc")
    msgs = llm_judge.build_messages(_case("false"), ans)
    content = msgs[0]["content"]
    assert content.count("REASONING:") == 1     # only inside the answer
    assert content.count("DAS_RETRIEVE_OK") == 1
    assert content.count(ans) == 1


# ---------------------------------------------------------------------------
# verdict parsing: simple TRUE / FALSE
# ---------------------------------------------------------------------------

def test_parse_verdict_true():
    assert llm_judge.parse_verdict("TRUE") is True
    assert llm_judge.parse_verdict("true") is True
    assert llm_judge.parse_verdict("True. The answer matches the expected one.") is True


def test_parse_verdict_false():
    assert llm_judge.parse_verdict("FALSE") is False
    assert llm_judge.parse_verdict("false") is False
    assert llm_judge.parse_verdict("False: the agent names the sky.") is False


def test_parse_verdict_junk_raises():
    for junk in ("", "yes", "correct", "the answer seems fine", "PASSED", None):
        try:
            llm_judge.parse_verdict(junk)
            raise AssertionError(f"expected JudgeUnavailable for {junk!r}")
        except llm_judge.JudgeUnavailable:
            pass


def test_parse_verdict_first_token_wins():
    assert llm_judge.parse_verdict("FALSE but TRUE appears later in the sentence") is False
    assert llm_judge.parse_verdict("TRUE even though FALSE appears later") is True


# ---------------------------------------------------------------------------
# API-key resolution precedence (same key the Omega agent uses)
# ---------------------------------------------------------------------------

_ENV_VARS = ("ASIONE_API_KEY", "OPENAI_API_KEY", "WR_JUDGE_API_KEY")


def _clear_env():
    saved = {v: os.environ.pop(v, None) for v in _ENV_VARS}
    return saved


def _restore_env(saved):
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


def test_resolve_api_key_arg_wins():
    saved = _clear_env()
    try:
        os.environ["ASIONE_API_KEY"] = "env-key"
        key, src = llm_judge.resolve_api_key("arg-key", "/nonexistent/runtime.env")
        assert key == "arg-key" and src == "arg"
    finally:
        _restore_env(saved)


def test_resolve_api_key_env_before_runtime_env():
    saved = _clear_env()
    try:
        os.environ["OPENAI_API_KEY"] = "env-key"
        key, src = llm_judge.resolve_api_key("", "/nonexistent/runtime.env")
        assert key == "env-key" and src == "env"
    finally:
        _restore_env(saved)


def test_resolve_api_key_runtime_env_fallback():
    saved = _clear_env()
    tmp = os.path.join(HERE, "tmp-runtime-env-v15.txt")
    try:
        with open(tmp, "w") as f:
            f.write("# comment\nASIONE_API_KEY=rt-key\n")
        key, src = llm_judge.resolve_api_key("", tmp)
        assert key == "rt-key" and src == "runtime.env"
    finally:
        os.path.exists(tmp) and os.remove(tmp)
        _restore_env(saved)


def test_resolve_api_key_missing_raises():
    saved = _clear_env()
    try:
        try:
            llm_judge.resolve_api_key("", "/nonexistent/runtime.env")
            raise AssertionError("expected JudgeUnavailable")
        except llm_judge.JudgeUnavailable:
            pass
    finally:
        _restore_env(saved)


def test_make_judge_without_key_raises_unavailable():
    saved = _clear_env()
    try:
        try:
            llm_judge.make_judge(api_key="", runtime_env_path="/nonexistent/runtime.env")
            raise AssertionError("expected JudgeUnavailable")
        except llm_judge.JudgeUnavailable:
            pass
    finally:
        _restore_env(saved)


# ---------------------------------------------------------------------------
# facts.py grading fields stay answer-only documentation
# ---------------------------------------------------------------------------

def test_case_grading_guidance_is_answer_only_wording():
    for case in TEST_CASES:
        g = case["grading"]
        assert g.startswith("CORRECT iff"), (case["id"], g)
        assert "PASS iff" not in g, (case["id"], g)
        assert "reasoning trace" not in g.lower(), (case["id"], g)


def test_template_names_answer_judge_honestly():
    """v15b/v16: the template no longer claims blanket determinism —
    format gates stay deterministic, answer substance is LLM-judged."""
    with open(os.path.join(HERE, "..", "agent_prompt_template.md"),
              encoding="utf-8") as f:
        t = f.read()
    assert "GRADED BY A MACHINE GATE" in t
    assert "DETERMINISTIC MACHINE GATE" not in t
    assert "exact regexes" in t            # format gates unchanged
    assert "LLM evaluator" in t           # answer substance = judge
    assert "sees only the question" in t   # judge isolation, agent-visible
