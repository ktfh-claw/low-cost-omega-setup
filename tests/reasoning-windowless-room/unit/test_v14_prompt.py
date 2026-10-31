"""v14 prompt tests: full-provenance extraction records (v2 re-pin).

2026-10-26 directive origin: the record discipline (record the receipt's
evidence at write time, copy verbatim at answer time, never rebuild from
memory) moved to the handle lane: every write receipt's `top=<handle>`
rides the `expr <the-exact-expression> top=<handle>` record line, and the
answer block's HANDLES: line is a verbatim copy of those handles.

v2 re-pin (Balázs directive 2026-10-31 11:31 UTC): the minimal
pseudocode prompt carries the same discipline; the pinned wording is
updated to the v2 template's.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _template() -> str:
    with open(os.path.join(HERE, "..", "agent_prompt_template.md"),
              encoding="utf-8") as f:
        return f.read()


def _segment(t: str, start: str, end: str) -> str:
    return t[t.index(start):t.index(end)]


def test_step1_records_the_writes_handle():
    # step 1 records the write receipt's handle — the `top=<handle>` that
    # feeds the HANDLES: line later
    seg = _segment(_template(), "1. EXTRACT", "2. FORMALIZE")
    assert "BRIDGE-PERSIST-OK: verified=<n> top=<handle>" in seg
    assert "expr <the-exact-expression> top=<handle>" in seg
    assert "handle copied VERBATIM from the receipt's `top=`" in seg
    assert "A fact without a fresh receipt is NOT persisted" in seg


def test_step1_handles_vocabulary_binding():
    # urls come from urls.txt; handles come from recorded
    # `expr ... top=` pairs only
    seg = _segment(_template(), "1. EXTRACT", "2. FORMALIZE")
    assert "`<source-url>` is this file's URL from `{{URL_LIST_PATH}}`" in seg
    t = _template()
    assert ("each copied VERBATIM from its recorded `expr <the-exact-expression> "
            "top=<handle>` pair") in t


def test_step5_handles_copy_not_compose():
    # step 5 extends the FACTS copy rule to HANDLES
    t = _template()
    seg = _segment(t, "5. WRITE", "## Answer block format")
    assert "one handle per FACTS expression, same order" in seg
    assert "copied VERBATIM from its recorded `expr <the-exact-expression> top=<handle>` pair" in seg
    assert "A handle is valid ONLY with the exact expression it was issued for" in seg


def test_gate_rules_handles_from_receipts():
    # the format-block rules reject non-verbatim handles
    t = _template()
    seg = _segment(t, "## Answer block format", "## STOP")
    assert "a re-typed, re-ordered, or composed handle FAILs" in seg
    assert "A knowledge case with no FACTS:/HANDLES: lines FAILs" in seg


def test_preamble_records_handle_discipline():
    # the working-state section names the RECORD's line discipline and
    # the no-redo reuse rule
    t = _template()
    assert "append every expr/query/exec/trace line the moment you produce it" in t
    assert "one append per tool result" in t
    assert "Never redo a recorded result" in t
