"""Plugin syntax/registration tests for das-grounded-reasoning (skill-split T03).

Verifies the .metta plugin file is syntactically well-formed (balanced
parens), the registration pattern (remove-skill + add-skill) is present,
and the skill description carries the required contract markers: the
checkpoint manifest reference, the das-retrieve grammar, and the
untrusted-answers policy. Also verifies the ZERO benchmark/campaign
vocabulary constraint.
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

GROUNDED_METTA = os.path.join(
    HERE, "..", "..", "..", "deploy", "omega", "plugins",
    "das-grounded-reasoning", "das-grounded-reasoning.metta")
GROUNDED_PY = os.path.join(
    HERE, "..", "..", "..", "deploy", "omega", "plugins",
    "das-grounded-reasoning", "das_grounded_reasoning.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _description(metta_text):
    m = re.search(r'\(add-skill das-grounded-reasoning "(.*?)" \(json_body\)\)', metta_text, re.DOTALL)
    if not m:
        raise AssertionError("add-skill das-grounded-reasoning not found")
    return m.group(1)


# ---------------------------------------------------------------------------
# syntax / registration
# ---------------------------------------------------------------------------

def test_plugin_metta_balanced_parens():
    content = _read(GROUNDED_METTA)
    lines = [l for l in content.splitlines() if not l.strip().startswith(';')]
    text = '\n'.join(lines)
    assert text.count('(') == text.count(')'), "unbalanced parens in das-grounded-reasoning.metta"


def test_registration_pattern_remove_then_add():
    content = _read(GROUNDED_METTA)
    assert 'remove-skill das-grounded-reasoning' in content
    assert 'add-skill das-grounded-reasoning' in content
    assert content.index('remove-skill das-grounded-reasoning') < content.index('add-skill das-grounded-reasoning')


def test_handler_clause_bound():
    content = _read(GROUNDED_METTA)
    assert '(py-call (das_grounded_reasoning.handle $body))' in content


def test_python_module_syntax():
    import ast
    ast.parse(_read(GROUNDED_PY))


# ---------------------------------------------------------------------------
# description contract markers (R2)
# ---------------------------------------------------------------------------

def test_description_references_checkpoint_manifest():
    desc = _description(_read(GROUNDED_METTA))
    assert 'checkpoint' in desc.lower()


def test_description_references_das_retrieve():
    desc = _description(_read(GROUNDED_METTA))
    assert 'das-retrieve' in desc


def test_description_carries_why_when_how():
    desc = _description(_read(GROUNDED_METTA))
    assert 'WHY:' in desc
    assert 'WHEN:' in desc
    assert 'HOW:' in desc


def test_description_states_untrusted_answers():
    desc = _description(_read(GROUNDED_METTA))
    assert 'untrusted' in desc.lower() or 'parametric memory' in desc.lower()


# ---------------------------------------------------------------------------
# zero benchmark/campaign vocabulary (R2 hard constraint)
# ---------------------------------------------------------------------------

def test_description_no_benchmark_vocabulary():
    desc = _description(_read(GROUNDED_METTA))
    for word in ['windowless', 'benchmark', 'campaign']:
        assert word not in desc.lower(), f"benchmark vocabulary in description: {word}"
