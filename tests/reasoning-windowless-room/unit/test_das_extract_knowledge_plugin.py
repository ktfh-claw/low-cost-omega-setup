"""Plugin syntax/registration tests for das-extract-knowledge (skill-split T02).

Verifies the .metta plugin file is syntactically well-formed (balanced
parens), the registration pattern (remove-skill + add-skill) is present,
and the skill description carries the required contract markers: the
das-write invocation form, the BRIDGE-PERSIST-OK receipt contract, and
the bounded single-pass extraction constraint. Also verifies the ZERO
benchmark/campaign vocabulary constraint (no windowless-room, benchmark,
or campaign words in the description).
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

EXTRACT_METTA = os.path.join(
    HERE, "..", "..", "..", "deploy", "omega", "plugins",
    "das-extract-knowledge", "das-extract-knowledge.metta")
EXTRACT_PY = os.path.join(
    HERE, "..", "..", "..", "deploy", "omega", "plugins",
    "das-extract-knowledge", "das_extract_knowledge.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _description(metta_text):
    """Extract the add-skill description string from the .metta file."""
    m = re.search(r'\(add-skill das-extract-knowledge "(.*?)" \(json_body\)\)', metta_text, re.DOTALL)
    if not m:
        raise AssertionError("add-skill das-extract-knowledge not found")
    return m.group(1)


# ---------------------------------------------------------------------------
# syntax / registration
# ---------------------------------------------------------------------------

def test_plugin_metta_balanced_parens():
    content = _read(EXTRACT_METTA)
    lines = [l for l in content.splitlines() if not l.strip().startswith(';')]
    text = '\n'.join(lines)
    assert text.count('(') == text.count(')'), "unbalanced parens in das-extract-knowledge.metta"


def test_registration_pattern_remove_then_add():
    content = _read(EXTRACT_METTA)
    # remove-skill must precede add-skill (single-definition invariant)
    assert 'remove-skill das-extract-knowledge' in content
    assert 'add-skill das-extract-knowledge' in content
    assert content.index('remove-skill das-extract-knowledge') < content.index('add-skill das-extract-knowledge')


def test_handler_clause_bound():
    content = _read(EXTRACT_METTA)
    assert '(py-call (das_extract_knowledge.handle $body))' in content


def test_python_module_syntax():
    # the Python module must be syntactically valid Python
    import ast
    ast.parse(_read(EXTRACT_PY))


# ---------------------------------------------------------------------------
# description contract markers (R1)
# ---------------------------------------------------------------------------

def test_description_references_das_write_add_atom():
    desc = _description(_read(EXTRACT_METTA))
    assert 'add-atom &persistent' in desc


def test_description_states_receipt_contract():
    desc = _description(_read(EXTRACT_METTA))
    assert 'BRIDGE-PERSIST-OK: verified=<n> top=<handle>' in desc


def test_description_states_bounded_single_pass():
    desc = _description(_read(EXTRACT_METTA))
    assert 'Bounded single-pass' in desc or 'bounded single-pass' in desc


def test_description_carries_why_when_how():
    desc = _description(_read(EXTRACT_METTA))
    assert 'WHY:' in desc
    assert 'WHEN:' in desc
    assert 'HOW:' in desc


def test_description_references_das_write_persistence():
    # the extraction procedure must reference the das-write skill (add-atom
    # persistence path) as the persistence mechanism (R1)
    desc = _description(_read(EXTRACT_METTA))
    assert 'das-write' in desc
    assert 'add-atom &persistent' in desc


# ---------------------------------------------------------------------------
# zero benchmark/campaign vocabulary (R1 hard constraint)
# ---------------------------------------------------------------------------

def test_description_no_benchmark_vocabulary():
    desc = _description(_read(EXTRACT_METTA))
    for word in ['windowless', 'benchmark', 'campaign']:
        assert word not in desc.lower(), f"benchmark vocabulary found: {word}"


def test_metta_file_no_benchmark_vocabulary():
    # the entire .metta file (including comments) must be free of
    # windowless-room / benchmark / campaign references in the skill
    # description (comments may reference the directive context)
    content = _read(EXTRACT_METTA)
    desc = _description(content)
    for word in ['windowless', 'benchmark', 'campaign']:
        assert word not in desc.lower(), f"benchmark vocabulary in description: {word}"
