# Windowless Room Gating Test — Test Specification (v3)

## Overview

This specification defines the windowless-room **gating test** for the Omega agent (DAS-backed persistent-knowledge agent on the OVH server). v2 re-scoped the test from a scored benchmark to a strict pass/fail GATE that verifies the environment is set up for DAS-grounded reasoning governance: the agent must answer **query-first** (real `das-retrieve` calls before every answer) with **provable provenance** (every citation resolves to the provenance git repo), and the harness must grade **deterministically with zero LLM interaction**.

v3 (2026-10-23 directive) makes **sequential standalone-question mode the default** — one prompt = one question, graded independently — and adds: an **E-gate** on clause extraction, harness-side **attestation lanes** for the known-lossy history channel, a pre-run **cleanup-das** phase, **blob reconstruction** back to the source markdown bytes, and explicit **environment requirements** (das-retrieve skill-description upgrade, pin working-memory plugin, chroma_db memory dir). `--batch` keeps the v2 all-at-once flow.

A gate FAIL is a valid, expected signal: it means the environment/agent did not meet the governance bar — not that the harness is broken.

## Scope

- **In scope:** background ingestion (agent-driven in sequential mode), fact extraction + persistence with provenance, query-first answering, strict deterministic grading (A/Q/E/P gates), harness re-issue verification, provenance git resolution + blob reconstruction, harness-side log attestation, pre-run DAS residue cleanup, reporting, teardown, exit-code signaling, and **agent-environment configuration deployed from this repo** (das-retrieve skill description upgrade, pin plugin rebind, chroma_db memory dir) — explicitly authorized by the v3 directive.
- **Out of scope:** LLM-based grading (forbidden), subjective assessment. At run time the harness still modifies only test-controlled files (prompt.txt, omega_state.md, benchmark/ inside the memory volume); agent plugin/skill configuration is deployed and validated before the run (preflight + the das-read plugin validation driver), never edited by the harness mid-run.

## Modes

### Sequential standalone-question mode (v3 default)

One prompt contains exactly ONE case question. The harness drives the sequence; each case runs the per-case phases and is graded independently:

