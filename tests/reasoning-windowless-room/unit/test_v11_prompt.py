"""v11 prompt-path tests: memory-volume-relative artifact paths.

2026-10-26 night directive (wr3j close-out). Live wr3j evidence: the
prompt-rendered relative paths (benchmark/answers.md, benchmark/facts-index.md,
benchmark/urls.txt) are resolved by the agent container's file tools
(append-file/read-file) against the container cwd /PeTTa — NOT against the
memory volume. The volume is mounted at /PeTTa/repos/Omega/memory, so
/PeTTa/benchmark does not exist and every file-tool call on the rendered
path fails with "file does not exist" (wr3j: 34+ APPEND-FAILED loops burned
the case-1 window; earlier runs silently absorbed the same defect via
self-recovery). The rendered prompt must therefore carry MEMORY-VOLUME-
RELATIVE paths (repos/Omega/memory/benchmark/...), which resolve for file
tools AND shell alike.
"""

import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import run_benchmark


def _fake_args(run_id="t-run", case="original"):
    return SimpleNamespace(
        run_id=run_id, case=case, dry_run=False,
        memory_volume="/fake/vol", trim_history=True,
        timeout_minutes=75,
    )


def _render(case_id="original"):
    case = next(c for c in run_benchmark._facts_mod().TEST_CASES
                if c["id"] == case_id)
    return run_benchmark._render_case_prompt(_fake_args(case=case_id), case)


def test_rendered_paths_memory_volume_relative():
    # v11: the prompt must render MEMORY-VOLUME-RELATIVE paths — the volume
    # is mounted at /PeTTa/repos/Omega/memory inside the agent container
    prompt = _render()
    assert "repos/Omega/memory/benchmark/urls.txt" in prompt, \
        "urls.txt path must be memory-volume-relative"
    assert "repos/Omega/memory/benchmark/answers.md" in prompt, \
        "answers.md path must be memory-volume-relative"
    assert "repos/Omega/memory/benchmark/facts-index.md" in prompt, \
        "facts-index.md path must be memory-volume-relative"


def test_rendered_prompt_has_no_bare_benchmark_paths():
    # the bare relative form is the wr3j defect: file tools resolve it
    # against /PeTTa where no benchmark dir exists. EVERY occurrence of
    # `benchmark/` in the rendered prompt must sit under
    # repos/Omega/memory/ — a single bare occurrence is enough to send the
    # agent into the APPEND-FAILED loop.
    prompt = _render()
    start = 0
    seen = 0
    while True:
        idx = prompt.find("benchmark/", start)
        if idx < 0:
            break
        seen += 1
        ctx = prompt[max(0, idx - 40):idx]
        assert "repos/Omega/memory" in ctx, \
            f"bare benchmark-relative path in rendered prompt near: {prompt[idx:idx+60]!r}"
        start = idx + len("benchmark/")
    assert seen >= 3, "expected at least the three artifact paths in the rendered prompt"


def test_prompt_constants_split_from_volume_paths():
    # the harness's own volume-side paths stay benchmark-relative (the
    # volume ROOT is the harness's memory_volume arg); only the PROMPT-side
    # constants move under repos/Omega/memory
    assert run_benchmark.ANSWERS_REL == "benchmark/answers.md"
    assert run_benchmark.FACTS_INDEX_REL == "benchmark/facts-index.md"
    assert run_benchmark.URLS_REL == "benchmark/urls.txt"
    assert run_benchmark.ANSWERS_PROMPT_REL == "repos/Omega/memory/benchmark/answers.md"
    assert run_benchmark.FACTS_INDEX_PROMPT_REL == "repos/Omega/memory/benchmark/facts-index.md"
    assert run_benchmark.URLS_PROMPT_REL == "repos/Omega/memory/benchmark/urls.txt"


def test_template_path_literals_updated():
    # the template's own literals (not placeholders) must name the
    # memory-volume-relative dir: the step-1 instruction and the question
    # preamble
    with open(os.path.join(HERE, "..", "agent_prompt_template.md"),
              encoding="utf-8") as f:
        t = f.read()
    assert "repos/Omega/memory/benchmark/background/" in t
    assert "`benchmark/background/`" not in t
    # placeholders still present for the render pass
    for ph in ("{{URL_LIST_PATH}}", "{{ANSWERS_PATH}}", "{{FACTS_INDEX_PATH}}"):
        assert ph in t, ph
