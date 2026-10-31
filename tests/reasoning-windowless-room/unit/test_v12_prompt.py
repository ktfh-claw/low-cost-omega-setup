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
    # v2 re-pin (2026-10-31): the format-block FACTS line names the
    # verbatim-copy rule from the RECORD
    t = _template()
    assert ("FACTS: <the exact expr expressions copied VERBATIM from the "
            "RECORD, semicolon-separated>") in t
    assert "no paraphrase, no unwrapping" in t


def test_step5_facts_copy_before_write():
    # v2 re-pin: step 5 carries the copy-not-compose rule with the
    # wrapper-preservation discipline, before the close-out moves
    t = _template()
    seg = _segment(t, "5. WRITE", "## Answer block format")
    assert ("copy the exact `expr` expressions this answer used, "
            "character-for-character from the RECORD") in seg
    assert "type wrappers such as `(Concept \"...\")` inside a stored expression are PART of the expression" in seg
    assert "no paraphrase, no unwrapping" in seg
    # copy rule before the close-out moves
    assert seg.index("character-for-character") < seg.index("four moves in this order")
    # the blocking condition rides the format-block rules
    assert "An expression not in the RECORD FAILs" in t


def test_gate_rules_facts_anti_gloss():
    # v2 re-pin: the format-block rules reject unrecorded expressions and
    # non-verbatim handles
    t = _template()
    seg = _segment(t, "## Answer block format", "## STOP")
    assert "An expression not in the RECORD FAILs" in seg
    assert "a re-typed, re-ordered, or composed handle FAILs" in seg
    assert "A knowledge case with no FACTS:/HANDLES: lines FAILs" in seg


def test_step1_answer_vocabulary():
    # v2 re-pin: step 2 binds the QUERY to the record's exact spellings;
    # the FACTS binding rides step 5's copy rule
    t = _template()
    seg = _segment(t, "2. FORMALIZE", "3. RETRIEVE")
    assert "exact predicate names and literal spellings from the RECORD" in seg
    assert "keep stored arity/shape/direction" in seg
