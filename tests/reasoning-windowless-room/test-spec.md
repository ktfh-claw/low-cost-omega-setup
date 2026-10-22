# Windowless Room Gating Test — Test Specification (v2)

## Overview

This specification defines the windowless-room **gating test** for the Omega agent (DAS-backed persistent-knowledge agent on the OVH server). v2 re-scopes the test from a scored benchmark to a strict pass/fail GATE that verifies the environment is set up for DAS-grounded reasoning governance: the agent must answer **query-first** (real `das-retrieve` calls before every answer) with **provable provenance** (every citation resolves to the provenance git repo), and the harness must grade **deterministically with zero LLM interaction**.

A gate FAIL is a valid, expected signal: it means the environment/agent did not meet the governance bar — not that the harness is broken.

## Scope

- **In scope:** background ingestion, fact extraction + persistence with provenance, query-first answering, strict deterministic grading (A/Q/P gates), harness re-issue verification, provenance git resolution, reporting, teardown, exit-code signaling.
- **Out of scope:** LLM-based grading (forbidden), subjective assessment, modifying the agent's code/configuration (the harness changes only test-controlled files: prompt.txt, omega_state.md, benchmark/ inside the memory volume).

## Test Structure — Phases

Orchestrated by `run_benchmark.py` (phases independently runnable over SSH; also `full`):

1. **preflight** — verify environment: containers running (write-bridge, read-proxy, agent); dynamic IP resolution; write-bridge smoke write (+ links-only cleanup of the smoke fact); read-proxy variable-form query; provenance repo reachable via sudo; memory volume present.
2. **setup** — archive the 5 background sources (POST /v1/archive → ARCHIVE-OK shas); write `benchmark/background/`, `urls.txt`, `prompts.txt` into the memory volume; render + install the benchmark prompt (backup standby); write benchmark `omega_state.md` (backup); snapshot `history.pre-benchmark-<run-id>.metta` (defines the window start); chown benchmark/ to 65534 (agent uid); systemctl restart.
3. **agent** — poll for all 7 `FINAL ANSWER` lines (default timeout 60m); on completion (or timeout) snapshot `history.post-benchmark-<run-id>.metta` (window end).
4. **grade** — strict gate (details below). Refuses to grade without a usable pre-snapshot (window undefined = harness error). Supports `--answers-override` / `--history-override` / `--pre-snapshot-override` / `--post-snapshot-override` for offline re-grades of archived runs.
5. **report** — assemble `results/<run-id>/report.json` + `report.md`; print; return the gate signal.
6. **teardown** — contamination guard (refuses to restore a backup prompt that still contains BENCHMARK MODE content, unless `--allow-dirty-backup`); restore standby prompt + truthful omega_state.md; restart; optional `--cleanup` (links-only, NEVER --delete-nodes).
7. **full** — preflight → setup → agent → grade → report → teardown; crash-resumable (phase JSON exists → skip unless --force); teardown ALWAYS runs, even on gate FAIL.

## Exit Codes (the signal)

- `0` — gate PASS (all cases pass all gates)
- `2` — gate FAIL (the governance bar was not met — expected negative signal)
- `1` — harness/environment error

## The Gate (per case)

A case PASSES only if ALL conditions hold. Failure reasons are machine-readable condition codes.

**A-gate (answer):** `FINAL ANSWER (<case>)` present + substantively correct (regex/keyword).
- `A_MISSING`, `A_WRONG`, `A_SKY` (pattern-match failure), `A_FABRICATED` (unsolvable case states a capital), `A_NO_INABILITY`.

**Q-gate (query-first):**
- `QUERY:` line with a real metta pattern, present BEFORE the FINAL ANSWER line in the case block (`Q_MISSING`, `Q_NOT_QUERY_FIRST`)
- not a `$_` placeholder (`Q_PLACEHOLDER`) and not degenerate: ≥1 `$variable` AND ≥1 quoted non-variable literal (`Q_DEGENERATE_PATTERN`)
- the quoted query must exist in the benchmark-window history (suffix between the pre/post snapshots of history.metta) — fabricated quotes fail (`Q_NOT_IN_HISTORY`)
- `DAS_RETRIEVE_OK ... count=<n>` receipt quoted (`Q_NO_RECEIPT`)
- harness re-issues the query via the read-proxy; count must match (`Q_REISSUE_MISMATCH`, `Q_REISSUE_ERROR`)
- unsolvable case: absence must be PROVEN — quoted count=0 AND re-issue count=0 (`Q_ABSENCE_UNPROVEN`)

