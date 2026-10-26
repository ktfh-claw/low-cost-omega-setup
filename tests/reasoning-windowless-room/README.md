# Windowless Room Gating Test (v10)

## Purpose

Strict, deterministic **gating test** for the Omega agent's DAS-grounded reasoning governance. Not a scored benchmark: the test verifies that the environment is set up so the agent **answers query-first from DAS with provable provenance**, and it FAILS hard when it does not.

The test uses the classic "windowless room" prompt:

> "You are in a windowless room / attic in the dark. You turn on a bulb/lamp and look straight up. What do you see?"

**Expected correct answer:** The ceiling (or the lamp/bulb hanging from the ceiling). "The sky" is the pattern-match failure the test catches.

## The Gate (what a case must satisfy to PASS)

Every case must pass ALL four gates:

1. **A-gate (answer):** the `FINAL ANSWER (<case>)` line exists and is substantively correct (regex/keyword graded — deterministic, no LLM anywhere in the harness).
2. **Q-gate (query-first):** a REAL `das-retrieve` query was executed during the benchmark window (attested against history.metta snapshots), quoted in answers.md with its `DAS_RETRIEVE_OK ... count=<n>` receipt BEFORE the answer line, non-degenerate (≥1 `$variable` AND ≥1 non-variable literal — a quoted string or a bare content symbol; structural keywords like `Evaluation`/`Inheritance` do not count, and `$_` placeholders fail), and re-issued by the harness via the read-proxy with a matching count. The unsolvable case requires a quoted `count=0` absence probe that also re-issues at 0.
3. **E-gate (extraction):** knowledge-case FACTS lines exist and resolve verbatim against the extraction record (facts-index.md); first-case ingestion is receipt-proven; query literals reuse the extracted vocabulary.
4. **R-gate (reasoning trace):** the `REASONING:` line carries the formalized MeTTa reasoning trace — question clause (the executed query) first, verbatim extraction-record fact steps, optional derived conclusion over extracted vocabulary — semicolon-separated s-expressions, NOT generated prose (`R_NOT_METTA`). Unsolvable case keeps the trace shape but is exempt from index grounding.
5. **P-gate (provenance):** every `git:<sha> <url>` source citation resolves against the provenance git repo: commit exists → exactly one `sources/` blob + `index.jsonl` change → index entry at that commit matches the blob path → sha256(blob) matches the index entry → entry URL matches the citation. Knowledge cases with no SOURCES line fail.

Failure reasons are machine-readable condition codes (`A_MISSING`, `Q_NOT_IN_HISTORY`, `Q_PLACEHOLDER`, `Q_DEGENERATE_PATTERN`, `Q_REISSUE_MISMATCH`, `Q_ABSENCE_UNPROVEN`, `P_MISSING`, `P_UNRESOLVED:<COND>`, …) — see `grading.py` docstring.

## Files

