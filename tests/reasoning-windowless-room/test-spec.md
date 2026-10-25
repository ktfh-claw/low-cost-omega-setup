# Windowless Room Gating Test — Test Specification (v6)

## Overview

This specification defines the windowless-room **gating test** for the Omega agent (DAS-backed persistent-knowledge agent on the OVH server). v2 re-scoped the test from a scored benchmark to a strict pass/fail GATE that verifies the environment is set up for DAS-grounded reasoning governance: the agent must answer **query-first** (real `das-retrieve` calls before every answer) with **provable provenance** (every citation resolves to the provenance git repo), and the harness must grade **deterministically with zero LLM interaction**.

v3 (2026-10-23 directive) makes **sequential standalone-question mode the default** — one prompt = one question, graded independently — and adds: an **E-gate** on clause extraction, harness-side **attestation lanes** for the known-lossy history channel, a pre-run **cleanup-das** phase, **blob reconstruction** back to the source markdown bytes, and explicit **environment requirements** (das-retrieve skill-description upgrade, pin working-memory plugin, chroma_db memory dir). `--batch` keeps the v2 all-at-once flow.

v4 (2026-10-24 directive, wr3b post-mortem levers 3+4) adds the **per-case history trim** and lengthens the per-case window to **75 minutes** (default). Root cause of all four wr3/wr3b timeouts: the stock agent serializes the WHOLE day history (~1.6 MB / ~32k prompt tokens) into EVERY LLM request, starving the per-case cycle budget — the skill/formulation layer was fixed in v3 (real queries, extraction, persistence all landed) but the terminal answer-block write never landed inside a 45-minute window. Lever 3: `setup-case` archives the current history to the pre-case snapshot, then resets `history.metta` to a comment-only window marker — every LLM call of the case then serializes only that case's episodes. Strict gates are unchanged; the window fallback (`mode "full"` = current file content = this case's episodes only) is by design and recorded per case. `--no-trim-history` keeps the v3 behavior.

A gate FAIL is a valid, expected signal: it means the environment/agent did not meet the governance bar — not that the harness is broken.

## Scope

- **In scope:** background ingestion (agent-driven in sequential mode), fact extraction + persistence with provenance, query-first answering, strict deterministic grading (A/Q/E/P gates), harness re-issue verification, provenance git resolution + blob reconstruction, harness-side log attestation, pre-run DAS residue cleanup, reporting, teardown, exit-code signaling, and **agent-environment configuration deployed from this repo** (das-retrieve skill description upgrade, pin plugin rebind, chroma_db memory dir) — explicitly authorized by the v3 directive.
- **Out of scope:** LLM-based grading (forbidden), subjective assessment. At run time the harness modifies only test-controlled files (prompt.txt, omega_state.md, benchmark/ inside the memory volume) — plus, in v4, the **per-case history trim**: history.metta is reset to a comment-only marker before each case window and restored byte-identically from the run-start backup at teardown (no-trace contract; prior content is always archived in the pre-case snapshots + `results/<run-id>/history.pre-run.metta` before any reset). The trim is the wr3b post-mortem lever 3, explicitly authorized by the 2026-10-24 directive; `--no-trim-history` restores the v3 file-touch set exactly. Agent plugin/skill configuration is deployed and validated before the run (preflight + the das-read plugin validation driver), never edited by the harness mid-run.

## Modes

### Sequential standalone-question mode (v3 default)

One prompt contains exactly ONE case question. The harness drives the sequence; each case runs the per-case phases and is graded independently:

