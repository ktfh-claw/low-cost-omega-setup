"""v12 prompt tests: FACTS-line verbatim-copy discipline.

2026-10-26 14:39 UTC directive (wr3k close-out). Live wr3k evidence:
case 2 (uncertainty) delivered a substantively correct answer with clean
Q/R/P lanes, but its FACTS: line carried two answer-time GLOSSES —
(Inheritance (Concept "ceiling") (Concept "upper-interior-surface")) and
(Inheritance (Concept "windowless-room") (Concept
"space-bounded-by-walls-ceiling-floor")) — paraphrases of recorded facts
composed in new words while writing the final answer. Both expressions
appear ONLY in answers.md, never as `expr` lines in the extraction record
(every recorded expr WAS persisted: index_absent_count=0), so
E_FACTS_NOT_IN_INDEX fired and failed the case.

v12 is prompt-side: the FACTS: line is a VERBATIM COPY of recorded `expr`
lines, not a composition. The template now states this in step 1 (the
record is the query AND answer vocabulary), in step 5 (copy-before-write
rule with the wr3k lesson), and in the format-block gate rules. Grading
code is unchanged — the gate already checks FACTS against the record.

v17 re-point (issue #2, spec §8 item 1): the FACTS copy rules KEPT
verbatim; the SOURCES half of the step-1 vocabulary binding is dropped
with the SOURCES: line — the record binds "query and answer vocabulary"
only. All other v12 assertions survive the slim prompt unchanged.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _template() -> str:
    with open(os.path.join(HERE, "..", "agent_prompt_template.md"),
              encoding="utf-8") as f:
        return f.read()


def _segment(t: str, start: str, end: str) -> str:
    return t[t.index(start):t.index(end)]


def test_facts_line_verbatim_copy_contract():
    # the format-block FACTS line names the verbatim-copy rule and the
    # blocking condition it prevents
    t = _template()
    assert ("FACTS: <the exact `expr` expressions copied VERBATIM from your "
            "extraction record") in t
    assert "no new or paraphrased expressions" in t


def test_step5_facts_copy_before_write():
    # step 5 carries the copy-not-compose rule BEFORE the write order,
    # names E_FACTS_NOT_IN_INDEX and the wr3k lesson, and states the
    # either-persist-first-or-omit resolution
    t = _template()
    seg = _segment(t, "5. **WRITE the answer block", "### REQUIRED FORMAT")
    assert "copy the exact `expr` expressions this answer used, character-for-character VERBATIM" in seg
    assert "E_FACTS_NOT_IN_INDEX" in seg
    assert "wr3k lesson" in seg
    assert "answer-time glosses" in seg
    # copy rule before the write order (iterate #4 re-point: the close-out
    # tail now renders the append as move (3) of the binding sequence)
    assert seg.index("VERBATIM") < seg.index("append the block")
    assert "either persist it first" in seg


def test_gate_rules_facts_anti_gloss():
    # the gate-rules FACTS bullet explains WHY unrecorded expressions fail
    # (false claim even when the answer is correct) and where plain-language
    # phrasing belongs (FINAL ANSWER text only)
    t = _template()
    seg = _segment(t, "FACTS:` line quoting", "- `REASONING:")
    assert "VERBATIM COPY" in seg
    assert "an expression that was never recorded is a false claim" in seg
    assert "put the plain-language version only in the FINAL ANSWER text" in seg


def test_step1_answer_vocabulary():
    # step 1 now binds BOTH the query and the FACTS line to the record's
    # exact spellings — the gloss trap is answer-side, not query-side only
    t = _template()
    seg = _segment(t, "1. **EXTRACT", "2. **FORMALIZE")
    # v17: the binding drops its SOURCES half (the SOURCES: line is
    # removed); the record binds the query and the FACTS line, and every
    # recorded `expr` line carries its write's handle for the HANDLES:
    # line
    assert "This record is your query and answer vocabulary" in seg
    assert "an unrecorded expression on a FACTS: line is a false claim" in seg
