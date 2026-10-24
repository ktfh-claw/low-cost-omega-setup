"""v6 prompt contract: campaign-style fixed pipeline, no open-ended study.

2026-10-24 19:50 UTC directive (wr3f iteration): both next-lever
recommendations applied — campaign-style prompt structure AND the
reasoning-trace + answer-write steps moved to the top of the task list
(deliverable-first framing) — plus the open-ended study/research step
REMOVED entirely: extraction is ONE bounded pass over the background
sources. These tests pin the v6 template invariants so the
convergence-ordering fix cannot silently regress.
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
    steps = [
        "1. **EXTRACT",
        "2. **FORMALIZE",
        "3. **RETRIEVE",
        "4. **COMPOSE THE REASONING TRACE",
        "5. **WRITE the answer block",
    ]
    pos = [t.index(s) for s in steps]  # raises if any step is missing
    assert pos == sorted(pos), "task-list steps out of order or missing"


def test_deliverable_first():
    t = _template()
    assert "THE DELIVERABLE" in t
    # the deliverable section precedes the task list
    assert t.index("THE DELIVERABLE") < t.index("TASK LIST")
    # the reasoning trace is deliverable #1, the answer block #2
    assert t.index("The MeTTa reasoning trace") < t.index("The answer block")
    # fixed-pipeline framing is explicit
    assert "fixed pipeline" in t


def test_no_open_ended_study_step():
    t = _template()
    # v5 open-ended phrasings must be gone
    assert "Ingest + persist (only if needed" not in t
    assert "Check what you already have." not in t
    assert "the sources you will actually use" not in t
    # explicit no-research rule present
    assert "NO open-ended study or research step" in t
    # single-pass, no-re-read rules present
    assert "read it ONCE" in t
    assert "may NOT open any background file again" in t
    assert "no summarizing, no analysis, no further study" in t


def test_record_reuse_skip_rule():
    t = _template()
    # already-recorded sources are skipped deterministically (no re-read,
    # no re-archive) — cross-case carry-over without a relevance decision
    assert "already lists this source with its `git:<sha>`, SKIP it" in t


def test_campaign_anti_loop_rules_present():
    t = _template()
    assert "Campaign rules" in t
    assert "next undone step of the TASK LIST" in t
    assert "never repeat a completed step" in t
    assert 'never "study more first"' in t


def test_answer_block_contract_unchanged():
    t = _template()
    for line in (
        "QUERY: <the exact metta pattern you executed>",
        "DAS_RETRIEVE_OK untrusted=true count=<n> truncated=... results=[...]",
        "FACTS: <the predicate expressions from your extraction record that this answer used, semicolon-separated>",
        "REASONING: <the MeTTa reasoning trace: question clause; fact step(s); conclusion clause — semicolon-separated s-expressions, NOT prose>",
        "FINAL ANSWER ({{CASE_ID}}): <answer>",
        "SOURCES: git:<40-hex-sha> <source-url> [git:<40-hex-sha> <source-url> ...]",
    ):
        assert line in t, line[:40]


def test_trace_deliverable_contract():
    t = _template()
    # step-4 trace shape matches the R-gate parser contract
    assert "the question clause (the exact QUERY you executed)" in t
    assert "copied VERBATIM from your extraction record" in t
    assert "every quoted literal in it must come from your recorded vocabulary" in t
    # trace persisted to the extraction record (working memory)
    assert "starting with `trace:`" in t
    # unsolvable-case trace form (shape kept, grounding exempt)
    assert "the question clause followed by the reverse-direction probe clause(s)" in t


def test_placeholders_present():
    t = _template()
    for ph in ("{{RUN_ID}}", "{{CASE_ID}}", "{{QUESTION}}",
               "{{URL_LIST_PATH}}", "{{ANSWERS_PATH}}", "{{FACTS_INDEX_PATH}}"):
        assert ph in t, ph
