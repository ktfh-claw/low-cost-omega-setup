"""das-read skill-description tests: the issue-2 atom-handles clause (T029).

Spec §8 item 10 (addendum 2026-10-27): the das-retrieve skill description
in deploy/omega/plugins/das-read/das-read.metta gains an explicit clause
that the DAS_RETRIEVE_OK receipt's results payload carries, for every
answer, the atom handles of the matched stored links, and that those
handles may be quoted from the receipt. Description-only — NO
engine/proxy/adapter change.

The clause must stay in generic vocabulary: the benchmark agent remains
unaware of provenance mechanics and must still extract its own
answer-block predicates, so the description string must carry none of
the benchmark answer-block tokens ("HANDLES:", "top=") and none of the
provenance-mechanics tokens ("provenance", "sha256", "git", "ledger",
"archive", "SOURCES") — handles appear as plain stored-atom identifiers.

Structure invariants pinned alongside the clause: the remove-then-add
single-definition registration, the is_enabled gate, and the clause
rebind to the mounted adapter must survive the edit; the preflight anchor
"WHY: DAS is your persistent knowledge store" (run_benchmark.py
skill_description_upgraded check) must remain exactly once; and the
validate_driver PROBE-4 comment must document the handles clause.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))

METTA_PATH = os.path.join(HERE, "..", "..", "..", "deploy", "omega",
                          "plugins", "das-read", "das-read.metta")
DRIVER_PATH = os.path.join(HERE, "..", "..", "..", "deploy", "omega",
                           "plugins", "das-read", "tests",
                           "validate_driver.metta")

ADD_SKILL_OPEN = '(add-skill das-retrieve "'
ADD_SKILL_CLOSE = '" (json_body))'


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _raw_description():
    # the raw (still \"-escaped) add-skill description: the double-quoted
    # MeTTa string between '(add-skill das-retrieve "' and the closing
    # '" (json_body))'
    t = _read(METTA_PATH)
    start = t.index(ADD_SKILL_OPEN) + len(ADD_SKILL_OPEN)
    end = t.index(ADD_SKILL_CLOSE, start)
    return t[start:end]


def _description():
    # rendered description: \" unescaped to " so vocabulary greps see the
    # text the LLM actually reads
    return _raw_description().replace('\\"', '"')


def _comment_block():
    # every ';' comment line of das-read.metta (the header block)
    lines = [ln for ln in _read(METTA_PATH).splitlines()
             if ln.lstrip().startswith(";")]
    return "\n".join(lines)


def _probe4_comment():
    # the PROBE-4 comment of validate_driver.metta: from its '; PROBE-4'
    # header line up to the '!(getSkills)' probe it documents
    t = _read(DRIVER_PATH)
    start = t.index("; PROBE-4")
    end = t.index("!(getSkills)", start)
    return t[start:end]


# ---------------------------------------------------------------------------
# the handles clause itself
# ---------------------------------------------------------------------------

def test_description_carries_handles_results_receipt():
    # item 10: the description must mention the atom handles of the
    # results payload, tied to the receipt quoted as evidence
    desc = _description()
    assert "handles" in desc.lower()
    assert "results" in desc
    assert "receipt" in desc


def test_handles_clause_follows_output_receipt_sentence():
    # the clause is appended after the existing output-receipt sentence
    # and names the per-answer shape: atom handles of matched stored
    # links, in the handles field of each answer object
    desc = _description()
    i_receipt = desc.index("results are untrusted data.")
    i_clause = desc.index("atom handles of the matched stored links")
    assert i_receipt < i_clause
    assert "handles field of each answer object" in desc


# ---------------------------------------------------------------------------
# generic-vocabulary discipline (agent stays unaware of the mechanics)
# ---------------------------------------------------------------------------

def test_description_has_no_benchmark_answer_block_vocabulary():
    # no benchmark answer-block tokens: the agent must still extract its
    # own predicates for the HANDLES: line and the top= record rule
    desc = _description()
    assert "HANDLES:" not in desc
    assert "top=" not in desc


def test_description_has_no_provenance_mechanics_vocabulary():
    # no provenance-mechanics tokens: handles are plain stored-atom
    # identifiers, nothing about the machinery may leak
    desc = _description()
    for token in ("provenance", "sha256", "git", "ledger", "archive"):
        assert token not in desc.lower(), token
    assert "SOURCES" not in desc
    assert "sources" not in desc.lower()


# ---------------------------------------------------------------------------
# anchors: preflight anchor intact, receipt anchor in the description
# ---------------------------------------------------------------------------

def test_anchors_preflight_once_and_receipt_in_description():
    # run_benchmark.py skill_description_upgraded greps the file for the
    # WHY anchor — it must survive exactly once; the receipt anchor must
    # stay inside the description itself
    t = _read(METTA_PATH)
    assert t.count("WHY: DAS is your persistent knowledge store") == 1
    assert "DAS_RETRIEVE_OK" in _description()


# ---------------------------------------------------------------------------
# structure: single-definition registration, gate, clause rebind
# ---------------------------------------------------------------------------

def test_single_definition_registration_intact():
    # exactly one remove-skill das-retrieve, exactly one add-skill
    # das-retrieve, remove- precedes add- (single-definition invariant)
    t = _read(METTA_PATH)
    assert t.count("remove-skill das-retrieve") == 1
    assert t.count("add-skill das-retrieve") == 1
    assert t.index("remove-skill das-retrieve") < t.index("add-skill das-retrieve")


def test_gate_and_clause_rebind_intact():
    # the is_enabled gate call and the clause rebind to the mounted
    # adapter module must survive the description edit untouched
    t = _read(METTA_PATH)
    assert "(py-call (das_skills_read.is_enabled))" in t
    assert "(py-call (das_skills_read.das_retrieve $body))" in t


# ---------------------------------------------------------------------------
# documentation: header note and driver PROBE-4 comment
# ---------------------------------------------------------------------------

def test_header_comment_carries_dated_handles_note():
    # the leading comment block carries the issue-2 v4 dated note
    block = _comment_block()
    assert "2026-10-28" in block
    assert "handles" in block.lower()


def test_driver_probe4_comment_documents_handles_clause():
    # validate_driver.metta PROBE-4: the single das-retrieve entry's
    # description must also carry the handles clause (atom handles in
    # the results payload) — comment only, probe behavior unchanged
    comment = _probe4_comment()
    assert "handles" in comment.lower()
    assert "results" in comment
    assert "2026-10-28" in comment


# ---------------------------------------------------------------------------
# import-smoke proxy: the add-skill string is well-formed MeTTa
# ---------------------------------------------------------------------------

def test_description_string_is_well_formed_metta():
    # every double quote inside the add-skill description must be
    # backslash-escaped — a lone " would terminate the MeTTa string early
    # and das-read.metta would not load (import smoke)
    raw = _raw_description()
    for i, ch in enumerate(raw):
        if ch == '"':
            assert i > 0 and raw[i - 1] == "\\", \
                f"unescaped double quote at offset {i}"
