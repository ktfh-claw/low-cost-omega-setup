"""v6 prompt contract (v2 re-pin, 2026-10-31): fixed pipeline, no
open-ended study.

Balázs directive 2026-10-31 11:31 UTC: minimal pseudocode prompt. The
substance of every v6 invariant survives the rewrite; the pinned
wording is updated to the v2 template's.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

TEMPLATE_PATH = os.path.join(HERE, "..", "agent_prompt_template.md")


def _template() -> str:
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


def test_task_list_fixed_pipeline_order():
    t = _template()
    steps = ["1. EXTRACT", "2. FORMALIZE", "3. RETRIEVE", "4. REASON",
             "5. WRITE"]
    pos = [t.index(s) for s in steps]  # raises if any step is missing
    assert pos == sorted(pos), "procedure steps out of order or missing"


def test_deliverable_first():
    # the reasoning trace is deliverable 1, the answer block deliverable 2,
    # named in order inside the procedure
    t = _template()
    assert "(deliverable 1)" in t
    assert "(deliverable 2)" in t
    assert t.index("(deliverable 1)") < t.index("(deliverable 2)")
    # fixed-pipeline framing is explicit
    assert "five steps, each once, in order" in t


def test_no_open_ended_study_step():
    t = _template()
    # v5 open-ended phrasings must be gone
    assert "Ingest + persist (only if needed" not in t
    assert "Check what you already have." not in t
    assert "the sources you will actually use" not in t
    # explicit no-research rule present
    assert "no research, no extra study, no messages" in t
    # single-pass, no-re-read rules present
    assert "read-file ONCE" in t
    assert "Never open that file again" in t


def test_record_reuse_skip_rule():
    # already-recorded sources are skipped deterministically
    t = _template()
    assert "skip files already recorded in the RECORD" in t


def test_campaign_anti_loop_rules_present():
    # v2: the anti-loop rules ride the procedure + working-state rules
    t = _template()
    assert "Never issue the same query more than twice" in t
    assert "issue the `next:` call immediately" in t
    assert "Never redo a recorded result" in t


def test_answer_block_contract_unchanged():
    # the block lines are pinned verbatim to the v2 template
    t = _template()
    for line in (
        "QUERY: <the exact metta pattern you executed>",
        "DAS_RETRIEVE_OK untrusted=true count=<n> truncated=... results=[...]",
        "FACTS: <the exact expr expressions copied VERBATIM from the RECORD, semicolon-separated>",
        "HANDLES: <the atom handles of the FACTS expressions, in the same order, space-separated, each copied VERBATIM from its expr … top= pair>",
        "REASONING: <the executed MeTTa trace: question clause; fact clauses; derivation steps with interpreter (stv ...) outputs — s-expressions only, no prose>",
        "FINAL ANSWER ({{CASE_ID}}): <answer>",
    ):
        assert line in t, line[:40]


def test_trace_deliverable_contract():
    # step-4 trace shape matches the R-gate parser contract
    t = _template()
    assert "the question clause EXACTLY as executed" in t
    assert "character-for-character identical to your QUERY: line" in t
    assert "STRICTLY 2-argument" in t
    assert "feed the derived output of one call in as a premise of the next call" in t
    assert "exec <metta-call> => <interpreter-output-with-stv>" in t
    # trace persisted to the record (working memory)
    assert "starting `trace:`" in t
    # unsolvable-case trace form (shape kept, grounding exempt)
    assert "the bare question clause followed by the reverse-direction probe clause(s)" in t


def test_step5_deliverable_first_write():
    # the file write is an ordered close-out move, before the terminal pin
    t = _template()
    step5 = t.index("5. WRITE")
    seg = t[step5:t.index("## Answer block format")]
    assert "four moves in this order" in seg
    assert "append-file the block" in seg
    # terminal pin only after the append succeeded
    assert "after the append succeeds" in seg


def test_stop_rule_idle_discipline():
    # STOP forbids sends/verification/rewrites on later wakes
    t = _template()
    stop = t[t.index("## STOP"):]
    assert "no sends" in stop
    assert "does NOTHING" in stop
    assert "Idle silently" in stop


def test_placeholders_present():
    t = _template()
    for ph in ("{{RUN_ID}}", "{{CASE_ID}}", "{{QUESTION}}",
               "{{URL_LIST_PATH}}", "{{ANSWERS_PATH}}", "{{FACTS_INDEX_PATH}}"):
        assert ph in t, ph
