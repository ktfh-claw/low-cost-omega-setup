# Windowless Room Reasoning Test — Test Specification

## Overview

This specification defines the end-to-end windowless-room reasoning benchmark for the Omega agent (DAS-backed persistent-knowledge agent deployed on an OVH server). The test exercises the agent's ability to reason about a 3D scene using DAS-persisted background knowledge, and audits the full provenance chain (Git archive + DAS atoms/links + quoted evidence).

## Scope

- **In scope:** Background knowledge ingestion, fact extraction + persistence, prompt answering, grading, two-layer trace verification, provenance audit, reporting, opt-in cleanup.
- **Out of scope:** LLM-based grading, LLM interaction for the test itself, subjective assessment.

## Test Structure — Phases

The benchmark is orchestrated by `run_benchmark.py` with these phases (each independently runnable over SSH; also `full`):

1. **preflight** — verify environment: docker containers (`omega-das-write-bridge-write-bridge-1`, `omega-das-integration-read-proxy-1`, `omega-curiosity`) running; resolve their client-network IPs dynamically (do NOT hardcode); write-bridge smoke test (POST /v1/write with verify:true); read-proxy metta query test; provenance repo exists; agent memory volume exists. Exit nonzero on failure.
2. **setup** — archive the background sources (POST /v1/archive); write `benchmark/background/`, `benchmark/urls.txt`, `benchmark/prompts.txt` into the agent memory volume; render `agent_prompt_template.md` → `prompt.txt` (backup existing); write benchmark-mode `omega_state.md` (backup existing); copy `history.metta` for window slicing; restart the agent via `sudo systemctl restart omega-curiosity.service`.
3. **agent** — poll for completion: the answers file exists and contains all 7 `FINAL ANSWER (case):` lines, or timeout (default 60 minutes).
4. **grade** — parse answers.md per case; grade each case per `grading.py`; two-layer verification (re-issue quoted das-retrieve queries via read-proxy; compare counts/assignments); provenance audit (each cited git sha exists in the provenance repo + maps to a cited URL).
5. **report** — assemble `results/<run-id>/report.json` (machine) + `report.md` (human); print report.md to stdout.
6. **teardown** — restore prompt.txt + omega_state.md from backups; append a truthful "benchmark complete, returned to standby" line; restart the service. If `--cleanup`: remove the benchmark DAS atoms via cleanup.py (links-only default; NEVER --delete-nodes — symbol nodes are shared on the live DB). Default (no --cleanup): leave facts (they are the benchmark's persistent product).
7. **full** — preflight → setup → agent → grade → report → teardown with a single command; crash-resumable (phases skip if their output JSON exists unless `--force`).

## Test Cases

| # | ID | Prompt file | Type | Expected answer | Grading key |
|---|----|------------|------|-----------------|-------------|
| 1 | `original` | `prompts/original-prompt.md` | Primary (previously-used example) | The ceiling (or the lamp/bulb hanging from it) | PASS iff answer mentions ceiling AND not sky/sun/stars; trace present |
| 2 | `uncertainty` | `prompts/uncertainty-prompt.md` | Uncertainty (room/attic ambiguity) | The ceiling | PASS iff answer is ceiling or ceiling + lamp/bulb with trace |
| 3 | `unsolvable` | `prompts/unsolvable-unrelated-prompt.md` | Unsolvable (unrelated domain) | Reports inability from stored knowledge | PASS iff agent reports inability AND does not state a specific capital/population answer |
| 4 | `true` | `prompts/true-statement-prompt.md` | True statement | True | PASS iff answer is true-affirming with trace |
| 5 | `false` | `prompts/false-statement-prompt.md` | False statement | False | PASS iff answer is false-affirming with trace (answering "true" → FAIL) |
| 6 | `easy` | `prompts/easy-prompt.md` | Easy (simple fact lookup) | The ceiling | PASS iff agent answers "the ceiling" citing DAS facts |
| 7 | `difficult` | `prompts/difficult-prompt.md` | Difficult (multi-step chained) | The sloped ceiling (underside of the roof) | PASS iff answer mentions sloped ceiling / underside of roof AND not sky/stars/exterior-of-roof; trace present |

## Expected Input

- **Input:** `tests/reasoning-windowless-room/background/*.md` — reasoning text already generated and pushed to the repo (commit `ea8245d`).
- **Expected output:** For each test case: (a) answer, (b) DAS query trace, (c) provenance artifacts (Git hash + source link), (d) standardized JSON report.

## Canonical-Fact Model

The benchmark has two modes for the fact set:

- **Agent-extracted (primary mode):** the agent derives predicates from the background text and persists them via the write-bridge with provenance. The harness grades the answers; the fact set is the agent's own.
- **Seed-canonical (grading-oracle mode, opt-in via `--seed-canonical`):** the harness writes `CANONICAL_FACTS` (from `facts.py`) to DAS with the archived shas + stv via /v1/write. Used to diff the agent's extracted facts against the canonical set (semantic-overlap heuristic; reported as coverage, not a hard fail).

`facts.py` exports `CANONICAL_FACTS` (~25–35 facts), `SOURCE_URLS`, and `TEST_CASES` with per-case `required_facts`.

## Provenance Chain

Each fact is traceable end-to-end:

1. Background file (`tests/reasoning-windowless-room/background/<file>.md`)
2. → raw URL (`https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/main/tests/reasoning-windowless-room/background/<file>`)
3. → `/v1/archive` POST → git commit sha (`ARCHIVE-OK git:<40-hex-sha>`)
4. → `add-atom` suffix (the `git:<sha>` travels with the fact)
5. → DAS atom (BRIDGE-PERSIST-OK verified handle)
6. → quoted evidence in answers.md (the agent cites the query + count + git sha + source URL)

## Two-Layer Verification

- **Layer 1 (agent's claims):** the agent quotes das-retrieve queries with counts and result summaries in answers.md.
- **Layer 2 (harness re-verification):** the harness re-issues each quoted query via the read-proxy (metta mode, 30s timeout) and compares result counts and assignment sets. Mismatch → trace verification failure.
- **Provenance check:** every git sha the agent cites must exist in the provenance repo (`git cat-file -t <sha>`) and map to a cited URL via the index entry (`sources/index.jsonl` or `index.jsonl`).

## Report Schema

`results/<run-id>/report.json` (machine-readable):
- `run_id`, `timestamp`
- `setup`: archived shas, file paths, container IPs, prompt installed
- `per_case`: per-case verdict (PASS/FAIL), reason, evidence
- `trace_verification`: per-query verdicts, trace_ok boolean
- `provenance`: per-sha verdicts, provenance_ok boolean
- `history_summary`: counts by kind (das_retrieve, add_atom, archive_source), written expressions, archive shas, queries

`results/<run-id>/report.md` (human-readable): run header, per-case table (PASS/FAIL + answer excerpts), provenance chain table (fact → git sha → source URL), trace verification summary, notes.

## Cleanup Policy

- **Opt-in:** `--cleanup` flag on teardown.
- **Links-only:** each fact removed via `cleanup.py --metta "<expr>"` (links-only default).
- **NEVER `--delete-nodes`:** symbol nodes are shared on the live DB; node deletion would corrupt other data.
- **Default (no --cleanup):** leave the facts — they are the benchmark's persistent product.

## Deployment Invariants

1. **Engine rejects ground patterns — always variable-form:** the read-proxy returns 400 for ground (non-variable) patterns. All queries must contain at least one `$variable`.
2. **Systemd restart, NOT docker restart:** the agent unit's `start.sh` trap `rm -f`'s the container. Use `sudo systemctl restart omega-curiosity.service`.
3. **Write-bridge is fire-and-forget:** `SUCCESS, RETURN:` only means the skill ran. `BRIDGE-PERSIST-OK: verified=<n>` is the ONLY write success — the verified handles are the write receipt. `ARCHIVE-OK` is the only archive success. `DAS_RETRIEVE_OK count=<n>` is the only retrieve success.

## External Links

- Repo: https://github.com/ktfh-claw/low-cost-omega-setup
- Test folder: `tests/reasoning-windowless-room/`

## Contact

Maintained by the assistant (Vector) for Balazs. Questions about the spec belong in `test-spec.md`.
