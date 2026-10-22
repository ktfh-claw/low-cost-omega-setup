"""Regression tests for benchmark prompts.txt rendering.

Live incident wr-20261021-2355: setup() double-joined the prompt path
(HERE / "prompts" / "prompts/<name>.md") so prompts.txt shipped to the
agent memory volume with empty case bodies — the agent ran the benchmark
blind. These tests pin the correct behavior.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / ".."))

import facts
import run_benchmark


def test_prompts_txt_contains_all_case_ids():
    content = run_benchmark._render_prompts_txt(run_benchmark.HERE)
    for case in facts.TEST_CASES:
        assert f"=== CASE: {case['id']} ===" in content, case["id"]
        assert f"ANSWER FORMAT: FINAL ANSWER ({case['id']}): <answer>" in content, case["id"]


def test_prompts_txt_case_bodies_nonempty():
    """Each case block must carry real prompt text (>100 chars)."""
    content = run_benchmark._render_prompts_txt(run_benchmark.HERE)
    for case in facts.TEST_CASES:
        marker = f"=== CASE: {case['id']} ==="
        start = content.index(marker) + len(marker)
        end = content.index(f"ANSWER FORMAT: FINAL ANSWER ({case['id']}):", start)
        body = content[start:end].strip()
        assert len(body) > 100, f"case {case['id']} body too short ({len(body)} chars)"


def test_prompts_txt_matches_prompt_files_verbatim():
    """Each case body must embed its prompt file's text verbatim."""
    content = run_benchmark._render_prompts_txt(run_benchmark.HERE)
    for case in facts.TEST_CASES:
        pf = run_benchmark.HERE / case["prompt_file"]
        text = pf.read_text(encoding="utf-8").strip()
        assert text in content, f"case {case['id']}: prompt text not embedded verbatim"


def test_render_fails_fast_on_missing_prompt_file(tmp_path=None):
    """A missing prompt file must raise, not silently render an empty body."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td)
        # symlink only the files _render needs
        (fake / "facts.py").write_text(
            (run_benchmark.HERE / "facts.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (fake / "prompts").mkdir()
        # intentionally do NOT copy prompt files -> must raise
        try:
            run_benchmark._render_prompts_txt(fake)
        except FileNotFoundError:
            return
        raise AssertionError("expected FileNotFoundError for missing prompt file")
