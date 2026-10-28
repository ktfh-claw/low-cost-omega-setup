"""v14 prompt tests: full-provenance extraction records.

2026-10-26 22:52 UTC directive (Balázs): "following your proposal implement
new version by modifying the agent prompt to save also the urls, git hash,
etc. — whatever is necessary to reconstruct the provenance." Live wr3i/wr3m
evidence: the extraction record stored only `source <filename> git:<sha>`
— no url, no blob, no path — so at answer time the agent had to rebuild
the SOURCES sha/url pairs from memory across wake cycles. That gap
produced: wr3i's one-position sha/url pair shift (P_UNRESOLVED:
URL_MISMATCH), wr3m true/difficult's corrupted sha transcription
(3443aff…b70724 vs the valid …b707242 — one inserted hex digit,
P_UNRESOLVED:COMMIT_NOT_IN_REPO), and wr3m easy's fabricated URL on a
valid sha. The archive-source receipt carried everything, but it was
never recorded and tool results do not survive wake cycles.

v17 re-point (issue #2, spec §8 item 1): the capture step, `source` lines
and the SOURCES: line are REMOVED — the record discipline they enforced
(record the receipt's full evidence at write time, copy verbatim at answer
time, never rebuild from memory) moves to the handle lane: every write
receipt's `top=<handle>` rides the `expr <the-exact-expression>
top=<handle>` record line, and the answer block's HANDLES: line is a
verbatim copy of those handles. Each v14 assertion below is re-pointed at
the v17 equivalent of equal strictness.
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
    # v17 re-point (was: the FULL archive receipt line): step 1 records the
    # write receipt's handle — the `top=<handle>` that survives wake cycles
    # and feeds the HANDLES: line later
    seg = _segment(_template(), "1. **EXTRACT", "2. **FORMALIZE")
    assert "BRIDGE-PERSIST-OK: verified=<n> top=<handle>" in seg
    assert "expr <the-exact-expression> top=<handle>" in seg
    # the rule states WHY: the receipt does not survive wake cycles and
    # the HANDLES: line is copied from these lines later
    assert "receipt itself does not survive wake cycles" in seg
    assert "feeds the `HANDLES:` line" in seg


def test_step1_handles_vocabulary_binding():
    # v17 re-point (was: SOURCES binding): the record binds the answer
    # block the same way it binds queries and FACTS — handles come from
    # recorded `expr … top=<handle>` lines only, urls from urls.txt
    seg = _segment(_template(), "1. **EXTRACT", "2. **FORMALIZE")
    assert "This record is your query and answer vocabulary" in seg
    assert ("an unrecorded expression on a FACTS: line is a false claim "
            "the gate rejects") in seg
    assert "`<source-url>` is this file's URL from `{{URL_LIST_PATH}}`" in seg


def test_step5_handles_copy_not_compose():
    # v17 re-point (was: SOURCES copy-not-compose): step 5 extends the
    # FACTS copy rule to HANDLES, before the write
    seg = _segment(_template(), "5. **WRITE the answer block",
                    "### REQUIRED FORMAT")
    assert ("The `HANDLES:` line is governed by the same copy-not-compose "
            "rule") in seg
    assert "ONE handle per FACTS expression, in the same order" in seg
    assert "never re-type a handle from memory" in seg
    assert "a re-typed or mis-ordered handle fails the case" in seg


def test_gate_rules_handles_from_receipts():
    # v17 re-point (was: SOURCES bullets point at recorded `source`
    # lines): the format-block HANDLES bullets name the receipts the
    # agent holds as the only legitimate origin of handles
    t = _template()
    seg = _segment(t, "`HANDLES:` line carrying",
                   "- If the question cannot be answered")
    assert "ONE atom handle for every FACTS: expression, in the same order" in seg
    assert "copied character-for-character from a receipt you hold" in seg
    assert "the write receipt's `top=`" in seg
    assert "`das-retrieve` receipt's `results=` handles" in seg
    assert "never re-typed, never re-ordered, never composed" in seg
    assert ("The gate cross-checks every handle against its aligned FACTS "
            "expression") in seg
    assert "is fabricated" in seg


def test_preamble_records_handle_discipline():
    # v17 re-point (was: preamble names provenance receipts): the
    # working-memory preamble names the handle discipline among the
    # things recorded immediately, and reuse covers urls/handles
    t = _template()
    assert "append every expression, query, and `exec` line" in t
    assert "every recorded `expr` line carries its write's handle (`top=<handle>`)" in t
    assert "reuse the recorded url/handle/expression" in t