1. **setup-case** — prepare the benchmark dir (background files + urls.txt, idempotent); at RUN START (the first setup-case of this run-id, whichever case id that is — a continuation run via `--cases` starts mid-sequence) back up prompt.txt / omega_state.md (`*.bak-pre-benchmark-<run-id>`) and, with the trim enabled, the FULL pre-run history (`history.bak-pre-benchmark-<run-id>`); on the first case `original` additionally initialize fresh `answers.md` + `facts-index.md`; chown benchmark/ to 65534:65534. Then for EVERY case: snapshot `history.pre-case-<run-id>-<case>.metta` (the case's window start), **trim history.metta to the per-case window marker** (v4, default; `--no-trim-history` keeps the v3 full-history behavior), render + install the per-case prompt, write the benchmark `omega_state.md` (case marker), restart the agent. The trim never runs without the snapshot: the pre-trim content is always archived first.
2. **agent-case** — poll `answers.md` every 30 s for this case's `FINAL ANSWER (<case>):` line (default timeout 75 m, v4; was 45 m); on completion OR timeout snapshot `history.post-case-<run-id>-<case>.metta` (window end). A timeout is a case failure, not a harness error — the case is graded anyway (it will fail its gates).
3. **grade-case** — the independent A/Q/E/P gate for this case (details below). Window = the case's pre/post snapshots. Refuses to grade without the pre-case snapshot (window undefined = harness error). Attestation + reconstruction lanes run here.

Sequential-mode properties:

- **Agent-driven ingestion.** The harness does NOT archive the background sources; the agent must ingest them itself (archive-source → ARCHIVE-OK; add-atom → BRIDGE-PERSIST-OK). The E-gate's first-case ingest check (below) verifies this actually happened.
- **Independent grading.** Every case is graded regardless of the previous case's verdict; the sequence continues after a FAIL. Overall gate: PASS iff every selected case passes and no harness error occurred.
- **`--cases` subset filter** (iteration mode): relaunch only the cases under test, e.g. `--cases original,uncertainty`. Unknown ids are a harness error.
- The first case in `facts.TEST_CASES` order (`original`) is the ingest-required case (E-gate).
- **Per-case history trim** (v4). With the trim enabled (default), grading's window mode for a trimmed case falls back to `full` — the whole live history.metta at grade time, which after the trim contains ONLY this case's episodes (plus the comment-only marker, which parses as zero retrievals/receipts/shas). This is the designed window semantics under the trim; `mode` is recorded per case in the grade-case JSON. Continuation runs (`--cases` without `original`) preserve the accumulated answers.md/facts-index.md (cross-case carry-over) but still create run backups at their first setup-case.

### Batch mode (`--batch`, v2 flow, kept)

Single prompt with all 7 questions (`prompts.txt`, rendered per-case sections); phases: preflight → setup (harness archives the 5 sources via POST /v1/archive) → agent (poll for all 7 answers, default timeout 60 m) → grade (all cases against one benchmark window) → report → teardown.

## Test Structure — Phases

Orchestrated by `run_benchmark.py` (phases independently runnable over SSH):

1. **preflight** — verify environment: containers running (write-bridge, read-proxy, query-engine, mongodb, agent); dynamic IP resolution; write-bridge smoke write (+ links-only cleanup of the smoke fact); read-proxy variable-form query; provenance repo reachable via sudo; memory volume present; plus v3 checks: `prompt_backup_fresh` (per-run backup must not pre-exist — fresh run-id rule), `skill_description_upgraded` (das-retrieve description contract present in the mounted plugin), `chroma_memory_dir` (volume chroma_db dir exists), `canary_fetch_ai` (canary count ≥ 1 — campaign atoms intact).
2. **cleanup-das** (v3) — remove previous-run benchmark residue from the DAS mongo store (details below). Runs BEFORE the test (default in `full`; `--no-cleanup` skips by pre-creating its result marker).
3. **setup-case / agent-case / grade-case** (sequential default) — per-case phases as above.
4. **report** — assemble `results/<run-id>/report.json` + `report.md`; print; return the gate signal.
5. **teardown** — contamination guard (refuses to restore a backup prompt that still contains BENCHMARK MODE content, unless `--allow-dirty-backup`); restore standby prompt + truthful omega_state.md; **restore the pre-run history from `history.bak-pre-benchmark-<run-id>`** (v4: archives it to `results/<run-id>/history.pre-run.metta` first, then restores the volume file and removes the backup — the per-case trims leave no trace; no backup = no-trim run = nothing to restore); restart; remove the per-case history snapshots from the volume (copies are kept under `results/<run-id>/windows/<case>/`; `--keep-snapshots` preserves them). DAS cleanup is NOT part of teardown anymore — it moved to the pre-run cleanup-das phase (teardown's legacy `--cleanup` flag is not honored).
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

**R-gate (reasoning trace)** — the REASONING line must carry the formalized MeTTa reasoning trace, NOT generated prose (2026-10-24 directive: the standard the 2026-10-20 report campaign proved — every step grounded in atoms/predicates retrieved from DAS). v7 (2026-10-25): the reasoning must additionally have been EXECUTED — hand-composed truth values do not count (scenario A/A2 lesson):
- `R_MISSING` — case block has no `REASONING:` line
- `R_NOT_METTA` — the trace has fewer than 2 steps or contains prose segments
- `R_NOT_EXECUTED` — no interpreter `(stv ...)` evidence: neither an `exec <call> => <output-with-stv>` line in the extraction record nor an `(stv ...)` output quoted in the trace itself. Unsolvable cases are exempt (absence probes have no derivation to execute)
- Shape: semicolon-separated s-expressions; the FIRST step must be the question clause (the exact executed query, whitespace-normalized); middle steps must be existing atoms — expressions verbatim (whitespace-normalized) in the extraction record (`R_STEP_NOT_IN_INDEX`) or executed-derivation outputs from the record's `exec` lines; the final step may be a derived conclusion whose quoted literals all come from the extracted vocabulary or the query (`R_LITERAL_NOT_EXTRACTED`)
- The unsolvable case keeps the shape requirements (question clause + absence probes) but is exempt from index grounding (no facts to ground against)
- Zero LLM: trace parsing, exec-record parsing, and grounding are pure string/set operations

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

## Answers.md Contract (v5)

Per case, the gate parses blocks of exactly this shape (deviation = FAIL):

```
### CASE <id>

QUERY: <the exact metta pattern you executed>
DAS_RETRIEVE_OK untrusted=true count=<n> truncated=<bool> results=[...]
FACTS: <extraction-record expressions used, semicolon-separated>
REASONING: <the executed MeTTa reasoning trace — question clause; fact steps; executed derivation steps with interpreter (stv ...) outputs — semicolon-separated s-expressions, NOT prose>
FINAL ANSWER (<id>): <answer>
SOURCES: git:<40-hex-sha> <source-url> [git:<40-hex-sha> <source-url> ...]
```

- `FACTS:` is required for knowledge cases (E-gate); the unsolvable case is exempt.
- `REASONING:` is required for every case (R-gate): a semicolon-separated MeTTa trace — first step = the executed question clause, then verbatim extraction-record fact steps, then the executed derivation steps with their interpreter `(stv ...)` outputs. Prose (scene descriptions, narrative text) fails (`R_NOT_METTA`). No interpreter `(stv ...)` evidence anywhere (record `exec` lines or trace-quoted outputs) fails (`R_NOT_EXECUTED`). The unsolvable case is exempt from execution evidence and index grounding but still needs the trace shape (question clause + absence probes).
- `SOURCES:` is required for knowledge cases; the unsolvable case may cite none.
- Backward compatibility: bare `FINAL ANSWER (case):` lines still parse, but they fail the Q/R/P gates (and, for knowledge cases, the E-gate's FACTS check).
- Block-line parsing is line-anchored (`QUERY:`/`FACTS:`/`REASONING:`/`SOURCES:` labels match horizontal whitespace only; an empty value is a genuinely empty value, not the next line's content).

## The Benchmark Prompt (v6)

Per-case template (`agent_prompt_template.md`), de-leaked: **no example queries, no per-case answer guidance** — the query grammar lives in the das-retrieve skill description (Environment Requirements), and the agent must extract its own predicates. v6 restructures the prompt per the 2026-10-24 19:50 UTC directive (wr3d forensics: all cycles prompt-work, the open-ended ingest/study loop saturates every window — steps after it are starved):

**Deliverable-first:** the case is decided by exactly two artifacts — the MeTTa reasoning trace (REASONING: line) and the answer block — stated at the top of the prompt.

**Fixed pipeline, no open-ended study:** the TASK LIST is a closed 5-step pipeline; there is NO research/study step. Each step runs exactly once, in order:
1. **EXTRACT** — ONE bounded pass over the background sources: per file, skip-if-recorded (record lists `git:<sha>`), else read ONCE → archive → persist clauses → record → move on; no re-reading a processed file, no summarizing/analysis (record-driven ingest and immediate receipt echo are folded into this step; the v3 relevance-decision "the sources you will actually use" is GONE — the pass is unconditional).
2. **FORMALIZE** the question as one MeTTa clause (record vocabulary, verbatim spellings).
3. **RETRIEVE** — das-retrieve with the QUERY, receipt + `query <pattern> count=<n>` appended to the record.
4. **EXECUTE THE REASONING** (v7) — run the derivations via the metta skill under the 2-argument NAL/PLN contract (metta-grammar plugin carries the operator grammar in the skill description); chain calls by feeding each derived output into the next call's premises; append `exec <call> => <output-with-stv>` to the record after EVERY successful call (the atomspace is ephemeral — unpinned results are lost next cycle); compose the trace (question clause; verbatim record fact steps; executed derivation steps with their interpreter stv outputs) and persist it as a `trace:` line.
5. **WRITE the answer block** (v7: deliverable-first) — IMMEDIATELY after appending the trace, before any message or other work, then STOP; later wake cycles that find the block appended must do NOTHING (idle-silently discipline — the STOP rule forbids re-sends, re-verification, and rewrites on completion).

**Campaign anti-loop rules:** no background re-read after first pass; when unsure, the next undone TASK LIST step — never "study more first"; one case per cycle. The extraction record remains the working-memory prosthesis (per-case restarts + `$_`-collapse) AND the grounding set for the E/R gates. Unit-pinned by `unit/test_v6_prompt.py` (pipeline order, deliverable-first, no-study invariants, block/trace contracts).

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

## Requirement Reconciliation (v4)

1. **Scope vs the history trim.** v3 scope: "the harness changes only test-controlled files (prompt.txt, omega_state.md, benchmark/)". The v4 lever-3 trim resets history.metta — an agent-owned file — before each case window. **Resolution:** scope updated (trim + no-trace contract documented); authorized by the 2026-10-24 directive; the pre-trim content is always archived (pre-case snapshot + run-start backup + results copy) and teardown restores the pre-run bytes. Applied.
2. **Per-case window length.** v3: "default timeout 45 m". The wr3b post-mortem showed the 45-minute cycle budget insufficient even with the v3 skill/prompt fixes fully working (queries, extraction, persistence, verification all landed; only the terminal answer write did not). **Resolution:** default raised to 75 m (lever 4, harness parameter only — strict gates unchanged; `--timeout-minutes` overrides). Applied.
3. **Window semantics under the trim.** v3 defined the case window as the pre/post-snapshot slice of a monotonically growing history. With the trim, the live history at grade time starts with the marker, so the pre-case snapshot is no longer a prefix → grading falls back to window mode `full`, which is EXACTLY this case's episodes (by design, not data loss). **Resolution:** Modes section documents the fallback as the designed v4 window semantics; the comment-only marker contributes zero retrievals/receipts/shas (unit-tested). Applied.

## Requirement Reconciliation (v5)

1. **Lever-1/2 vs the reasoning-trace standard.** The wr3c close-out recommended lever 1 (facts-index append coupled into the persist step) and lever 2 (answer-block reordering). The 2026-10-24 15:40 UTC directive REJECTED both: "not the right direction" — the purpose of the end-to-end test is redefined as a reusable, redeployable verification standard for Omega+DAS reasoning (anyone redeploying this exact configuration can run the test and verify the reasoning feature is in place). **Resolution:** levers 1–2 not implemented; instead the campaign-grade reasoning-trace standard is formalized as the R-gate + prompt step 4. Applied.
2. **REASONING line semantics.** v3/v4 contract: `REASONING: <short trace>` — free-form, ungraded. The directive requires the `REASONING:` part to contain the MeTTa reasoning trace (question clause → fact steps → derived conclusion), every step grounded in existing atoms/predicates retrieved from DAS — generated prose fails. **Resolution:** Answers.md Contract v5 defines the trace form; `grading.py` enforces it deterministically (`parse_reasoning_trace`, grounding against the extraction record). Applied.
3. **Why the campaign needed no facts-index.** Campaign-config reconstruction (2026-10-24): the 2026-10-20 report campaign had NO facts-index.md — a single continuous process (no per-case restarts → no episode-context wipe → no re-ingest churn), working memory = the v7 prompt itself + the report files the agent wrote + das-retrieve receipts quoted into them; the report phase was read-only over pre-persisted facts (0 write-bridge POSTs, mongo static). The benchmark's facts-index.md (v3) exists to compensate for harness-imposed per-case restarts + history `$_`-collapse — problems the campaign never had. **Resolution:** facts-index.md retained (it is the working-memory prosthesis for the sequential restart design AND the R-gate grounding set); documented so the divergence from the campaign is understood, not accidental. Applied.
4. **Line-anchored block parsing.** The `QUERY:`/`FACTS:`/`REASONING:`/`SOURCES:` line regexes used `\s*` which matches newlines — an empty value captured the NEXT line's content (live evidence: an empty `FACTS:` line captured the `REASONING:` line, masking `E_NO_FACTS`). **Resolution:** all four regexes are now horizontal-whitespace-anchored (`[ \t]*`); unit tests cover the empty-value paths. Applied.

## Requirement Reconciliation (v6)

1. **Prompt structure vs wr3d live evidence.** v5 placed the reasoning-trace step before the answer write but AFTER the conditional ingest block; wr3d forensics showed all ~177 cycles consumed by open-ended background study/re-reading — steps downstream of the study loop are starved in every window (the same convergence-ordering blocker, now conclusively prompt-structural). The 19:50 UTC directive applied both monitor recommendations — campaign-style pinned task structure (v7-rule-1 analog) AND moving the reasoning-trace + answer-write to the top as deliverables. **Resolution:** v6 template = deliverable-first + fixed 5-step pipeline with the study step removed entirely (extraction is one unconditional bounded pass; the record-driven skip rule replaces the v3/v5 relevance decision). Unit-pinned in `test_v6_prompt.py`. Applied.
2. **Open-ended ingest removed.** v5 step 2 ("Ingest + persist only if needed") required the agent to DECIDE which sources the question needs — a decision the agent never terminates on (wr3/wr3b/wr3c/wr3d all show the same non-termination). The directive: "I don't think it needs any step with an open-ended study… just a simple extract of the reasoning traces… then formalize the question and answer with the reasoning trace." **Resolution:** EXTRACT is unconditional and single-pass (skip only on already-recorded); no relevance judgment exists anywhere in the pipeline. Applied.
3. **Contract stability.** The answers.md block contract, R-gate grounding rules, E-gate record discipline, and the das-retrieve grammar are UNCHANGED from v5 — v6 reorders and bounds the agent-side workflow only; no harness grading code changed. **Resolution:** `test_v6_prompt.py` additionally pins the block/trace contracts verbatim to catch accidental drift. Applied.

## Requirement Reconciliation (v7)

1. **Executed vs composed reasoning.** Scenario A (2026-10-24/25) proved the agent can compose valid campaign-grade traces as text while the interpreter path also executes — but scenario A2 (2026-10-25) showed the agent's file artifacts can claim "no stv obtained" while the log shows 39 real derivations: executed reasoning that never reached the deliverable. The 10:57 UTC directive ("make sure we build in these findings to the e2e wr3 tests") requires the e2e standard to demand EXECUTION, not composition. **Resolution:** `R_NOT_EXECUTED` gate (exec-record lines or trace-quoted stv outputs; unsolvable exempt); prompt step 4 renamed EXECUTE THE REASONING with the 2-arg operator contract and `exec` record discipline; executed-derivation outputs count as grounded trace steps. Applied.
2. **Deliverable priority (A2 defect 1).** A2's answer.md was never written — the Telegram send was treated as the deliverable. **Resolution:** step 5 orders the answer-block write FIRST ("before any message or other work"); pinned by `test_step5_deliverable_first_write`. Applied.
3. **Stop-rule binding across wakes (A2 defect 2).** A2 re-sent an idle Telegram on every ~3-min wake after completion. **Resolution:** the STOP rule now forbids sends/verification/rewrites on later wakes and demands silent idling; pinned by `test_stop_rule_idle_discipline`. (Behavioral enforcement remains probabilistic — the gate measures artifacts, not wake behavior; the discipline is prompt-level.) Applied.
4. **Skill grammar as environment requirement.** The metta 2-arg contract is a deployment artifact (metta-grammar plugin), not prompt text duplicated per run. **Resolution:** preflight `metta_skill_upgraded` (repo artifact carries "STRICTLY 2-ARGUMENT") + `metta_plugin_mounted` (running container has the plugin file — the 10:04Z A2 launch failed exactly because the repo file was fine but the live start.sh lacked the mount). Applied.

## Requirement Reconciliation (v8)

1. **Cross-cycle working memory (wr3g root cause).** The wr3g run (2026-10-25) proved the v7 prompt contract reaches the agent intact but the per-wake architecture defeats it: restarts collapse prior tool results to `$_` history tuples, so every wake re-derived progress from file reads alone — 120/122 tool calls were `shell` state reads, zero DAS interactions ever started, artifacts stayed header-only through the full 75-minute window (8th consecutive genuine timeout). **Resolution (14:48 UTC directive — "build the pin ledger as v8 and restart e2e"):** the PINNED LEDGER — pinned tool output is the only tool result that survives a wake cycle, so v8 requires a mechanical ledger line (`LEDGER: step <1-5> | done: <items> | next: <ONE literal tool call>`) pinned after every tool result; first-cycle seed pins the ledger with the literal `archive-source` call for the first URL; each wake issues the `next:` call immediately instead of re-deriving from files; orientation reads bounded to ONE per cycle and only when building the next call; terminal ledger line on completion. Anti-loop unsure-resolution reroutes through the ledger's `next:` field (v6 wording updated). Pinned by `unit/test_v8_prompt.py` (9 tests). Applied.
2. **Gates unchanged.** v8 is a working-memory/prompt-side fix only; all gates (A/Q/P/E/R, attestation lanes, cleanup, trim) are byte-identical to v7 — the wr3g grade FAIL (A/Q/P/R_MISSING, facts_index_size=0) is the honest verdict of a run whose agent never acted, not a gate defect.

## Requirement Reconciliation (v9)

1. **False extraction records (wr3h root cause).** wr3h (2026-10-25) proved the ledger mechanism (v8) works — 27/27 pins carried LEDGER content, 305+ cross-cycle surfaces, `next:` calls issued — and the run made real pipeline progress (archive + persist + query receipts, ~20 recorded clauses). But the facts-index recorded ~23 expressions while ~10 (including the case-critical spatial facts) were never persisted: mongo holds zero nodes for their vocabulary, and the agent then re-queried the missing atoms to deadline (21+ identical count=0 retrieves in case 2). The index also embedded a hallucinated bulk receipt (`BRIDGE-PERSIST-OK verified=19` written as an expression line). **Resolution (20:44 UTC directive — wr3i levers ①②③):** (a) `parse_facts_index` now accepts the agent's real record shapes — `expr` labels, trailing src/git annotations, receipt suffixes — via a balanced-prefix scan (was: only bare `(...)` lines, so wr3h graded facts_index_size=0 against a 3,067 B record); (b) new informational condition `E_INDEXED_NOT_PERSISTED`: every recorded expression is probed against DAS (`index_variable_form` binds the last element to `$X` — ground patterns never complete in the pinned engine) and absent ones are listed per-expression in grade detail, making false records visible instead of misleading; (c) prompt step 1 requires ONE `expr` line per fresh receipt (`expr <expression> verified=<n>`), forbids batch recording, and names the gate's re-probe explicitly. Applied.
2. **Attested retrieve census (wr3h grader blindness).** The history channel collapses tool calls to `$_` placeholders (wr3h post-window: 100% placeholder tuples), so `retrieve_calls=0` was a channel artifact, not evidence. The attestation lane existed but was only collected when an answer block named a query. **Resolution:** attestation is now ALWAYS collected per case (query-specific `qe_pattern_match` stays conditional on the block naming a query); grade JSONs carry `attested_retrieve_calls` / `attested_write_calls` / `attested_archive_calls` alongside the history census. Applied.
3. **count=0 anti-loop bound.** wr3h case 2 looped the same zero-result query 21+ times to deadline. **Resolution:** prompt step 3 now defines the bound — `count=0` on a query whose expression the record lists as persisted means the WRITE is missing: re-persist ONCE (reuse the recorded `git:<sha>`), re-query ONCE; a second zero after exact-spelling probes in both directions is final; never issue the same query more than twice per case (also added to the hard anti-loop rules). Applied.
4. **Gates unchanged in verdict semantics.** `E_INDEXED_NOT_PERSISTED` is informational (prompt-side discipline is the fix; the gate measures artifacts), matching the established attestation-lane pattern. Verdicts for wr3h's two cases are unchanged: the answer blocks were never written.

## History

- v1 (2026-10-21): scored benchmark; live run wr-20261021-2355 — 7/7 substantively correct, 1/7 trace-PASS (no real das-retrieve calls; answers from context).
- v2 (2026-10-22): re-scoped to strict gating test per Balazs's directive; condition codes, degenerate-trace conditions, provenance git resolution, deterministic grading, signal exit codes.
- v3 (2026-10-23): sequential standalone-question default (per-case phases, `--cases`, `--batch` kept); E-gate (extraction) + `FACTS:` line; attestation lanes (`Q_ATTESTED_VIA_ACCESS_LOG`, `E_INGEST_ATTESTED_VIA_FACADE_LOG` — informational; lossy history channel stated); cleanup-das pre-run phase (two discovery nets, links-only, canary-proof); P-gate blob reconstruction lane; environment requirements (das-read skill description upgrade, pin rebind, chroma_db dir) with preflight checks; de-leaked per-case prompt with convergence rules (wr3-20261023 root cause: restart-wiped episode context + `$_`-collapse → re-archive churn loop).
- v4 (2026-10-24): wr3b post-mortem levers 3+4 — per-case history trim (run-start full-history backup, comment-only window marker, teardown byte-identical restore, `--no-trim-history` opt-out, `full`-mode window fallback documented) + 75-minute default per-case window. Root cause addressed: every LLM call serialized ~1.6 MB of day history (~32k prompt tokens) → ~100–150 useful cycles per 45-minute window, consumed by state re-reads/ingest/verification — the answer-block write never landed (4/4 timeouts across wr3/wr3b with the v3 skill layer demonstrably working). Run-start initialization is now key-agnostic (continuation runs back up without re-initializing answers.md/facts-index.md). 104 offline unit tests.
- v5 (2026-10-24): reasoning-trace standard (15:40 UTC directive — levers 1–2 rejected; the test is redefined as a reusable redeployable verification standard for Omega+DAS reasoning): R-gate added (`R_MISSING`, `R_NOT_METTA`, `R_STEP_NOT_IN_INDEX`, `R_LITERAL_NOT_EXTRACTED` — semicolon-separated MeTTa trace, first step = executed question clause, middle steps verbatim extraction-record atoms, final step may derive over extracted vocabulary; unsolvable keeps shape, exempt from grounding; zero-LLM); prompt step 4 (compose trace → record `trace:` line → paste verbatim into `REASONING:`) inserted before the answer write; block-line regexes fixed to horizontal-whitespace anchoring (empty-value capture bug). 114 offline unit tests.
- v6 (2026-10-24): wr3d close-out (case-1 FAIL — 177 cycles all prompt-work, study loop starved the trace/answer steps; case-2 aborted by operator directive in favor of the v6 iteration) → both monitor recommendations applied per the 19:50 UTC directive: campaign-style prompt (deliverable-first, fixed 5-step TASK LIST, anti-loop rules) with the reasoning-trace + answer-write as the stated deliverables, and the open-ended study step REMOVED (extraction = one unconditional bounded pass with a record-driven skip rule). Answers/facts contracts and all gates unchanged from v5. 122 offline unit tests (8 new v6 prompt-contract tests in `unit/test_v6_prompt.py`).
- v7 (2026-10-25): scenario A/A2 findings built into the e2e standard (10:57 UTC directive "build in these findings"): `R_NOT_EXECUTED` gate (executed reasoning required — interpreter `(stv ...)` evidence via the extraction record's `exec <call> => <output-with-stv>` lines or trace-quoted stv outputs; hand-composed truth values fail; unsolvable exempt); prompt step 4 = EXECUTE THE REASONING (metta-grammar plugin carries the 2-arg NAL/PLN operator contract + ephemeral-atomspace chaining; `exec` record discipline after every successful call); step 5 deliverable-first (answer block before any message — A2 wrote no answer.md); STOP rule hardened to idle-silently across wakes (A2 re-sent idle Telegrams every ~3-min wake after completion); preflight `metta_skill_upgraded` + `metta_plugin_mounted` (the 10:04Z A2 launch failed because the live start.sh lacked the plugin mount while the repo file was fine). 127 offline unit tests (2 new R_NOT_EXECUTED gate tests + 2 new prompt-contract tests + fixtures synced to the executed-trace shape).
- v8 (2026-10-25): pinned-ledger working memory (14:48 UTC directive — wr3g root cause: per-wake `$_`-collapse forced progress re-derivation from file reads; 120/122 shell reads, zero DAS calls, header-only artifacts, 8th genuine timeout): PINNED LEDGER required after every tool result (`LEDGER: step <1-5> | done: | next: <ONE literal tool call>`), first-cycle seed = ledger pin with the literal archive-source call, wake cycles issue the `next:` call immediately, one bounded orientation read per cycle max, terminal ledger line on completion; anti-loop rules reroute through the ledger; gates unchanged from v7. 136 offline unit tests (9 new v8 ledger-contract tests).
- v9 (2026-10-25): wr3h close-out levers (20:44 UTC directive — push v7/v8 approved; wr3i ①②③): bridge round-trip debug REFUTED the infra hypothesis (fresh ar2/ar3/ar4 writes all retrieve; canary=4; agent-written lighting facts retrieve — the zero-result loop was TRUE ABSENCE of never-persisted spatial facts); `parse_facts_index` accepts the real record shapes (`expr` labels, trailing annotations, receipt suffixes); new informational `E_INDEXED_NOT_PERSISTED` presence cross-check probes every recorded expression against DAS via last-element `$X` binding; attestation lane always collected with `attested_*_calls` censuses in grade JSON (history channel is 100% `$_` placeholders); prompt step 1 = one `expr <expression> verified=<n>` line per fresh receipt (no batch recording), step 3 + anti-loop = count=0 twice-is-final bound with one re-persist allowance. 149 offline unit tests (13 new v9 gate tests incl. the real wr3h facts-index fixture).