- `background/*.md` — 5 background knowledge sources (spatial, lighting, perspective, meta-reasoning, failure-modes)
- `prompts/*.md` — the 7 prompt cases + expected-answer doc
- `facts.py` — canonical fact set (grading oracle, opt-in `--seed-canonical`), SOURCE_URLS, TEST_CASES
- `grading.py` — v5 strict gate: answers.md parsing (horizontal-whitespace-anchored line regexes), degenerate-query detection, MeTTa reasoning-trace parsing + grounding, gate_case + condition codes
- `history_parse.py` — benchmark-window extraction (pre/post snapshot prefix slicing), das-retrieve arg normalization (raw + JSON payload forms), placeholder/receipt/sha extraction
- `provenance_check.py` — citation → git repo resolution chain (mirrors the bridge's write-time verify_commit, read-only)
- `agent_prompt_template.md` — benchmark-mode prompt with the exact answers.md block format the gate parses
- `run_benchmark.py` — orchestrator CLI (phases: preflight|setup|agent|grade|report|teardown|full)
- `unit/` — 169 offline unit tests (stdlib shim runner: `python3 unit/run_tests.py`)
- `results/<run-id>/` — per-run artifacts (preflight/setup/agent/grade/report/teardown JSON + report.md)

## Exit Codes (the signal)

`grade`, `report`, and `full` return:

- `0` — gate PASS
- `2` — gate FAIL (expected negative signal: the environment did NOT meet the governance bar)
- `1` — harness/environment error (answers unreadable, no history window, etc.)

`full` ALWAYS runs teardown (even on gate FAIL) so the agent returns to standby.

## Offline Re-grade

`grade` supports `--answers-override`, `--history-override`, `--pre-snapshot-override`, `--post-snapshot-override` for re-grading archived runs without touching the live agent. A missing pre-benchmark snapshot is an error (window undefined → refuse to grade).

## Success Criteria

- All 7 cases PASS the A/Q/E/R/P gate (exit 0)
- No fabricated queries (quoted query must exist in the benchmark-window history)
- No degenerate queries (placeholders, bare variables)
- Every citation resolves to the provenance git repo
- The unsolvable case proves absence (count=0, re-issued)
- Zero LLM interaction in the harness: grading is regex/keyword/HTTP/git only
- The REASONING: line carries a MeTTa reasoning trace grounded in DAS-retrieved facts (the campaign-grade standard), not generated prose

## Provenance

- v1 (benchmark): generated 2026-10-21; live run wr-2026-20261021-2355 graded 1/7 trace-PASS — all answers correct but no real das-retrieve calls
- v2 (gating test): 2026-10-22, per Balazs's directive — strict query-first gate, degenerate-trace conditions, provenance-resolves-to-git, deterministic grading
- v5 (reasoning-trace standard): 2026-10-24 — levers 1–2 rejected; R-gate (MeTTa trace, deterministic grounding), prompt step 4 (trace before answer write), line-anchored block parsing fix; 114 offline unit tests
- v6 (campaign-style fixed pipeline): 2026-10-24 19:50 UTC directive — deliverable-first prompt (reasoning trace + answer block on top), open-ended study step REMOVED (extraction = one unconditional bounded pass, record-driven skip); anti-loop rules; 8 new prompt-contract tests; 122 offline unit tests
- v7 (executed-reasoning standard): 2026-10-25 10:57 UTC directive — scenario A/A2 findings built in: `R_NOT_EXECUTED` gate (interpreter `(stv ...)` evidence required — `exec` record lines or trace-quoted stv; hand-composed truth values fail; unsolvable exempt), prompt step 4 EXECUTE THE REASONING (2-arg NAL/PLN contract via the metta-grammar plugin, exec-record discipline), step 5 deliverable-first write, STOP rule idle-silently discipline, preflight metta plugin checks (repo artifact + live mount); 127 offline unit tests
- v8 (pinned-ledger working memory): 2026-10-25 14:48 UTC directive — wr3g root cause (per-wake restarts collapse prior tool results to `$_` history tuples; each wake re-derived progress from file reads alone; 120/122 shell reads, zero DAS calls, header-only artifacts) fixed by the PINNED LEDGER: a mechanical `pin`-maintained ledger line (`LEDGER: step <1-5> | done: ... | next: <ONE literal tool call>`) is required cross-cycle working memory — pinned tool output is the only tool result that survives a wake; first-cycle seed = ledger pin with the literal archive-source call; each wake issues the `next:` call immediately instead of re-deriving from files; orientation reads bounded to one per cycle; terminal ledger line on completion; anti-loop unsure-resolution reroutes through the ledger. 136 offline unit tests (9 new v8 ledger-contract tests in `unit/test_v8_prompt.py`; v6 anti-loop invariant updated to the ledger routing).
- v9 (false-extraction-record visibility): 2026-10-25 20:44 UTC directive (wr3h close-out: push v7/v8; wr3i ①②③) — lever ① debug REFUTED the bridge round-trip hypothesis (fresh ar2/ar3/ar4 facade writes all retrieve; canary=4; agent-written lighting facts retrieve; the zero-result loop was TRUE ABSENCE: ~10 of ~23 recorded expressions — incl. the case-critical spatial facts — were never persisted, mongo holds zero nodes for their vocabulary); `parse_facts_index` accepts the agent's real record shapes (`expr` labels, trailing src/git annotations, receipt suffixes — balanced-prefix scan; wr3h graded facts_index_size=0 against a 3,067 B record); new informational `E_INDEXED_NOT_PERSISTED` presence cross-check (every recorded expression probed against DAS via last-element `$X` binding; absent ones listed per-expression); attestation lane always collected + `attested_retrieve_calls`/`attested_write_calls`/`attested_archive_calls` in grade JSON (history channel collapses to 100% `$_` placeholders); prompt step 1 = one `expr <expression> verified=<n>` line per fresh receipt, no batch recording; step 3 + anti-loop = count=0 twice-is-final bound with one re-persist allowance. 149 offline unit tests (13 new v9 gate tests incl. the real wr3h facts-index fixture).
- v10 (grader false-positive fixes): 2026-10-26 night directive (wr3i close-out: all 6 fired uncertainty-case conditions grader-side or harness-side) — (a) `A_SKY` negation-aware ("no window or sky visible" is the honest correct answer; an UNNEGATED sky/sun/stars mention still fails; negation must PRECEDE the claim, so "sky visible but no windows" still fails); (b) `Q_DEGENERATE_PATTERN` literal check accepts bare content symbols per its own docstring (the live working query `(--> (looking-up windowless-room) $X)` was rejected; structural keywords like `Evaluation`/`Inheritance` still do not count — `(Evaluation $X $Y)` remains a tautology probe); (c) `R_TRACE_NOT_GROUNDED` grounds executed-derivation steps ATOM-WISE (`(|- call premise) => output` splits into call + output atoms; whole-line comparison could never ground them; bare-symbol dialect grounds against the index/query bare-symbol vocabulary, fabricated atoms still fail); (d) attested-retrieve regex de-escaped to the facade pattern (the rf-string `HTTP/1\\.1" 2\\d\\d` demanded literal backslashes → the lane read 0 for every window containing real query traffic; proved by live repro on the wr3i 00:00:07.562Z agent query); (e) prompt gate-rules: cite each `git:<sha> <url>` pair EXACTLY as the archive receipt returned it (wr3i P_URL_MISMATCH ×2 diagnosed as agent-side mispairing: the agent shifted shas one position across source urls — wr3h receipts prove `3443aff`=perspective.md and `6149e59`=failure-modes.md, but the wr3i SOURCES line cited `6149e59`+perspective.md and `3443aff`+meta-reasoning.md). 169 offline unit tests (20 new v10 tests in `unit/test_v10_gates.py`).
- Reference: windowless-room prompt (classic LLM failure case)
