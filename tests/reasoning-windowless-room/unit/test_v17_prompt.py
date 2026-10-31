"""v17 prompt tests (v2 re-pin, 2026-10-31): the minimal pseudocode prompt.

Balázs directive 2026-10-31 11:31 UTC: prompt-only restructure — minimal,
formal, pseudocode-style, exact tool references. The agent remains
UNAWARE of provenance (no archive/SOURCES/git/sha256/provenance
vocabulary), the v3 add-atom form + `top=<handle>` record rule + HANDLES
line survive, and the close-out/STOP discipline survives as bare rules.
Lesson narratives (wr3k/wr3p/wr3q/wr3r/o) are GONE from the template by
design — their substance is pinned here as behavior rules, not stories.
"""

import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import run_benchmark


TEMPLATE_PATH = os.path.join(HERE, "..", "agent_prompt_template.md")


def _template() -> str:
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# negative greps: removed mechanics leave no vocabulary behind
# ---------------------------------------------------------------------------

def test_template_has_no_archive_vocabulary():
    t = _template()
    assert "archive" not in t.lower()


def test_template_has_no_sources_line():
    t = _template()
    assert "SOURCES" not in t


def test_template_has_no_git_or_sha256_tokens():
    t = _template()
    assert "git:" not in t
    assert "sha256" not in t


def test_template_has_no_provenance_word():
    t = _template()
    assert "provenance" not in t.lower()


def test_template_has_no_lesson_narratives():
    # v2 removes the wr3x story references — rules survive, stories do not
    t = _template()
    for token in ("wr3k lesson", "wr3p lesson", "wr3q lesson",
                  "wr3r lesson", "wr3o lesson", "lesson"):
        assert token not in t, token


# ---------------------------------------------------------------------------
# positive greps: the v2 contract is present
# ---------------------------------------------------------------------------

def test_required_format_has_handles_line_between_facts_and_reasoning():
    fmt = _template()[_template().index("## Answer block format"):]
    i_facts = fmt.index("FACTS:")
    i_handles = fmt.index("HANDLES:")
    i_reasoning = fmt.index("REASONING:")
    assert i_facts < i_handles < i_reasoning, \
        "HANDLES must sit between FACTS and REASONING"
    assert ("HANDLES: <the atom handles of the FACTS expressions, in the "
            "same order") in fmt


def test_step1_record_line_carries_top_handle():
    seg = _template()
    seg = seg[seg.index("1. EXTRACT"):seg.index("2. FORMALIZE")]
    assert "expr <the-exact-expression> top=<handle>" in seg
    assert "BRIDGE-PERSIST-OK: verified=<n> top=<handle>" in seg
    assert "handle copied VERBATIM from the receipt's `top=`" in seg
    assert "A fact without a fresh receipt is NOT persisted" in seg


def test_step1_v3_add_atom_form():
    seg = _template()
    seg = seg[seg.index("1. EXTRACT"):seg.index("2. FORMALIZE")]
    assert ('(metta "(add-atom &persistent (<expression>) \\"<source-url>\\" '
            '(stv 0.9 0.8))")') in seg
    assert "`<source-url>` is this file's URL from `{{URL_LIST_PATH}}`" in seg


def test_url_list_stays_the_reference_vocabulary():
    t = _template()
    assert "read `{{URL_LIST_PATH}}` ONCE" in t
    assert t.count("{{URL_LIST_PATH}}") >= 3


def test_ledger_stop_final_answer_retained():
    t = _template()
    assert "LEDGER: step <1-5> | done: <completed items> | next: <ONE literal tool call>" in t
    assert "## STOP" in t
    assert "FINAL ANSWER ({{CASE_ID}}): <answer>" in t


def test_placeholders_all_present():
    t = _template()
    for ph in ("{{RUN_ID}}", "{{CASE_ID}}", "{{QUESTION}}",
               "{{URL_LIST_PATH}}", "{{ANSWERS_PATH}}", "{{FACTS_INDEX_PATH}}"):
        assert ph in t, ph


def test_template_is_minimal():
    # the directive's size target: v1 was ~2600 words; v2 must stay
    # well under half of it
    words = len(_template().split())
    assert words <= 1200, f"template grew to {words} words"


# ---------------------------------------------------------------------------
# render: every case prompt renders with the v2 contract
# ---------------------------------------------------------------------------

def _render(case) -> str:
    args = SimpleNamespace(run_id="t-run", case=case["id"], dry_run=False,
                           memory_volume="/fake/vol", trim_history=True,
                           timeout_minutes=75)
    return run_benchmark._render_case_prompt(args, case)


def _banned(rendered: str) -> None:
    assert "SOURCES" not in rendered
    assert "archive" not in rendered.lower()
    assert "git:" not in rendered
    assert "provenance" not in rendered.lower()
    assert "sha256" not in rendered
    assert "lesson" not in rendered


