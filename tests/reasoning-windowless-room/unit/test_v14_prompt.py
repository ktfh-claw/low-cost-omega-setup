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
valid sha (a fetchai-benchmark raw URL that exists nowhere in the
archive index). The archive-source receipt — ARCHIVE-OK git:<sha>
sha256:<blob> path=<path> — carried everything, but it was never
recorded and tool results do not survive wake cycles.

v14 is prompt-side only: the record's `source` line captures the FULL
provenance receipt including the raw-github URL, and the SOURCES: line
of the answer block becomes a verbatim COPY of recorded pairs — the
same copy-not-compose discipline v12 applied to FACTS:. Grading code is
unchanged (parse_facts_index skips non-expression `source` lines with
any annotation shape; parse_citations reads the answers block only).
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _template() -> str:
    with open(os.path.join(HERE, "..", "agent_prompt_template.md"),
              encoding="utf-8") as f:
        return f.read()


def _segment(t: str, start: str, end: str) -> str:
    return t[t.index(start):t.index(end)]


def test_step1_records_full_provenance():
    # step 1 appends the FULL receipt line — sha, blob, path AND url
    seg = _segment(_template(), "1. **EXTRACT", "2. **FORMALIZE")
    assert ("source <filename> git:<sha> sha256:<blob> path=<repo path> "
            "<raw-github-url>") in seg
    # the rule states WHY: the receipt does not survive wake cycles and
    # the SOURCES line is copied from these lines later
    assert "receipt itself does not survive wake cycles" in seg
    assert "SOURCES: line" in seg


def test_step1_sources_vocabulary_binding():
    # the record binds SOURCES citations the same way it binds queries
    # and FACTS — pairs come from recorded `source` lines only
    seg = _segment(_template(), "1. **EXTRACT", "2. **FORMALIZE")
    assert "query, answer AND SOURCES vocabulary" in seg
    assert ("cite a `git:<sha> <url>` pair ONLY as it appears in a "
            "recorded `source` line") in seg
    assert "fabricated provenance" in seg


def test_step5_sources_copy_not_compose():
    # step 5 extends the FACTS copy rule to SOURCES, before the write
    seg = _segment(_template(), "5. **WRITE the answer block",
                   "### REQUIRED FORMAT")
    assert ("The `SOURCES:` line is governed by the same copy-not-compose "
            "rule") in seg
    assert "never re-type a sha from memory" in seg
    assert "never guess a url" in seg
    assert "wr3m lessons" in seg


def test_gate_rules_sources_from_record():
    # the format-block SOURCES bullets point at the record's source
    # lines as the only legitimate origin of pairs
    t = _template()
    seg = _segment(t, "`SOURCES:` line citing",
                   "- If the question cannot be answered")
    assert "copied from the `source` lines of your extraction record" in seg
    assert "EXACTLY as it sits in your extraction record" in seg
    assert "never re-type a sha by hand" in seg
    assert "wr3i lesson" in seg


def test_preamble_records_provenance():
    # the working-memory preamble names provenance receipts among the
    # things recorded immediately, and reuse covers urls
    t = _template()
    assert ("append every provenance receipt, expression, query, and "
            "`exec` line") in t
    assert "reuse the recorded sha/url/expression" in t
