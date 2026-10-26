"""v15 unit tests: the A-gate LLM judge (llm_judge.py, directive 2026-10-26
22:56 UTC).

The answer-substance check is now ONE OpenAI chat-completions-compatible
call. Design contract under test:
  - isolation: the judge payload carries ONLY the question, the ground
    truth (expected answer + answer-only grading guidance), and the
    FINAL ANSWER text — never the reasoning trace, receipts, queries, or
    any other gate evidence;
  - verdict parsing: first CORRECT/INCORRECT token wins; junk raises;
  - API-key resolution precedence: arg > env (ASIONE_API_KEY /
    OPENAI_API_KEY / WR_JUDGE_API_KEY) > the Omega deployment
    runtime.env;
  - fail-safe: no resolvable key -> JudgeUnavailable at construction (the
    gate then emits A_JUDGE_UNAVAILABLE and fails the case — an unjudged
    answer can never pass);
  - the 3-case set's grading guidance is answer-only (facts.py).
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
# isolation: the judge sees only question + ground truth + answer
# ---------------------------------------------------------------------------

def test_judge_payload_keys_minimal():
    msgs = llm_judge.build_messages(_case("original"), "the ceiling")
    payload = msgs[1]["content"]
    import json
    data = json.loads(payload)
    assert set(data.keys()) == {
        "question", "expected_answer", "grading_guidance", "final_answer"}


def test_judge_payload_carries_no_gate_evidence():
    """The answer may mention evidence; the judge payload must not carry
    the reasoning trace/receipts even when the answer contains them."""
    ans = ("the ceiling. REASONING: (|- a b) => (stv 1 0); "
           "DAS_RETRIEVE_OK count=1; SOURCES: git:abc")
    msgs = llm_judge.build_messages(_case("false"), ans)
    data = __import__("json").loads(msgs[1]["content"])
    # the evidence strings ride only inside final_answer, never as fields
    assert set(data.keys()) == {
        "question", "expected_answer", "grading_guidance", "final_answer"}
    assert data["final_answer"] == ans


def test_judge_system_prompt_orders_one_word_verdict():
    assert "CORRECT" in llm_judge.SYSTEM_PROMPT
    assert "INCORRECT" in llm_judge.SYSTEM_PROMPT
    assert "Ignore" in llm_judge.SYSTEM_PROMPT  # ignore style/evidence


# ---------------------------------------------------------------------------
# verdict parsing
# ---------------------------------------------------------------------------

def test_parse_verdict_correct():
    assert llm_judge.parse_verdict("CORRECT") is True
    assert llm_judge.parse_verdict("correct — the answer names the ceiling") is True


def test_parse_verdict_incorrect():
    assert llm_judge.parse_verdict("INCORRECT") is False
    assert llm_judge.parse_verdict("Incorrect: the sky is not visible indoors... wait") is False


def test_parse_verdict_junk_raises():
    for junk in ("", "yes", "the answer seems fine", "PASSED", None):
        try:
            llm_judge.parse_verdict(junk)
            raise AssertionError(f"expected JudgeUnavailable for {junk!r}")
        except llm_judge.JudgeUnavailable:
            pass


def test_parse_verdict_first_token_wins():
    assert llm_judge.parse_verdict("INCORRECT but CORRECT wording") is False
    assert llm_judge.parse_verdict("CORRECT even though INCORRECT appears later") is True


# ---------------------------------------------------------------------------
# API-key resolution precedence
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
# the 3-case set's grading guidance is answer-only (facts.py)
# ---------------------------------------------------------------------------

def test_case_grading_guidance_is_llm_judge_wording():
    for case in TEST_CASES:
        g = case["grading"]
        assert g.startswith("CORRECT iff"), (case["id"], g)
        assert "PASS iff" not in g, (case["id"], g)
        assert "reasoning trace" not in g.lower(), (case["id"], g)


def test_template_names_answer_judge_honestly():
    """v15b: the template no longer claims blanket determinism — format
    gates stay deterministic, answer substance is LLM-judged."""
    with open(os.path.join(HERE, "..", "agent_prompt_template.md"),
              encoding="utf-8") as f:
        t = f.read()
    assert "GRADED BY A MACHINE GATE" in t
    assert "DETERMINISTIC MACHINE GATE" not in t
    assert "exact regexes" in t            # format gates unchanged
    assert "LLM evaluator" in t           # answer substance = judge
    assert "sees only the question" in t   # judge isolation, agent-visible