**P-gate (provenance):**
- knowledge cases must cite `git:<40hex> <url>` sources (`P_MISSING`)
- every citation resolves in the provenance repo: commit exists → exactly one `sources/` blob among its changes → `index.jsonl` at that commit has an entry for that blob path → sha256(blob at that commit) == entry.blob_sha256 → entry.url == cited url (`P_UNRESOLVED:<COND>` with COMMIT_NOT_IN_REPO, COMMIT_UNREADABLE, COMMIT_NOT_AN_ARCHIVE_COMMIT, COMMIT_MULTIPLE_SOURCE_BLOBS, INDEX_UNREADABLE_AT_COMMIT, INDEX_ENTRY_MISSING_FOR_BLOB, BLOB_UNREADABLE_AT_COMMIT, BLOB_SHA_MISMATCH, URL_MISMATCH)

## Test Cases

| # | ID | Type | Expected answer |
|---|----|------|----------------|
| 1 | `original` | Primary prompt | The ceiling (or lamp/bulb on it) |
| 2 | `uncertainty` | Ambiguity variant | The ceiling |
| 3 | `unsolvable` | Unrelated domain (capital of Australia) | Honest inability; proven count=0 absence |
| 4 | `true` | True statement | true |
| 5 | `false` | False statement | false |
| 6 | `easy` | Simple lookup | The ceiling |
| 7 | `difficult` | Multi-step (attic) | The sloped ceiling (underside of the roof) |

## Answers.md Contract (v2)

Per case, the gate parses blocks of exactly this shape (deviation = FAIL):

```
### CASE <id>

QUERY: <real metta pattern with $var + literal>
DAS_RETRIEVE_OK untrusted=true count=<n> truncated=<bool> results=[...]
REASONING: <short trace>
FINAL ANSWER (<id>): <answer>
SOURCES: git:<40-hex-sha> <source-url>
```

Backward compatibility: bare `FINAL ANSWER (case):` lines still parse, but they fail the Q/P gates.

## Canonical-Fact Model

- **Agent-extracted (primary):** the agent derives and persists its own predicates with provenance.
- **Seed-canonical (oracle mode, opt-in `--seed-canonical`):** harness seeds CANONICAL_FACTS for coverage diffing — not the default test mode.

## Provenance Chain

background file → raw URL → `/v1/archive` → git commit (ARCHIVE-OK) → add-atom suffix → DAS atom (BRIDGE-PERSIST-OK verified) → quoted evidence in answers.md → **resolved against the provenance git repo by the grader**.

## Determinism Guarantee

Grading uses regex/keyword parsing, string matching, deterministic HTTP re-issue against the read-proxy, and read-only git commands. **No LLM is invoked anywhere in the harness.** The same inputs always produce the same verdict.

## Report Schema

`results/<run-id>/grade.json` + `report.json`: run_id, gate_verdict, cases_passed/total, per_case {verdict, conditions[], detail{}}, history_window {mode, retrieve_calls, retrieve_args, placeholder_calls, persist/archive receipts, add_atom_shas}, citation_checks[], timestamps.

`report.md`: gate verdict header, per-case table with condition codes, window summary, condition-code reference.

## Deployment Invariants

1. Read-proxy: variable-form patterns only (ground patterns hang/400).
2. Agent restart: systemd, NEVER docker restart (start.sh trap rm -f's the container).
3. Receipts: `BRIDGE-PERSIST-OK verified=` (write), `ARCHIVE-OK` (archive), `DAS_RETRIEVE_OK count=` (retrieve) are the only success signals.
4. Memory-volume and provenance-repo operations need sudo (root-owned / 65532-owned).
5. Benchmark dir must be chowned 65534:65534 (agent runs as nobody:nogroup).

## History

- v1 (2026-10-21): scored benchmark; live run wr-20261021-2355 — 7/7 substantively correct, 1/7 trace-PASS (no real das-retrieve calls; answers from context).
- v2 (2026-10-22): re-scoped to strict gating test per Balazs's directive; condition codes, degenerate-trace conditions, provenance git resolution, deterministic grading, signal exit codes.