1. **setup-case** — prepare the benchmark dir (background files + urls.txt, idempotent); on the FIRST case (`original`) initialize fresh `answers.md` + `facts-index.md`, back up prompt.txt / omega_state.md (`*.bak-pre-benchmark-<run-id>`), chown benchmark/ to 65534:65534; then for EVERY case: snapshot `history.pre-case-<run-id>-<case>.metta` (the case's window start), render + install the per-case prompt, write the benchmark `omega_state.md` (case marker), restart the agent.
2. **agent-case** — poll `answers.md` every 30 s for this case's `FINAL ANSWER (<case>):` line (default timeout 45 m); on completion OR timeout snapshot `history.post-case-<run-id>-<case>.metta` (window end). A timeout is a case failure, not a harness error — the case is graded anyway (it will fail its gates).
3. **grade-case** — the independent A/Q/E/P gate for this case (details below). Window = the case's pre/post snapshots. Refuses to grade without the pre-case snapshot (window undefined = harness error). Attestation + reconstruction lanes run here.

Sequential-mode properties:

- **Agent-driven ingestion.** The harness does NOT archive the background sources; the agent must ingest them itself (archive-source → ARCHIVE-OK; add-atom → BRIDGE-PERSIST-OK). The E-gate's first-case ingest check (below) verifies this actually happened.
- **Independent grading.** Every case is graded regardless of the previous case's verdict; the sequence continues after a FAIL. Overall gate: PASS iff every selected case passes and no harness error occurred.
- **`--cases` subset filter** (iteration mode): relaunch only the cases under test, e.g. `--cases original,uncertainty`. Unknown ids are a harness error.
- The first case in `facts.TEST_CASES` order (`original`) is the ingest-required case (E-gate).

### Batch mode (`--batch`, v2 flow, kept)

Single prompt with all 7 questions (`prompts.txt`, rendered per-case sections); phases: preflight → setup (harness archives the 5 sources via POST /v1/archive) → agent (poll for all 7 answers, default timeout 60 m) → grade (all cases against one benchmark window) → report → teardown.

## Test Structure — Phases

Orchestrated by `run_benchmark.py` (phases independently runnable over SSH):

1. **preflight** — verify environment: containers running (write-bridge, read-proxy, query-engine, mongodb, agent); dynamic IP resolution; write-bridge smoke write (+ links-only cleanup of the smoke fact); read-proxy variable-form query; provenance repo reachable via sudo; memory volume present; plus v3 checks: `prompt_backup_fresh` (per-run backup must not pre-exist — fresh run-id rule), `skill_description_upgraded` (das-retrieve description contract present in the mounted plugin), `chroma_memory_dir` (volume chroma_db dir exists), `canary_fetch_ai` (canary count ≥ 1 — campaign atoms intact).
2. **cleanup-das** (v3) — remove previous-run benchmark residue from the DAS mongo store (details below). Runs BEFORE the test (default in `full`; `--no-cleanup` skips by pre-creating its result marker).
3. **setup-case / agent-case / grade-case** (sequential default) — per-case phases as above.
4. **report** — assemble `results/<run-id>/report.json` + `report.md`; print; return the gate signal.
5. **teardown** — contamination guard (refuses to restore a backup prompt that still contains BENCHMARK MODE content, unless `--allow-dirty-backup`); restore standby prompt + truthful omega_state.md; restart; remove the per-case history snapshots from the volume (copies are kept under `results/<run-id>/windows/<case>/`; `--keep-snapshots` preserves them). DAS cleanup is NOT part of teardown anymore — it moved to the pre-run cleanup-das phase (teardown's legacy `--cleanup` flag is not honored).
6. **full** — sequential default: preflight → cleanup-das → per case (setup → agent → grade) → report → teardown. preflight/cleanup-das are skipped if their phase JSON exists (unless `--force`); teardown ALWAYS runs (even on gate FAIL or harness error). `--batch` selects the v2 all-at-once flow; `--skip-report` omits the report phase.
7. **batch legacy phases** — `setup` (archives sources, prompts.txt, fresh answers/facts-index, backups, restart), `agent` (all-answers poll, 60 m default), `grade` (whole answers.md against the pre/post-benchmark window; supports `--answers-override` / `--history-override` / `--pre-snapshot-override` / `--post-snapshot-override` / `--facts-index-override` for offline re-grades of archived runs).

## Exit Codes (the signal) — unchanged from v2

- `0` — gate PASS (all cases pass all gates)
- `2` — gate FAIL (the governance bar was not met — expected negative signal)
- `1` — harness/environment error

## The Gate (per case)

A case PASSES iff it has NO blocking conditions. Failure reasons are machine-readable condition codes. Two conditions are **informational** — `Q_ATTESTED_VIA_ACCESS_LOG` and `E_INGEST_ATTESTED_VIA_FACADE_LOG` — they record that the harness-side attestation lanes (below) proved the evidence and do NOT fail a case; the evidence standard is unchanged, only the observation channel differs.

**A-gate (answer):** `FINAL ANSWER (<case>)` present + substantively correct (regex/keyword).
- `A_MISSING`, `A_WRONG`, `A_SKY` (pattern-match failure), `A_FABRICATED` (unsolvable case states a capital), `A_NO_INABILITY`.

**Q-gate (query-first):**
- `QUERY:` line with a real metta pattern, present BEFORE the FINAL ANSWER line in the case block (`Q_MISSING`, `Q_NOT_QUERY_FIRST`)
- not a `$_` placeholder (`Q_PLACEHOLDER`) and not degenerate: ≥1 `$variable` AND ≥1 quoted non-variable literal (`Q_DEGENERATE_PATTERN`)
- the quoted query must exist in the case-window history (suffix between the case's pre/post snapshots) — fabricated quotes fail (`Q_NOT_IN_HISTORY`) — **unless** the attestation lane proves the call via the independent logs (informational `Q_ATTESTED_VIA_ACCESS_LOG`, see below)
- `DAS_RETRIEVE_OK ... count=<n>` receipt quoted (`Q_NO_RECEIPT`)
- harness re-issues the query via the read-proxy; count must match (`Q_REISSUE_MISMATCH`, `Q_REISSUE_ERROR`); a knowledge case quoting `count=0` fails (`Q_ABSENCE_UNPROVEN`) — a truthful absence cannot be the answer to a knowledge case
- unsolvable case: absence must be PROVEN — quoted count=0 AND re-issue count=0 (`Q_ABSENCE_UNPROVEN`)

**E-gate (extraction)** — active whenever a facts index is supplied (sequential grade-case and batch grade both supply it; `facts_index=None` = legacy grading, gate off):
- `E_NO_EXTRACTION` — the extraction record (`facts-index.md`) is empty: no clauses were extracted at all (fails every case)
- `E_NO_INGEST` — FIRST case only, when the index is non-empty: the case window must show real ingestion (≥1 `ARCHIVE-OK` AND ≥1 `BRIDGE-PERSIST-OK` receipt) — after a DAS cleanup, later cases may legitimately reuse already-persisted facts without new writes. If both receipts are missing from the (lossy) history, the facade-log attestation lane may prove the ingest instead (informational `E_INGEST_ATTESTED_VIA_FACADE_LOG`)
- `E_NO_FACTS` — knowledge case block has no `FACTS:` line (unsolvable exempt)
- `E_FACTS_NOT_IN_INDEX` — a `FACTS:` line expression is not verbatim (whitespace-normalized) in the extraction record
- `E_LITERAL_NOT_EXTRACTED` — a quoted literal of the executed query does not come from the extracted predicate vocabulary (unsolvable exempt; only checked when a QUERY line exists). This is the extracted-predicate-awareness rule: queries must REUSE the exact extracted spellings — a reformulated query matches nothing and produces a false absence (mechanical trap)

**P-gate (provenance):**
- knowledge cases must cite `git:<40hex> <url>` sources (`P_MISSING`; unsolvable exempt)
- every citation resolves in the provenance repo: commit exists → exactly one `sources/` blob among its changes → `index.jsonl` at that commit has an entry for that blob path → sha256(blob at that commit) == entry.blob_sha256 → entry.url == cited url (`P_UNRESOLVED:<COND>` with COMMIT_NOT_IN_REPO, COMMIT_UNREADABLE, COMMIT_NOT_AN_ARCHIVE_COMMIT, COMMIT_MULTIPLE_SOURCE_BLOBS, INDEX_UNREADABLE_AT_COMMIT, INDEX_ENTRY_MISSING_FOR_BLOB, BLOB_UNREADABLE_AT_COMMIT, BLOB_SHA_MISMATCH, URL_MISMATCH)
- the harness also resolves every `git:<sha>` the agent persisted in-window (add-atom calls in the window) and records the results; only citations on the case's SOURCES line can fail the gate

## Harness-side Attestation Lanes (informational)

**The history channel is known-lossy:** an upstream PeTTa defect (superpose/collapse) collapses tool tuples in `history.metta` to `$_`, so history evidence can silently vanish even when the tool call really happened. Receipts must therefore be echoed to durable files (facts-index.md, answers.md) at once, and the harness keeps two independent, tamper-resistant log lanes (docker logs, window = [case setup restart, grade time]):

- `Q_ATTESTED_VIA_ACCESS_LOG` — when the quoted query is absent from the window history: the query-engine log carried the exact pattern (space-stripped comparison) in the window AND the read-proxy access log shows ≥1 successful `POST /v1/query` from the agent container IP. Replaces blocking `Q_NOT_IN_HISTORY`.
- `E_INGEST_ATTESTED_VIA_FACADE_LOG` — first case with no persist/archive receipts in the window: the write-bridge facade log shows ≥1 successful `POST /v1/write` AND ≥1 `POST /v1/archive` from the agent IP. Replaces blocking `E_NO_INGEST`.

Verdict logic is unchanged: informational conditions never fail a case; receipt, re-issue, degenerate and provenance checks still apply.

## cleanup-das Phase (v3)

Runs BEFORE the test so prior-run benchmark predicates do not contaminate counts. Discovers benchmark residue in the DAS mongo store with two read-only nets (union):

- **N1 (provenance):** links whose `custom_attributes.provenance_url` matches the benchmark source URL base — every facade add-atom write is provenance-decorated, so this catches all agent-written benchmark facts, old and new.
- **N2 (literal):** links whose `custom_attributes.metta_expression` contains a high-confidence benchmark-ONLY literal (windowless-room, sloped-ceiling, observer-inside-room, ...; full set in `run_benchmark.py`). Generic words plausible in campaign atoms are deliberately excluded, as are generic meta-reasoning spellings (undecorated writes are impossible anyway — the facade always decorates).

Each discovered expression is deleted via the write-bridge `cleanup.py --metta <expr>` — **links-only, NEVER `--delete-nodes`** (symbol nodes are shared across the campaign DB). Deletion is eventual; the bridge oracle (alternate-pattern absence check + bounded standby) handles it. Zero residue is proven by re-running the discovery nets (must come back empty).

**Canaries:** `(Inheritance (Concept "Fetch.ai") $X)` — a live campaign atom, deliberately NOT benchmark vocabulary — is queried before and after; counts must be unchanged and ≥ 1. Non-empty residue or changed canary counts → exit 1 (harness error, aborts the sequential run). Artifacts: `results/<run-id>/cleanup-das.json` (mongo counts, discovered expressions, per-expression cleanup results, canaries, remaining, `canaries_intact`).

## P-gate Blob Reconstruction Lane

For every `git:<sha>` citation on a case's SOURCES line, the grader reconstructs the archived source blob from the provenance repo (`provenance_check.reconstruct_citation_blob`: commit → its one `sources/` blob → `git show`), byte-compares it against the repo's background markdown (`tests/reasoning-windowless-room/background/<url basename>`, `matches_repo_file`), and persists the reconstructed bytes under `results/<run-id>/reconstructed/`. Recorded per citation in the grade-case JSON and the report. This is an evidence lane, not an extra blocking condition: a tampered blob already fails the P-gate sha256 check (`BLOB_SHA_MISMATCH`); the byte-compare additionally proves the archived bytes are exactly the background markdown the agent's reasoning was extracted from.

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

Sequential mode renders each case's `question` (facts.py) into the per-case prompt.

## Answers.md Contract (v3)

Per case, the gate parses blocks of exactly this shape (deviation = FAIL):

```
### CASE <id>

QUERY: <the exact metta pattern you executed>
DAS_RETRIEVE_OK untrusted=true count=<n> truncated=<bool> results=[...]
FACTS: <extraction-record expressions used, semicolon-separated>
REASONING: <short trace>
FINAL ANSWER (<id>): <answer>
SOURCES: git:<40-hex-sha> <source-url> [git:<40-hex-sha> <source-url> ...]
```

- `FACTS:` is required for knowledge cases (E-gate); the unsolvable case is exempt.
- `SOURCES:` is required for knowledge cases; the unsolvable case may cite none.
- Backward compatibility: bare `FINAL ANSWER (case):` lines still parse, but they fail the Q/P gates (and, for knowledge cases, the E-gate's FACTS check).

## The Benchmark Prompt (v3)

Per-case template (`agent_prompt_template.md`), de-leaked: **no example queries, no per-case answer guidance** — the query grammar lives in the das-retrieve skill description (Environment Requirements), and the agent must extract its own predicates. The template carries the **convergence rules** (root cause wr3-2026-10-23: per-case restarts wipe episode context and history `$_`-collapse hides prior work — the agent re-archived the same 5 sources ~5× and timed out in a memory-churn loop):

1. **Record-driven ingest:** read the extraction record (`facts-index.md`) FIRST; reuse recorded shas/expressions; never re-archive or re-write what the record already lists.
2. **Immediate receipt echo:** append every receipt, expression, and query (with its count) to the extraction record immediately, one append per tool result — the record is the agent's working memory across wake cycles.
3. **Answer immediately after the query:** write the case's answer block right after the query, then STOP — one case per cycle, no batch writes, no re-verification of recorded steps.

The extraction record doubles as the query vocabulary: the exact predicate names and literal spellings to REUSE VERBATIM when querying (E_LITERAL_NOT_EXTRACTED enforces this mechanically).

## Canonical-Fact Model

- **Agent-extracted (primary):** the agent derives and persists its own predicates with provenance.
- **Seed-canonical (oracle mode):** `CANONICAL_FACTS` in facts.py remains the design-time oracle for coverage diffing. The `--seed-canonical` flag is retained for CLI compatibility but is currently a NO-OP in the harness (the v2 seeding code was removed); it is not the default test mode and must not be relied on.

## Provenance Chain

background file → raw URL → `/v1/archive` (AGENT-initiated in sequential mode via archive-source; harness-initiated in batch) → git commit (ARCHIVE-OK) → add-atom suffix → DAS atom (BRIDGE-PERSIST-OK verified) → extraction record + quoted evidence in answers.md → **resolved against the provenance git repo by the grader** → **blob reconstructed and byte-compared against the repo background markdown**.

## Determinism Guarantee

Grading uses regex/keyword parsing, string matching, deterministic HTTP re-issue against the read-proxy, read-only git commands, and docker-log reads (attestation). **No LLM is invoked anywhere in the harness.** The same inputs always produce the same verdict.

## Report Schema

`results/<run-id>/`:

- `grade-case-<case>.json` (sequential): run_id, case_id, verdict, conditions, detail, history_window {mode, retrieve_calls, retrieve_args, placeholder_calls, persist/archive receipts, add_atom_shas}, facts_index_size, attestation, citations, reconstruction, timestamp.
- `grade.json`: run_id, mode (sequential|batch), gate_verdict, cases_passed/total, per_case {verdict, conditions[]}, timestamp.
- `report.json`: run_id, grade, per-case grade-case files (rich detail), cleanup summary, timestamp.
- `windows/<case>/{pre,post}.metta` — per-case history snapshot copies (kept after teardown).
- `reconstructed/` — reconstructed citation blobs.
- `cleanup-das.json`, `preflight.json`, `setup-case-*.json`, `agent-case-*.json`, `teardown.json`.

`report.md`: gate verdict header, per-case table (Case | Verdict | Conditions | Attested | Reconstruction), cleanup summary line, condition-code reference (A_* answer, Q_* query-first with the informational note, E_* extraction, P_* provenance).

## Environment Requirements (v3)

The gate is only meaningful on an environment that passes these; preflight checks what it can mechanically:

1. **das-retrieve skill description upgrade** (`deploy/omega/plugins/das-read`): the baked one-line description states neither WHY, WHEN, nor the engine's query grammar (live evidence wr-20261021-2355: the agent never called das-retrieve spontaneously and fabricated meet-form queries that return count=0). The plugin re-registers the skill with the WHY/WHEN/HOW contract: DAS as the only trusted source; call FIRST and to prove absence; query grammar (one parenthesized link expression; reuse exact extracted spellings; ground one argument with a quoted literal + bind one target with a $variable; keep stored arity/shape and direction; probe the complementary direction before concluding absence; no meet-forms; count=0 = absent OR wrongly-shaped). Examples deliberately use NON-benchmark vocabulary. Preflight: `skill_description_upgraded`.
2. **pin working-memory plugin** (`deploy/omega/plugins/pin`): the stock pin skill is a NO-OP STUB (`(= (pin $x) PIN-SUCCESS)` — it discards the item while its description promises working memory; contributed to the wr3 re-ingest churn). The plugin rebinds pin to `(add-prompt-extension $x $x)` so pinned items re-appear in EVERY following prompt of the run (cross-cycle working memory; not durable across restarts — durable memory is DAS + memory-volume files). Validated by the das-read plugin validation driver (PROBE-5/PROBE-6: pin then read back prompt extensions; single-definition dedup).
3. **chroma_db memory dir:** the image's `/PeTTa/chroma_db` symlink dangles → `Knowledge init failed` at every boot (live evidence wr3-20261023). Fixed by creating `<memory-volume>/chroma_db` (owned 65534:65534) as a volume dir. Preflight: `chroma_memory_dir`.
4. **Canary probe:** the campaign atom `(Inheritance (Concept "Fetch.ai") $X)` must resolve (count ≥ 1) before the run — campaign atoms intact; also the cleanup-das canary. Preflight: `canary_fetch_ai`.
5. **Fresh run-id:** `prompt.txt.bak-pre-benchmark-<run-id>` must not pre-exist (a stale backup would restore the wrong standby prompt). Preflight: `prompt_backup_fresh`.

## Deployment Invariants

1. Read-proxy: variable-form patterns only (ground patterns hang/400).
2. Agent restart: systemd, NEVER docker restart (start.sh trap rm -f's the container).
3. Receipts: `BRIDGE-PERSIST-OK verified=` (write), `ARCHIVE-OK` (archive), `DAS_RETRIEVE_OK count=` (retrieve) are the only success signals.
4. Memory-volume and provenance-repo operations need sudo (root-owned / 65532-owned).
5. Benchmark dir must be chowned 65534:65534 (agent runs as nobody:nogroup).
6. DAS deletion is links-only, NEVER `--delete-nodes` (symbol nodes are shared across the campaign DB).
7. Campaign/canary atoms must be untouched by any test cleanup (canary counts before/after).
8. The history channel is known-lossy (tool tuples collapse to `$_`): receipts must be echoed to durable files at once; attestation lanes exist for the collapsed-evidence case.

## Requirement Reconciliation (v3)

Contradictions between this spec at v2 and (a) the v3 directive / original requirements, or (b) the current code — all resolutions applied in this revision:

1. **Scope vs v3 directive.** v2: "Out of scope: modifying the agent's code/configuration". The v3 directive explicitly authorizes agent-side skill/plugin changes (das-read description, pin rebind). **Resolution:** scope now separates repo-deployed agent-environment configuration (in scope, pre-validated) from harness runtime writes (still test-controlled files only). Applied.
2. **Harness-archived background vs agent-driven ingest.** v2 setup: "archive the 5 background sources (POST /v1/archive → ARCHIVE-OK shas)". Sequential mode does NOT pre-archive; ingestion is the agent's job, verified by E_NO_INGEST. **Resolution:** sequential flow documented as agent-driven; harness archiving kept under `--batch`. Applied.
3. **Agent-phase shape.** v2: "poll for all 7 FINAL ANSWER lines (default timeout 60m)". Sequential default is per-case polling at 45 m. **Resolution:** both documented under Modes/Phases. Applied.
4. **Pre-snapshot refusal.** v2: grade "refuses to grade without a usable pre-snapshot". True for grade-case (no pre-case snapshot → harness error); the batch `grade` no longer refuses — it falls back to window mode `full` (whole history as window, recorded in the report). **Resolution:** spec states the per-case refusal and documents the batch fallback. Applied. (Maintainer note: restore the batch refusal if offline re-grade strictness matters.)
5. **Teardown `--cleanup`.** v2: teardown has "optional --cleanup (links-only, NEVER --delete-nodes)". The flag is no longer honored (accepted by the CLI, unused); DAS cleanup moved to the pre-run cleanup-das phase. **Resolution:** teardown description updated; cleanup-das section added. Applied.
6. **`--seed-canonical`.** v2: "harness seeds CANONICAL_FACTS". The seeding implementation was removed in v3; the flag is a no-op. **Resolution:** Canonical-Fact Model section states this. Applied. (Maintainer note: remove the flag or restore the seeding.)
7. **Answers.md contract.** v2 block shape lacks `FACTS:`; the E-gate requires it for knowledge cases. **Resolution:** contract updated to v3. Applied.
8. **Q_NOT_IN_HISTORY absolutism.** v2: fabricated quotes fail unconditionally. The attestation lane can substitute log proof (informational). Also v2 omitted the knowledge-case count=0 → `Q_ABSENCE_UNPROVEN` rule that the code already enforced. **Resolution:** both documented. Applied.
9. **Gate wording.** v2: "A case PASSES only if ALL conditions hold" — with informational conditions the rule is "no blocking conditions". **Resolution:** wording updated. Applied.

## History

- v1 (2026-10-21): scored benchmark; live run wr-20261021-2355 — 7/7 substantively correct, 1/7 trace-PASS (no real das-retrieve calls; answers from context).
- v2 (2026-10-22): re-scoped to strict gating test per Balazs's directive; condition codes, degenerate-trace conditions, provenance git resolution, deterministic grading, signal exit codes.
- v3 (2026-10-23): sequential standalone-question default (per-case phases, `--cases`, `--batch` kept); E-gate (extraction) + `FACTS:` line; attestation lanes (`Q_ATTESTED_VIA_ACCESS_LOG`, `E_INGEST_ATTESTED_VIA_FACADE_LOG` — informational; lossy history channel stated); cleanup-das pre-run phase (two discovery nets, links-only, canary-proof); P-gate blob reconstruction lane; environment requirements (das-read skill description upgrade, pin rebind, chroma_db dir) with preflight checks; de-leaked per-case prompt with convergence rules (wr3-20261023 root cause: restart-wiped episode context + `$_`-collapse → re-archive churn loop).
