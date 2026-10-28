"""v17 prompt tests: the slim transparent-provenance prompt (T020).

v17 (issue #2, spec §2.7/§8 item 1): the agent is UNAWARE of provenance.
The standalone source-capture step, its ARCHIVE-OK receipt, the `source …`
record lines, and the SOURCES: answer line are gone from the template; in
their place the agent carries exactly three obligations: pass the source
URL in the v3 add-atom call, record `expr <expression> top=<handle>` lines
(the handle copied VERBATIM from the write receipt — it must survive wake
cycles), and copy handles into the new HANDLES: line (between FACTS and
REASONING, aligned BY ORDER with the FACTS expressions, each copied from
the write receipt's `top=` or a das-retrieve receipt's `results=` handles).
Everything else (hashing, ledger commits, verification) is invisible
machinery — the words themselves must not appear.

These tests pin the slim invariants so the v4 design cannot silently
regress: no removed-mechanics vocabulary survives in the template, the
v3 call form + `top=<handle>` record rule + HANDLES line are present,
urls.txt stays the reference vocabulary (D5), the ledger/anti-loop/STOP
contract is intact, and every case prompt renders with the slim contract
(T020's test hook: "dry-run of `full` renders the slim prompt with the
HANDLES line").
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


def _segment(t: str, start: str, end: str) -> str:
    return t[t.index(start):t.index(end)]


# ---------------------------------------------------------------------------
# negative greps: removed mechanics leave no vocabulary behind
# ---------------------------------------------------------------------------

def test_template_has_no_archive_vocabulary():
    # the standalone capture step is gone — no archive word in any case
    t = _template()
    assert "archive" not in t.lower()


def test_template_has_no_sources_line():
    # the SOURCES: answer line is removed with the citation-pair rules
    t = _template()
    assert "SOURCES" not in t


def test_template_has_no_git_or_sha256_tokens():
    # git shas and content hashes are invisible machinery — never agent work
    t = _template()
    assert "git:" not in t
    assert "sha256" not in t


def test_template_has_no_provenance_word():
    # the agent is unaware of provenance — the word itself must not appear
    t = _template()
    assert "provenance" not in t.lower()


# ---------------------------------------------------------------------------
# positive greps: the v17 contract is present
# ---------------------------------------------------------------------------

def test_required_format_has_handles_line_between_facts_and_reasoning():
    # §2.7 answers-block order: QUERY / DAS_RETRIEVE_OK / FACTS / HANDLES /
    # REASONING / FINAL ANSWER — HANDLES sits between FACTS and REASONING
    fmt = _segment(_template(), "### REQUIRED FORMAT", "Gate rules for the block")
    i_facts = fmt.index("FACTS:")
    i_handles = fmt.index("HANDLES:")
    i_reasoning = fmt.index("REASONING:")
    assert i_facts < i_handles < i_reasoning, \
        "HANDLES must sit between FACTS and REASONING"
    assert ("HANDLES: <the atom handles of the FACTS expressions, in the same "
            "order") in fmt


def test_step1_record_line_carries_top_handle():
    # `expr <the-exact-expression> top=<handle>` replaces `expr … verified=<n>`
    # — the handle is copied VERBATIM from the receipt and survives wake
    # cycles as the HANDLES: line's carrier
    seg = _segment(_template(), "1. **EXTRACT", "2. **FORMALIZE")
    assert "expr <the-exact-expression> top=<handle>" in seg
    assert "BRIDGE-PERSIST-OK: verified=<n> top=<handle>" in seg
    assert "copied VERBATIM from the receipt's `top=` field" in seg
    assert "receipt itself does not survive wake cycles" in seg
    assert "feeds the `HANDLES:` line" in seg


def test_step1_v3_add_atom_form():
    # v3 grammar: the source URL rides the add-atom call (D5 — URL refs
    # from the urls.txt list); write success is ONLY the top=-carrying
    # receipt
    seg = _segment(_template(), "1. **EXTRACT", "2. **FORMALIZE")
    assert ('(metta "(add-atom &persistent (<expression>) \\"<source-url>\\" '
            '(stv 0.9 0.8))")') in seg
    assert "`<source-url>` is this file's URL from `{{URL_LIST_PATH}}`" in seg


def test_url_list_stays_the_reference_vocabulary():
    # urls.txt remains the agent's source-url vocabulary (D5)
    t = _template()
    assert "read `{{URL_LIST_PATH}}` ONCE" in t
    assert t.count("{{URL_LIST_PATH}}") >= 3


def test_ledger_stop_final_answer_retained():
    # the surviving discipline sections are untouched by the slim
    t = _template()
    assert "## PINNED LEDGER — required, mechanical" in t
    assert "LEDGER: step <1-5> | done: <completed items> | next: <ONE literal tool call>" in t
    assert "## STOP rule" in t
    assert "FINAL ANSWER ({{CASE_ID}}): <answer>" in t


def test_placeholders_all_present():
    # run_benchmark.py:710-717 substitutes exactly these six
    t = _template()
    for ph in ("{{RUN_ID}}", "{{CASE_ID}}", "{{QUESTION}}",
               "{{URL_LIST_PATH}}", "{{ANSWERS_PATH}}", "{{FACTS_INDEX_PATH}}"):
        assert ph in t, ph


# ---------------------------------------------------------------------------
# render: every case prompt renders slim, with the HANDLES line
# ---------------------------------------------------------------------------

def _render(case) -> str:
    args = SimpleNamespace(run_id="t-run", case=case["id"], dry_run=False,
                           memory_volume="/fake/vol", trim_history=True,
                           timeout_minutes=75)
    return run_benchmark._render_case_prompt(args, case)


def test_rendered_prompt_carries_v17_contract_for_every_case():
    # T020's hook: a dry-run of `full` renders the slim prompt with the
    # HANDLES line and the v3 add-atom form, for every case in TEST_CASES
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
        assert "SOURCES" not in rendered, case["id"]
        assert "archive" not in rendered.lower(), case["id"]
        assert "git:" not in rendered, case["id"]
        assert "provenance" not in rendered.lower(), case["id"]


# ---------------------------------------------------------------------------
# wr3o lessons (2026-10-28 live run): two agent-discipline failures the
# slim prompt must prevent at the source — R_NOT_METTA from a bracketed
# probe annotation in REASONING (unsolvable) and the E_FACTS_NOT_IN_INDEX +
# H_MISMATCH pair from unwrapping a recorded expression while keeping its
# receipt handle (false case)
# ---------------------------------------------------------------------------

def test_step4_bans_bracket_annotations_in_reasoning():
    # unsolvable case: a `[reverse-direction probe count=0]` bracket note
    # inside REASONING is prose under the strict gate (R_NOT_METTA)
    seg = _segment(_template(), "4. **EXECUTE", "5. **WRITE")
    assert "NEVER annotate anything inside REASONING" in seg
    assert "bracketed notes" in seg
    assert "`R_NOT_METTA`" in seg
    # the zero-count evidence rides in the block's receipt line, not REASONING
    assert "DAS_RETRIEVE_OK ... count=0" in seg
    assert "never a note in REASONING" in seg


def test_gate_rule_reasoning_brackets_are_prose():
    # the block's REASONING gate rule carries the same ban
    fmt = _segment(_template(), "### REQUIRED FORMAT", "## Write artifacts")
    assert "Bracketed annotations are prose too" in fmt


def test_step5_facts_wrapper_preservation():
    # false case: unwrapping `(Concept "...")` type wrappers from a recorded
    # expression rewrites it — the rewritten form was never recorded and the
    # receipt handle paired with it belongs to the original form
    seg = _segment(_template(), "5. **WRITE", "### REQUIRED FORMAT")
    assert ("type wrappers such as `(Concept \"...\")` inside a stored "
            "expression are PART of the expression") in seg
    assert "Unwrapping, simplifying, or re-formatting a recorded expression rewrites it" in seg
    assert "`E_FACTS_NOT_IN_INDEX`" in seg
    assert "`H_MISMATCH`" in seg


def test_step5_handles_pair_copy_rule():
    # the recorded `expr <expression> top=<handle>` line pairs an expression
    # with its handle — the pair must survive to the block intact
    seg = _segment(_template(), "5. **WRITE", "### REQUIRED FORMAT")
    assert "A handle is valid ONLY with the exact expression it was issued for" in seg
    assert "copy the PAIR intact" in seg


def test_gate_rules_facts_and_handles_pair_discipline():
    fmt = _segment(_template(), "### REQUIRED FORMAT", "## Write artifacts")
    # FACTS bullet: the recorded form is the claim — wrappers and all
    assert "The recorded form is the claim — wrappers and all" in fmt
    # HANDLES bullet: the handle travels together with its expression
    assert "Copy each handle TOGETHER with its expression" in fmt


def test_rendered_prompt_carries_wr3o_lessons_for_every_case():
    # the discipline additions render for every case and introduce no banned
    # vocabulary
    cases = run_benchmark._facts_mod().TEST_CASES
    assert cases
    for case in cases:
        rendered = _render(case)
        assert "NEVER annotate anything inside REASONING" in rendered, case["id"]
        assert "copy the PAIR intact" in rendered, case["id"]
        assert ("type wrappers such as `(Concept \"...\")`" in rendered), case["id"]
        assert "provenance" not in rendered.lower(), case["id"]
        assert "archive" not in rendered.lower(), case["id"]
        assert "SOURCES" not in rendered, case["id"]
        assert "git:" not in rendered, case["id"]
        assert "sha256" not in rendered, case["id"]