def test_rendered_prompt_carries_v17_contract_for_every_case():
    cases = run_benchmark._facts_mod().TEST_CASES
    assert cases
    for case in cases:
        rendered = _render(case)
        assert "{{" not in rendered, \
            f"unrendered placeholder survives in case {case['id']}"
        assert ("HANDLES: <the atom handles of the FACTS expressions, in the "
                "same order") in rendered, case["id"]
        assert ('(metta "(add-atom &persistent (<expression>) \\"<source-url>\\" '
                '(stv 0.9 0.8))")') in rendered, case["id"]
        assert "expr <the-exact-expression> top=<handle>" in rendered, case["id"]
        _banned(rendered)


# ---------------------------------------------------------------------------
# wr3o substance (re-pinned as rules): bracketed annotations in
# REASONING are prose; recorded expressions are copied with wrappers
# intact; handle-expression pairs travel together
# ---------------------------------------------------------------------------

def test_step4_bans_bracket_annotations_in_reasoning():
    seg = _template()
    seg = seg[seg.index("4. REASON"):seg.index("5. WRITE")]
    assert "no words, no bracketed annotations anywhere" in seg
    assert "Only parenthesized s-expressions" in seg
    assert "its `(stv ...)` output stays on exec lines, never on the question clause" in seg


def test_step5_facts_wrapper_preservation():
    seg = _template()
    seg = seg[seg.index("5. WRITE"):seg.index("## Answer block format")]
    assert ("type wrappers such as `(Concept \"...\")` inside a stored "
            "expression are PART of the expression") in seg
    assert "no paraphrase, no unwrapping" in seg


def test_step5_handles_pair_copy_rule():
    seg = _template()
    seg = seg[seg.index("5. WRITE"):seg.index("## Answer block format")]
    assert "A handle is valid ONLY with the exact expression it was issued for" in seg
    assert "copied VERBATIM from its recorded `expr <the-exact-expression> top=<handle>` pair" in seg


# ---------------------------------------------------------------------------
# wr3p substance (re-pinned as rules): the trace opens with the bare
# executed question clause — no stv pair, no wrapper
# ---------------------------------------------------------------------------

def test_step4_unsolvable_trace_opens_with_bare_question_clause():
    seg = _template()
    seg = seg[seg.index("4. REASON"):seg.index("5. WRITE")]
    assert "the question clause EXACTLY as executed" in seg
    assert "character-for-character identical to your QUERY: line" in seg
    assert "no `(stv ...)` pair attached, no wrapping parentheses" in seg
    assert "the bare question clause followed by the reverse-direction probe clause(s)" in seg


def test_gate_rules_block_format_discipline():
    fmt = _template()
    fmt = fmt[fmt.index("## Answer block format"):]
    # first trace step is the bare QUERY clause
    assert "the FIRST step is the bare QUERY clause — never wrapped, never with an attached `(stv ...)`" in fmt
    # prose/brackets/stv rules
    assert "Prose or bracketed annotations anywhere in REASONING FAIL" in fmt
    assert "No interpreter `(stv ...)` outputs FAIL" in fmt
    # facts/handles pairing
    assert "An expression not in the RECORD FAILs" in fmt
    assert "a re-typed, re-ordered, or composed handle FAILs" in fmt
    # unanswerable rule
    assert "Do NOT fabricate" in fmt


# ---------------------------------------------------------------------------
# wr3q/wr3r substance (re-pinned as rules): close-out ordering and
# one-block idempotency; truthful terminal pin only after the append
# ---------------------------------------------------------------------------

def test_ledger_closeout_pins_intermediate_before_terminal_after():
    t = _template()
    assert ("LEDGER: step 5 | done: terminal close-out composed | "
            "next: append-file {{ANSWERS_PATH}} with the answer block "
            "once, then pin the done line") in t
    assert ("LEDGER: step 5 | done: answer block written | next: none — "
            "case complete, idle silently") in t
    seg = t[t.index("5. WRITE"):t.index("## Answer block format")]
    assert "NEVER pin this line before the block exists" in seg
    assert "after the append succeeds" in seg


def test_ledger_existing_block_pins_and_idles():
    t = _template()
    seg = t[t.index("5. WRITE"):t.index("## Answer block format")]
    assert "existing `### CASE {{CASE_ID}}` block" in seg
    assert "already answered" in seg
    assert "NEVER append a second block" in seg


def test_rendered_prompt_carries_closeout_discipline_for_every_case():
    cases = run_benchmark._facts_mod().TEST_CASES
    assert cases
    for case in cases:
        rendered = _render(case)
        assert "done: terminal close-out composed" in rendered, case["id"]
        assert ("LEDGER: step 5 | done: answer block written | next: none — "
                "case complete, idle silently") in rendered, case["id"]
        assert "NEVER pin this line before the block exists" in rendered, case["id"]
        assert "NEVER append a second block" in rendered, case["id"]
        assert "existing `### CASE " + case["id"] + "` block" in rendered, case["id"]
        _banned(rendered)
