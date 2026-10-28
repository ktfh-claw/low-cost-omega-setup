# Windowless Room Gating Test — Exhaustive Gate-State Reference (v15)

Authoritative reference for every machine-readable state the harness can emit: run-level verdicts and exit codes, per-case verdicts, all condition codes (blocking and informational), attestation-lane states, and every phase-artifact JSON field. Each entry carries the **goal** of the check (why it exists) and the exact **trigger** (when it fires). Grading implementation: `grading.py` (+ `provenance_check.py`, `history_parse.py`); orchestrator: `run_benchmark.py`. Zero LLM in any grading path — everything below is regex/set/HTTP/git.

Machine states are emitted in `grade-case-<case>.json`, `grade.json`, `report.json`/`report.md`, and the phase JSONs under `results/<run-id>/`.

---

## 1. Run-level states

| State | Values | Meaning |
|---|---|---|
| `gate_verdict` | `PASS` / `FAIL` | `PASS` iff **every** case verdict is `PASS` and no harness error occurred. A FAIL is a valid, expected negative signal: the agent/environment did not meet the governance bar — not a harness bug. |
| Exit code (grade/report/full) | `0` / `2` / `1` | `0` = gate PASS; `2` = gate FAIL (expected negative); `1` = harness/environment error (answers unreadable, no usable history window, preflight failure, harness exception). |
| `cases_passed` / `cases_total` | ints | Sequential mode counts independently graded cases. |
| `per_case[case].verdict` | `PASS` / `FAIL` / `ERROR` | `ERROR` = the case never reached grading (setup phase failed); recorded in `full` mode only. |
| `mode` | `sequential` / `batch` | Sequential = one prompt, one question, per-case phases (default). Batch = v2 all-at-once flow (kept for offline re-grades). |

**Case set** (`facts.TEST_CASES`, 3 cases as of v15 — was 7 through v14): `original`, `unsolvable`, `false`. Removed cases (`uncertainty`, `true`, `easy`, `difficult`) deleted with their prompt files; gates and e2e procedure otherwise unchanged. A case PASSes iff it accumulates **zero blocking conditions** (informational conditions never fail a case — §2).

---

## 2. Informational conditions (verdict-neutral, by design)

| Code | Emitted when | Goal |
|---|---|---|
| `Q_ATTESTED_VIA_ACCESS_LOG` | The quoted query is absent from the (known-lossy) window history, but the harness-side attestation lane proves it: query-engine log carried the exact pattern (space-stripped) in the case window AND the read-proxy access log shows ≥1 successful `POST /v1/query` from the agent container IP. Substitutes for blocking `Q_NOT_IN_HISTORY`. | The history channel collapses tool tuples to `$_` (upstream PeTTa superpose/collapse defect). The evidence standard is unchanged — the query must still be proven real, now by two tamper-resistant machine logs instead of one lossy one. Receipt/reissue/degenerate checks still apply. |
| `E_INGEST_ATTESTED_VIA_FACADE_LOG` | First case only, no `ARCHIVE-OK`/`BRIDGE-PERSIST-OK` receipts in the window, but the facade log shows ≥1 successful `POST /v1/write` AND ≥1 `POST /v1/archive` from the agent IP. Substitutes for blocking `E_NO_INGEST`. | Same observability gap, ingest lane. Proves the first case really ingested when history lost the receipts. |
| `E_INDEXED_NOT_PERSISTED` | The v9 presence cross-check found ≥1 recorded index expression that resolves to zero in DAS (probe = variable form with the last element bound to `$X`). Per-expression list in `detail.index_absent`. | Makes false extraction records VISIBLE (wr3h: ~10 of ~23 recorded exprs were never persisted, the agent then re-queried the missing atoms to deadline) without failing the verdict — the discipline fix is prompt-side; the gate measures artifacts. |

`INFORMATIONAL_CONDITIONS = {Q_ATTESTED_VIA_ACCESS_LOG, E_INGEST_ATTESTED_VIA_FACADE_LOG, E_INDEXED_NOT_PERSISTED}` — verdict logic ignores exactly this set.

---

## 3. A-gate — answer substance (`grade_answer` + `llm_judge.py`, v16)

**Goal:** the final answer line must exist (deterministic parse) and be substantively correct — judged by ONE OpenAI chat-completions-compatible LLM call per case (default ASI:One `https://api.asi1.ai/v1`, model `asi1-ultra`, temperature 0 — the same API key the Omega agent uses, resolved arg > env > Omega `runtime.env`, never logged). The request is a SINGLE user message containing exactly three items: the test prompt (case question), the Omega agent's FINAL ANSWER text, and the expected correct answer. The endpoint replies TRUE or FALSE; the verdict is the first TRUE/FALSE token (max_tokens 512: a 16-token cap returned empty content with finish_reason=length on asi1-ultra — 2026-10-26 live evidence). The judge never sees the reasoning trace, receipts, queries, or citations, so it cannot reward evidence discipline it cannot see. Judge metadata (model, base_url, key_source, latency, raw reply prefix) lands in the grade JSON `detail.judge`.

**Why (directive 2026-10-26 22:56 UTC follow-up):** the v2–v14 deterministic keyword lexicons could not generalize across phrasings; the v16 single-prompt TRUE/FALSE form is the simplest general form — question + agent answer + expected answer -> TRUE/FALSE, parsed by the script and used as the blocking gate. Preflight smoke-checks the judge (fail fast before case windows burn).

| Code | Trigger | Goal |
|---|---|---|
| `A_MISSING` | No `FINAL ANSWER (<case>)` line in the case block (or no block at all) | The deliverable must exist. Also co-emitted with Q/P/R_MISSING when the whole block is absent. |
| `A_WRONG` | The judge replies FALSE for the answer line | The answer must be substantively correct for the case question. |
| `A_JUDGE_UNAVAILABLE` | No resolvable API key (arg > env > runtime.env), judge HTTP failure after one retry, empty or unparseable reply | Fail-safe: an answer that was never judged can never pass (blocking). |

**Removed in v15b/v16:** `A_SKY`, `A_FABRICATED`, `A_NO_INABILITY` (keyword-lexicon conditions superseded by the judge).

---

## 4. Q-gate — query-first evidence

**Goal:** prove the agent ASKED DAS FIRST, with a real, non-degenerate, reproducible query — no answer from parametric memory, no fabricated query quotes, no matches-anything tautology probes. The harness re-issues the query itself; a quoted count it cannot reproduce is fabricated evidence.

| Code | Trigger | Goal |
|---|---|---|
| `Q_MISSING` | No `QUERY:` line in the case block | Query-first is the core contract: an answer without a query is unverifiable. |
| `Q_NOT_QUERY_FIRST` | `QUERY:` line appears AFTER the `FINAL ANSWER` line in the block | Order matters: retrieval must precede the answer, not be backfilled. |
| `Q_PLACEHOLDER` | Query contains `$_` (or is empty) | The history-collapse placeholder is not a query; also emitted when window placeholder calls exist without a real quoted query. |
| `Q_DEGENERATE_PATTERN` | After stripping `$variables`, the query has no non-variable literal — no quoted string and no bare CONTENT symbol (structural keywords `Concept`/`Inheritance`/`Evaluation`/… never count) | A pattern like `(Evaluation $X $Y)` matches anything and proves nothing; a query must pin real content. (v10: bare content symbols count as literals, per the docstring's own contract.) |
| `Q_NOT_IN_HISTORY` | The quoted query is absent from the case-window history events — fabricated quote — AND the attestation lane did not prove it | The window (between pre/post snapshots) is authoritative: a query that never ran is fabricated evidence. Substituted by informational `Q_ATTESTED_VIA_ACCESS_LOG` when the logs prove it (§2). |
| `Q_NO_RECEIPT` | No literal `DAS_RETRIEVE_OK ... count=<n>` receipt line in the block | The retrieval must be evidenced by the tool's own success line, not narrated. |
| `Q_REISSUE_ERROR` | The harness's own re-issue of the query via the read-proxy errored | The count must be independently reproducible; an unreadable re-issue is ungradable. |
| `Q_REISSUE_MISMATCH` | Re-issue count ≠ quoted count | The quoted count must be the truth for the current store — a mismatch means the receipt was edited, stale, or fabricated. |
| `Q_ABSENCE_UNPROVEN` | Knowledge case: quoted `count=0` (a zero can't be the answer to a knowledge case). Unsolvable case: quoted ≠ 0 OR re-issue ≠ 0 (absence not proven on both sides). | For knowledge cases a zero means "wrong query or missing write", not an answer. For the unsolvable case, the negative MUST be proven by a re-issued zero — an unproven absence is indistinguishable from a broken query. |

---

## 5. E-gate — extraction record discipline

**Goal:** force a durable, persisted extraction record (`facts-index.md`) and make the agent answer strictly from recorded, persisted vocabulary — the anti-hallucination core. Active whenever a facts index is supplied (`facts_index=None` = legacy grading, gate off; `[]` = index exists but is empty). Whitespace-normalized verbatim comparisons throughout.

| Code | Trigger | Goal |
|---|---|---|
| `E_NO_EXTRACTION` | Index is empty — no clauses were ever extracted | No record = no grounded reasoning; the whole pipeline is moot. |
| `E_NO_INGEST` | FIRST case only: the window is missing a real-ingest receipt on EITHER side (`BRIDGE-PERSIST-OK` == 0 OR `ARCHIVE-OK` == 0 — both must be ≥ 1 to pass), and the facade-log attestation lane didn't prove the ingest (§2) | After a DAS cleanup the first case MUST show a real ingest; later cases may legitimately reuse already-persisted facts without new writes. |
| `E_NO_FACTS` | Knowledge case block has no (non-empty) `FACTS:` line | The answer must declare which recorded facts it used — undeclared grounding is unverifiable. (Unsolvable exempt: absence probes carry no facts.) |
| `E_FACTS_NOT_IN_INDEX` | A `FACTS:` line expression is not verbatim (whitespace-normalized) in the extraction record. Missing exprs listed in `detail.facts_not_in_index` (up to 5). | The FACTS line is a COPY of recorded `expr` lines, not a composition (v12). An expression that was never recorded is a false claim even when the answer is substantively correct — wr3k: two answer-time glosses (`ceiling → upper-interior-surface`, `windowless-room → space-bounded-by-walls-ceiling-floor`) failed an otherwise-clean case. |
| `E_LITERAL_NOT_EXTRACTED` | A quoted literal of the executed query does not come from the extracted predicate vocabulary (`detail.foreign_literals`) | Queries must REUSE the exact extracted spellings — a reformulated query matches nothing and produces a false absence (mechanical trap). (Unsolvable exempt; only checked when a QUERY line exists.) |
| `E_INDEXED_NOT_PERSISTED` | Informational (§2) | Recorded-but-never-persisted claims must be visible. |

---

## 6. R-gate — executed, grounded reasoning trace

**Goal:** the `REASONING:` line must carry the formalized MeTTa derivation — the 2026-10-24 campaign standard ("every step grounded in atoms/predicates retrieved from DAS"), EXECUTED by the interpreter (v7, scenario A/A2 lesson: hand-composed truth values don't count), and every step grounded in stored atoms (v10/v11 atom-wise grounding). Shape: semicolon-separated s-expressions, ≥2 steps, no prose; FIRST step = the exact executed query clause (whitespace-normalized).

| Code | Trigger | Goal |
|---|---|---|
| `R_MISSING` | No `REASONING:` line in the block | The trace is deliverable #1 — an answer without a trace is unproven reasoning. |
| `R_NOT_METTA` | Fewer than 2 steps, or the trace contains prose segments | Narrated scene descriptions are not derivations; the gate is zero-LLM, so the shape must be mechanically parseable. |
| `R_NOT_EXECUTED` | Knowledge case: no interpreter evidence — neither `exec <call> => <output-with-stv>` lines in the extraction record nor an `(stv ...)` output quoted in the trace itself. (Unsolvable exempt: absence probes have no derivation.) | The derivation must have RUN: composed-but-never-executed traces are exactly the A2 defect (file claimed "no stv obtained" while the log showed 39 real derivations). |
| `R_TRACE_NOT_GROUNDED` | Step 0 ≠ the exact query clause, or any non-first step fails grounding. Grounding for a step: byte-in the record/index set (recorded exprs + exec outputs) or equal to the query clause, OR (v10/v11, atom-wise for EVERY non-first step) every component atom of `call => output` is itself in the index/exec set or has quoted literals ⊆ stored vocabulary (index + query) or bare symbols ⊆ the bare-symbol vocabulary. A fabricated step needs a NEW symbol/literal — that's what fails. Unsolvable keeps the shape requirements (question clause + absence probes) but is exempt from index grounding. Flagged steps listed in `detail.trace_not_grounded` (up to 5). | Every reasoning step must trace back to retrieved/persisted atoms or interpreter products — no invented knowledge mid-trace. Step 0 must be the question itself so the trace answers the query that was actually issued. |

**Exec-output set:** `exec_outputs` = stv-carrying outputs parsed from the record's `exec` lines; count in `detail.exec_outputs`. The set is added to the index set for grounding, and its existence satisfies `R_NOT_EXECUTED`.

---

## 7. P-gate — provenance resolution (`provenance_check.py`)

**Goal:** every citation must resolve end-to-end inside the provenance git repo — no fabricated or re-paired sources. Resolution chain per citation: commit exists → readable → is an archive commit (index.jsonl among its changes) with EXACTLY ONE `sources/` blob → `index.jsonl` at that commit readable and has an entry for that blob path → blob readable at that commit → sha256(blob) == entry.blob_sha256 → entry.url == cited url. Only citations on the case's SOURCES line can fail the gate; `git:<sha>` values the agent persisted in-window are resolved and recorded but never block.

| Code | Trigger | Goal |
|---|---|---|
| `P_MISSING` | Knowledge case with no citations on the SOURCES line (unsolvable exempt) | Knowledge claims must cite their sources. |
| `P_UNRESOLVED:<sha12>:NOT_CHECKED` | The cited sha was never resolved by the harness (no matching checked citation) | Citing something outside the harness's resolution set is unverifiable evidence. |
| `P_UNRESOLVED:COMMIT_NOT_IN_REPO` | `git cat-file -e` fails for the sha | The cited commit does not exist in the provenance repo — fabricated. |
| `P_UNRESOLVED:COMMIT_UNREADABLE` | The cat-file call itself errors | Ungradable evidence is failed evidence. |
| `P_UNRESOLVED:COMMIT_NOT_AN_ARCHIVE_COMMIT` | No `sources/` blob among the commit's changes (or `index.jsonl` not among them) | Only genuine archive commits count as sources. |
| `P_UNRESOLVED:COMMIT_MULTIPLE_SOURCE_BLOBS` | More than one `sources/` blob in the commit | The chain must be unambiguous — one commit, one source. |
| `P_UNRESOLVED:INDEX_UNREADABLE_AT_COMMIT` | `git show <sha>:index.jsonl` fails | The index must be readable AT the cited commit (tamper-evident point-in-time state). |
| `P_UNRESOLVED:INDEX_ENTRY_MISSING_FOR_BLOB` | No index entry for the blob path | Every archived blob must be indexed. |
| `P_UNRESOLVED:BLOB_UNREADABLE_AT_COMMIT` | `git show <sha>:<blob>` fails | The archived bytes must exist at that commit. |
| `P_UNRESOLVED:BLOB_SHA_MISMATCH` | sha256(blob at commit) ≠ index entry's blob_sha256 | The blob was modified after archiving — tamper evidence. |
| `P_UNRESOLVED:URL_MISMATCH` | index entry url ≠ cited url | Sha/url pairs must be exactly as the archive receipt returned them (wr3i: one-position sha/url mispairing). |

**Blob reconstruction lane (evidence, not a condition):** for every citation, the harness reconstructs the archived blob and byte-compares it against the repo's background markdown (`matches_repo_file`), persisting it under `results/<run-id>/reconstructed/`. A tampered blob already fails `BLOB_SHA_MISMATCH`; the byte-compare additionally proves the archived bytes ARE the background markdown the agent's reasoning was extracted from.

**Prompt-side counterpart (v14):** the extraction record stores each archive receipt in full — `source <filename> git:<sha> sha256:<blob> path=<repo path> <raw-github-url>` — and the answer block's SOURCES pairs are copied verbatim from those recorded `source` lines (never re-typed, never re-paired, never guessed). A sha or URL that appears in no recorded `source` line is fabricated provenance; this gate is what catches it when the discipline slips (wr3i one-position mispairing; wr3m corrupted re-typed sha and invented URL).

---

## 8. Harness-side attestation lane states

Collected for EVERY case (v9) and recorded in the grade JSON `attestation` object:

| Field | Meaning |
|---|---|
| `agent_ip` | The resolved agent container IP (v9.1: single-valued; preflight fails on ambiguity). |
| `qe_pattern_match` | The query-engine log carried the block's exact query pattern (space-stripped) inside the case window. |
| `access_count` | Successful `POST /v1/query` responses to the agent IP in the window (read-proxy access log, regex matches the live line format; host-IP harness probes excluded). |
| `write_count` / `archive_count` | Successful `POST /v1/write` / `POST /v1/archive` responses to the agent IP (facade access log). |
| `window` | `[case setup restart, grade time]` — the attestation lane never reads outside the case window. |

History census (grade JSON `history_window`): `mode` (window mode; `full` = current file content, the per-case-trim default), `retrieve_calls` / `retrieve_args` (real das-retrieve args parsed from the window), `placeholder_calls` (collapsed `$_` tuples), `persist_receipts` / `archive_receipts` (in-window receipt lines), `add_atom_shas` (in-window persisted shas), and the attested censuses `attested_retrieve_calls` / `attested_write_calls` / `attested_archive_calls`. Known-lossy channel: 100% placeholder collapse has been observed; the censuses + lanes are the corrective.

---

## 9. Phase-artifact states (`results/<run-id>/`)

**`preflight.json`** — environment gate, `all_ok` must be true (else harness error, exit 1): container checks (`container_omega-das-write-bridge-write-bridge-1`, `container_omega-das-integration-read-proxy-1`, `container_omega-das-integration-query-engine-1`, `container_omega-das-integration-mongodb-1`, `container_omega-curiosity` — all must be `running`), dynamic IPs (`write_bridge_ip`, `read_proxy_ip`, `agent_ip` — single-valued), `write_bridge_smoke` + `write_bridge_smoke_cleanup` (`ok`), `read_proxy_query` (`ok`), `provenance_repo` (`ok`), `memory_volume` (`ok`), `prompt_backup_fresh` (`ok` — the per-run backup must not pre-exist), `skill_description_upgraded` (`ok` — das-retrieve WHY/WHEN/HOW contract present in the mounted plugin), `metta_skill_upgraded` (`ok` — 2-arg operator contract in the repo artifact), `metta_plugin_mounted` (`ok` — live container has the plugin file), `chroma_memory_dir` (`ok`), `canary_fetch_ai` (`count=<n>`, must be ≥ 1 — campaign atoms intact).

**`cleanup-das.json`** — pre-run residue cleanup: `mongo_counts_before/after`, `canaries_before/after` (`fetch_ai_inheritance` — must be unchanged, ≥1), `discovered_expressions` + `discovered_count` (two read-only discovery nets: provenance-URL-decorated writes + benchmark-only literals), `cleanup_results` (links-only deletion via the write bridge; `--delete-nodes` is FORBIDDEN — symbol nodes are shared across the campaign DB), `remaining_expressions`/`remaining_count` (must be 0), `canaries_intact` (true), `started`/`finished`. Non-empty residue or changed canaries → harness error (exit 1), run aborts.

**`setup-case-<case>.json`** — `prompt_installed: true`, `window_start_snapshot` (pre-case history snapshot path), `restarted_at` (ISO), `history_trimmed: true` (per-case window marker; `--no-trim-history` keeps full history).

**`agent-case-<case>.json`** — `status`: `complete` (answer block found before the deadline; `elapsed_s`) or `timeout` (75-min window expired; post snapshot taken; the case is graded ANYWAY on whatever was written). Timeout is a case failure, not a harness error.

**`grade-case-<case>.json`** — the per-case verdict object: `verdict`, `conditions[]`, `detail` (`final_answer`, `query`, `quoted_count`, `reissue_count`, `reissue_error`, `facts_index_size`, `facts_not_in_index[]`, `foreign_literals[]`, `index_absent_count`/`index_absent[]`, `trace_steps`, `trace_not_grounded[]`, `exec_outputs`), `history_window` (§8), `facts_index_size`, `attestation` (§8), `citations[]` (`sha`, `url`, `conditions` — resolution conditions per citation), `reconstruction[]` (`blob_path`, `reconstructed`, `repo_file`, `matches_repo_file`, `saved_to`), `timestamp`.

**`grade.json`** — run-level: `gate_verdict`, `cases_passed`/`cases_total`, `per_case{verdict, conditions[]}`, `mode`, `timestamp`.

**`report.json` / `report.md`** — assembled views of the grade JSONs + cleanup summary; report.md carries the per-case table (Case | Verdict | Conditions | Attested | Reconstruction).

**`teardown.json`** — `restored: true|false`, `timestamp`. ALWAYS runs (even on gate FAIL): standby prompt restored (contamination guard: refuses to restore a backup prompt that still contains BENCHMARK MODE content unless `--allow-dirty-backup`), truthful `omega_state.md`, history restored byte-identically from the pre-run backup (archived first as `history.pre-run.metta`), per-case snapshots kept under `windows/<case>/{pre,post}.metta` unless `--keep-snapshots`, agent restarted via systemd (never `docker restart` — start.sh trap-removes the container).

**Missing-block shorthand:** if no `### CASE` block exists at all, the grade emits `["A_MISSING", "Q_MISSING", "P_MISSING", "R_MISSING"]` — every deliverable-based gate failed at once; E-gate still evaluates the record independently.

---

## 10. Classification summary

- **Blocking (fail the case):** `A_MISSING`, `A_WRONG`, `A_JUDGE_UNAVAILABLE`, `Q_MISSING`, `Q_NOT_QUERY_FIRST`, `Q_PLACEHOLDER`, `Q_DEGENERATE_PATTERN`, `Q_NOT_IN_HISTORY`, `Q_NO_RECEIPT`, `Q_REISSUE_ERROR`, `Q_REISSUE_MISMATCH`, `Q_ABSENCE_UNPROVEN`, `E_NO_EXTRACTION`, `E_NO_INGEST`, `E_NO_FACTS`, `E_FACTS_NOT_IN_INDEX`, `E_LITERAL_NOT_EXTRACTED`, `R_MISSING`, `R_NOT_METTA`, `R_NOT_EXECUTED`, `R_TRACE_NOT_GROUNDED`, `P_MISSING`, all `P_UNRESOLVED:*`.
- **Informational (never fail):** `Q_ATTESTED_VIA_ACCESS_LOG`, `E_INGEST_ATTESTED_VIA_FACADE_LOG`, `E_INDEXED_NOT_PERSISTED`.
- **Harness-level (fail the RUN, exit 1):** preflight `all_ok=false`, cleanup residue/canary failure, unusable history window, unreadable answers, setup phase error (per-case `verdict:"ERROR"`), teardown failure.
- **Valid negative signal:** gate FAIL (exit 2) — the governance bar was not met; the artifacts say exactly which gate and why.

## 11. Gate-change history (details in `test-spec.md`)

- v2 (2026-10-22): strict gate re-scope; condition codes; deterministic grading; exit-code signal.
- v3 (2026-10-23): E-gate; attestation lanes; cleanup-das; P reconstruction; sequential mode.
- v5 (2026-10-24): R-gate (trace shape + grounding); line-anchored block parsing.
- v7 (2026-10-25): `R_NOT_EXECUTED` (scenario A/A2).
- v9 (2026-10-25): `E_INDEXED_NOT_PERSISTED` (informational); record-shape parsing; always-on attestation.
- v10 (2026-10-26): negation-aware `A_SKY`; bare-symbol `Q_DEGENERATE_PATTERN` literals; atom-wise derivation grounding; attested-retrieve regex fix; prompt citation-pair rule.
- v11 (2026-10-26): atom-wise grounding for EVERY non-first trace step; memory-volume-relative prompt paths.
- v12 (2026-10-26): prompt-side FACTS verbatim-copy discipline (this reference added); gates unchanged.
- v13 (2026-10-26): `A_SKY` negation lexicon extended with lexical blockers (blocks/prevents/excludes/hides/obscures + inflections) — wr3l evidence: the honest answer "blocks any view of the sky" false-failed; an UNNEGATED claim still fails and the negation/blocker must still PRECEDE the keyword.
- v14 (2026-10-26): prompt-side full-provenance extraction records — every `source` line now records the complete archive receipt (sha + sha256 blob + repo path + raw-github URL) and SOURCES pairs are verbatim copies of recorded pairs; gates unchanged.
- v15 (2026-10-26): case set reduced to `original`, `unsolvable`, `false` (removed `uncertainty`, `true`, `easy`, `difficult` + prompt files; nothing else relaxed); A-gate substance → single OpenAI-compatible LLM judge; `A_SKY`/`A_FABRICATED`/`A_NO_INABILITY` removed, `A_JUDGE_UNAVAILABLE` added (fail-safe).
- v16 (2026-10-26): judge simplified to the single-prompt TRUE/FALSE form — ONE user message with the test question, the agent's answer, and the expected answer; verdict = first TRUE/FALSE token; configurable endpoint (`--judge-base-url/--judge-model/--judge-api-key/--judge-timeout`), defaults reuse the Omega agent's ASI:One asi1-ultra + runtime.env key; preflight smoke-checks the judge.

---

## 12. Item-0 gate audit — v17 transition (Phase 5)

This section is the normative item-0 gate-condition audit (owner resolution 4, spec §8 item 0, `docs/issue-2-implementation-spec.md`): every condition code emitted in the grade paths (`grading.py`, cross-checked against its `history_parse.py` lanes and `run_benchmark.py` callers) is classified KEEP / MODIFY / RETIRE against the v4 source-ledger design (spec §2.6). The Phase 5 code milestones that follow implement this table; codes retired from the active paths disappear from §2–§10 at the corresponding code milestone. Preflight checks are OUT OF SCOPE here — they are audited in the Phase 5 preflight milestone (spec §8 item 7); run-level verdicts and exit-code semantics are unchanged (spec §2.6).

**(a) Blocking condition codes (current grade path):**

| Code | Classification | Current trigger (v15 source) | v4 disposition + rationale (spec anchor) |
|---|---|---|---|
| `A_MISSING` | KEEP | No `FINAL ANSWER (<case>)` line in the block, or no block at all (`grading.py:482`, `:586`). | Unchanged — the FINAL ANSWER line stays in the v4 answers block (spec §2.7) and `A_*` is listed unchanged (spec §2.6). |
| `A_WRONG` | KEEP | The LLM judge replies FALSE for the answer line (`grading.py:490`). | Unchanged — the v16 judge contract is untouched by provenance (spec §2.6: `A_*` unchanged). |
| `A_JUDGE_UNAVAILABLE` | KEEP | No judge configured (`grading.py:484`) or the judge call failed / replied unparseably (`grading.py:488`). | Unchanged — the fail-safe stays: an unjudged answer can never pass (spec §2.6: `A_*` unchanged). |
| `Q_MISSING` | KEEP | No `QUERY:` line in the case block (`grading.py:600`; missing-block shorthand `:586`). | Unchanged — the QUERY line stays (spec §2.7); `Q_*` unchanged (spec §2.6). |
| `Q_NOT_QUERY_FIRST` | KEEP | `QUERY:` line appears after the FINAL ANSWER line (`grading.py:609`). | Unchanged (spec §2.6: `Q_*` unchanged). |
| `Q_PLACEHOLDER` | KEEP | Query empty or contains `$_` (`grading.py:375`); also emitted when the quoted query is absent from history while window placeholder calls exist (`grading.py:632`). | Unchanged — the history-collapse defect it guards is exactly why the query attestation lanes stay (spec §2.6: `Q_*` unchanged; resolution 6 keeps the query lanes). |
| `Q_DEGENERATE_PATTERN` | KEEP | No `$variable` in the query (`grading.py:377`) or no non-variable literal after variable-stripping (`grading.py:387`). | Unchanged (spec §2.6: `Q_*` unchanged). |
| `Q_NOT_IN_HISTORY` | KEEP | Quoted query absent from the case-window history events and the attestation lane did not prove it (`grading.py:630`). | Unchanged — its informational substitute and the query lanes survive (spec §2.6: `Q_*`; resolution 6). |
| `Q_NO_RECEIPT` | KEEP | No `DAS_RETRIEVE_OK ... count=<n>` receipt line in the block (`grading.py:636`). | Unchanged — the das-retrieve receipt contract is untouched (spec §2.6: `Q_*`; §8 item 10 changes only the skill description). |
| `Q_REISSUE_ERROR` | KEEP | No re-issue function wired (`grading.py:643`) or the harness re-issue errored (`grading.py:647`). | Unchanged (spec §2.6: `Q_*` unchanged). |
| `Q_REISSUE_MISMATCH` | KEEP | Re-issue count ≠ quoted receipt count (`grading.py:658`). | Unchanged (spec §2.6: `Q_*` unchanged). |
| `Q_ABSENCE_UNPROVEN` | KEEP | Unsolvable: quoted ≠ 0 or re-issue ≠ 0 (`grading.py:654`, `:661`); knowledge case: quoted `count=0` (`grading.py:656`). | Unchanged (spec §2.6: `Q_*` unchanged). |
| `E_NO_EXTRACTION` | KEEP | Facts index supplied but empty (`grading.py:674`). | Unchanged (spec §2.6 explicit) — the extraction record survives v4; only its `source …` record lines change (spec §2.7). |
| `E_NO_INGEST` | MODIFY | First case only: `window_persist_receipts == 0` OR `window_archive_receipts == 0`, minus the facade-log attested branch (`grading.py:676-692`). | RECEIPTS-ONLY (spec §2.6; resolution 6; §8 item 2): blocking iff first case AND `window_persist_receipts == 0`; the ARCHIVE-OK half and the attested branch (`:684-690`) are deleted — `BRIDGE-PERSIST-OK` receipts are extractable from history windows (`history_parse.py:119-121`), so no log census is needed. |
| `E_NO_FACTS` | KEEP | Knowledge case block has no non-empty `FACTS:` line (`grading.py:697`). | Unchanged (spec §2.6 explicit) — the FACTS line stays and becomes the reconstruction script's aligned input (spec §2.7, §8 item 4). |
| `E_FACTS_NOT_IN_INDEX` | KEEP | A `FACTS:` expression is not verbatim in the extraction record (`grading.py:701`). | Unchanged (spec §2.6 explicit) — the record's `expr` lines persist as `expr <expression> top=<handle>` (spec §2.7). |
| `E_LITERAL_NOT_EXTRACTED` | KEEP | A quoted literal of the executed query is not from the extracted vocabulary (`grading.py:709`). | Unchanged (spec §2.6 explicit). |
| `R_MISSING` | KEEP | No `REASONING:` line in the block (`grading.py:748`). | Unchanged (spec §2.6: `R_*`) — the executed trace is the load-bearing direct evidence under the resolution-6 design principle (spec §2.6). |
| `R_NOT_METTA` | KEEP | Fewer than 2 s-expression steps or prose segments in the trace (`grading.py:753`). | Unchanged (spec §2.6: `R_*`). |
| `R_NOT_EXECUTED` | KEEP | Knowledge case: neither `exec` outputs in the record nor an `(stv …)` output in the trace (`grading.py:771`). | Unchanged (spec §2.6: `R_*`) — exactly the "direct verification evidence of the MeTTa reasoning trace" the owner calls load-bearing (resolution 6). |
| `R_TRACE_NOT_GROUNDED` | KEEP | Step 0 ≠ the executed query clause or a non-first step fails atom-wise grounding (`grading.py:821`). | Unchanged (spec §2.6: `R_*`). |
| `P_MISSING` | MODIFY | Knowledge case with no citations parsed from the SOURCES line (`grading.py:826-828`). | Redefined (spec §2.6; §8 item 4): knowledge case where reconstruction finds no used stored facts carrying provenance attributes (nothing citable); unsolvable exempt. The SOURCES line is removed (spec §2.7), so "missing" is decided by the deterministic chain, not by quoted citations. |
| `P_UNRESOLVED:<COND>` | MODIFY | A resolved citation's condition list is non-empty; each COND emitted bare (`grading.py:839`), CONDs produced by `provenance_check.resolve_citation` (`run_benchmark.py:979` sequential / `:1336` batch). | v4 form becomes `P_UNRESOLVED:<expr12>:<COND>` with the new 8-value COND set (spec §2.6); conditions come from the reconstruction script's JSON mapped by `grade_case` (spec §8 item 4). Per-COND dispositions below. |

**`P_UNRESOLVED` COND values (current set — `provenance_check.py`, emitted via `grading.py:839`):**

| COND | Classification | Current trigger (v15 source) | v4 disposition + rationale (spec anchor) |
|---|---|---|---|
| `COMMIT_NOT_IN_REPO` | KEEP | `git cat-file -e <sha>^{commit}` fails (`provenance_check.py:77`). | Carried over verbatim — commit-exists is step 1 of the v4 chain (spec §2.4) and a §2.6 COND-set member. |
| `COMMIT_UNREADABLE` | KEEP | The `git show --name-only` call errors (`provenance_check.py:83`). | Carried over verbatim — ungradable evidence is failed evidence (spec §2.6 COND set). |
| `COMMIT_NOT_AN_ARCHIVE_COMMIT` | MODIFY | No `sources/` blob among the commit's changes (`provenance_check.py:88`) or `index.jsonl` not among them (`:131`). | Renamed/split per spec §2.6: `COMMIT_NOT_A_LEDGER_COMMIT` (ledger-commit shape) plus `COMMIT_TOUCHES_OTHER_FILES` — matching the v4 `verify_commit` chain (spec §2.3, §2.4). |
| `COMMIT_MULTIPLE_SOURCE_BLOBS` | RETIRE | More than one `sources/` blob in the commit (`provenance_check.py:92`). | Retires with the old store (spec §2.6); the v4 unambiguity invariant is `COMMIT_ADDS_NOT_ONE_LINE` (spec §2.2). Survives only inside the standalone unwired `provenance_check.py` (resolution 4; spec §13 item 2). |
| `INDEX_UNREADABLE_AT_COMMIT` | RETIRE | `git show <sha>:index.jsonl` fails (`provenance_check.py:99`). | `INDEX_*` retires with the old store (spec §2.6); the v4 entry-parse failure is `ENTRY_PARSE_FAILED`. Standalone unwired survival only (resolution 4). |
| `INDEX_ENTRY_MISSING_FOR_BLOB` | RETIRE | No index entry for the blob path (`provenance_check.py:114`). | `INDEX_*` retires (spec §2.6) — the ledger entry identity is the `(ref, sha256)` pair; no index exists under v4 (spec §2.2). Standalone unwired survival only (resolution 4). |
| `BLOB_UNREADABLE_AT_COMMIT` | RETIRE | `git show <sha>:<blob>` fails (`provenance_check.py:122`). | `BLOB_*` retires (spec §2.6) — no content blobs exist under ledger-only v4 (D1, spec §10). Standalone unwired survival only (resolution 4). |
| `BLOB_SHA_MISMATCH` | RETIRE | sha256(blob at commit) ≠ index entry's `blob_sha256` (`provenance_check.py:126`). | `BLOB_*` retires (spec §2.6); the tamper evidence survives as the harness byte-compare (`sha256(background file) == entry.sha256`, spec §8 item 4; §11 residual risk 2) plus `REF_SHA_MISMATCH`. Standalone unwired survival only (resolution 4). |
| `URL_MISMATCH` | RETIRE | Index entry url ≠ cited url (`provenance_check.py:137`). | Retires explicitly (spec §2.6); re-pairing detection moves to `REF_SHA_MISMATCH` (entry `(ref, sha256)` vs atom attrs, spec §2.3) plus informational `P_SOURCE_SET_MISMATCH`. Standalone unwired survival only (resolution 4). |

**(b) Informational condition codes:**

| Code | Classification | Current trigger (v15 source) | v4 disposition + rationale (spec anchor) |
|---|---|---|---|
| `Q_ATTESTED_VIA_ACCESS_LOG` | KEEP | Quoted query absent from window history but `qe_pattern_match` AND `access_count >= 1` (`grading.py:628`). | Unchanged (spec §2.6: `Q_*`); the query lanes serving it are explicitly kept (resolution 6; spec §8 item 3) — the history-collapse defect persists under v4. |
| `E_INGEST_ATTESTED_VIA_FACADE_LOG` | RETIRE | First case, both receipt censuses zero, but the facade log shows ≥1 `POST /v1/write` AND ≥1 `POST /v1/archive` from the agent IP (`grading.py:690`). | Retired entirely (spec §2.6; resolution 6) — log-census ingest attestation is dropped; `E_NO_INGEST` becomes receipts-only. The query lanes survive because they serve the DIFFERENT gate `Q_ATTESTED_VIA_ACCESS_LOG`. Survives nowhere — full row in (c). |
| `E_INDEXED_NOT_PERSISTED` | KEEP | A recorded index expression's DAS presence probe resolves to zero (`grading.py:733`). | Unchanged (spec §2.6 explicit) — direct DAS-side verification, not a log census; consistent with the resolution-6 design principle. |

**(c) Retired codes — where they survive:**

| Code | Classification | Current trigger (v15 source) | v4 disposition + survival (spec anchor) |
|---|---|---|---|
| `E_INGEST_ATTESTED_VIA_FACADE_LOG` | RETIRE | Currently informational (§2): facade-log ingest attestation substitutes for blocking `E_NO_INGEST` (`grading.py:684-690`). | Dropped entirely (resolution 6; spec §2.6, §8 item 2 deletes the attested branch). Survives nowhere. |
| `P_UNRESOLVED:<sha12>:NOT_CHECKED` | RETIRE | A block-cited `(sha, url)` pair is absent from the harness-resolved `citation_checks` set (`grading.py:836`; emitted from the shared `gate_case`, so reachable from both the sequential path and the batch lane — in the sequential path a defensive tripwire only, since `citation_checks` is built from the same `parse_citations(block.sources_raw)` the gate re-parses, `run_benchmark.py:964-980`). | Retires from the active path with its feeders: the SOURCES-line citation parse (`grading.py:825-836`) is rewired to the reconstruction script (spec §8 item 4; §2.7 removes the SOURCES line) and the batch citation lane retires (resolution 4; spec §13 item 2). The reconstruction chain enumerates every used stored fact itself, so "cited outside the resolution set" has no v4 analog. Survives nowhere. |
| `COMMIT_MULTIPLE_SOURCE_BLOBS` | RETIRE | >1 `sources/` blob in the commit (`provenance_check.py:92`). | Survives only inside `provenance_check.py` as a STANDALONE UNWIRED legacy tool — no harness import remains after the rewire (resolution 4; spec §2.6, §13 item 2). |
| `INDEX_UNREADABLE_AT_COMMIT` | RETIRE | `git show <sha>:index.jsonl` fails (`provenance_check.py:99`). | Same standalone-unwired survival (resolution 4; spec §2.6 `INDEX_*`). |
| `INDEX_ENTRY_MISSING_FOR_BLOB` | RETIRE | No index entry for the blob path (`provenance_check.py:114`). | Same standalone-unwired survival (resolution 4; spec §2.6 `INDEX_*`). |
| `BLOB_UNREADABLE_AT_COMMIT` | RETIRE | `git show <sha>:<blob>` fails (`provenance_check.py:122`). | Same standalone-unwired survival (resolution 4; spec §2.6 `BLOB_*`). |
| `BLOB_SHA_MISMATCH` | RETIRE | sha256(blob) ≠ index `blob_sha256` (`provenance_check.py:126`). | Same standalone-unwired survival (resolution 4; spec §2.6 `BLOB_*`). |
| `URL_MISMATCH` | RETIRE | Index entry url ≠ cited url (`provenance_check.py:137`). | Same standalone-unwired survival (resolution 4; spec §2.6). |

**(d) New v4 codes (v17):**

| Code | Classification | Current trigger (v15 source) | v4 disposition + rationale (spec anchor) |
|---|---|---|---|
| `H_MISSING` | ADD — blocking (D4) | — (new in v17) | Knowledge case: no (or empty) `HANDLES:` line in the block (spec §2.6; §8 item 5). |
| `H_COUNT_MISMATCH` | ADD — blocking (D4) | — (new in v17) | HANDLES token count ≠ FACTS expression count (spec §2.6; §8 item 5). |
| `H_MISMATCH` | ADD — blocking (D4) | — (new in v17) | A claimed handle ≠ the deterministically re-derived `top_handle` of the aligned FACTS expression — fabrication tripwire; handles are re-derivable client-side, so the claim is a cross-check, not a lookup dependency (spec §2.6; §2.4 chain; D4). |
| `P_SOURCE_SET_MISMATCH` | ADD — informational | — (new in v17) | Sources attached to the case's facts ⊄ the case background source set — semantic-misattribution visibility (spec §2.6; §8 item 4); joins `INFORMATIONAL_CONDITIONS` in place of the retired `E_INGEST_ATTESTED_VIA_FACADE_LOG`. |
| `P_UNRESOLVED:…:COMMIT_NOT_IN_REPO` | carried over (KEEP) | `provenance_check.py:77` | v4 chain step 1: commit not found in the LEDGER repo (spec §2.4, §2.6). |
| `P_UNRESOLVED:…:COMMIT_UNREADABLE` | carried over (KEEP) | `provenance_check.py:83` | The cat-file/show call errors (spec §2.6 COND set). |
| `P_UNRESOLVED:…:COMMIT_NOT_A_LEDGER_COMMIT` | renamed (MODIFY) | `provenance_check.py:88`, `:131` | Replaces `COMMIT_NOT_AN_ARCHIVE_COMMIT`: changed paths do not fit the ledger-commit shape (spec §2.3 `verify_commit`; §2.6). |
| `P_UNRESOLVED:…:COMMIT_TOUCHES_OTHER_FILES` | ADD | — (new in v17) | Commit touches files besides `SOURCE-LEDGER.json` (spec §2.3, §2.6). |
| `P_UNRESOLVED:…:COMMIT_ADDS_NOT_ONE_LINE` | ADD | — (new in v17) | The commit's `SOURCE-LEDGER.json` diff adds ≠ exactly one entry line (spec §2.2 +1-line invariant; §2.6). |
| `P_UNRESOLVED:…:ENTRY_PARSE_FAILED` | ADD | — (new in v17) | The added line does not parse as an entry with exactly `{ref, sha256, entry_date}` (spec §2.3, §2.6). |
| `P_UNRESOLVED:…:REF_SHA_MISMATCH` | ADD | — (new in v17) | Entry `(ref, sha256)` ≠ the atom's provenance attributes (spec §2.3, §2.6) — replaces the INDEX/BLOB/URL pairing checks. |
| `P_UNRESOLVED:…:NO_PROVENANCE_ATTRS` | ADD | — (new in v17) | A stored link (re-derived handle hits `db.links`) carries no provenance attributes (spec §2.4 rule (a); §2.6); pre-migration atoms resolve via `--legacy-repo` as informational-only, never blocking (resolution 4). |

**(e) Attestation-lane states + census fields:**

| Field | Classification | Current trigger (v15 source) | v4 disposition + rationale (spec anchor) |
|---|---|---|---|
| `attestation.agent_ip` | KEEP | Resolved agent container IP recorded per case (`run_benchmark.py:322`, `:325`). | Structural bound for the kept query lanes (`access_count` counts `POST /v1/query` from this IP) — resolution 6 keeps the query lanes (spec §8 item 3). |
| `attestation.access_count` | KEEP | 2xx `POST /v1/query` count to the agent IP in the window (`run_benchmark.py:326`). | Query lane — serves `Q_ATTESTED_VIA_ACCESS_LOG`; explicitly kept (resolution 6; spec §8 item 3, §2.6). |
| `attestation.qe_pattern_match` | KEEP | Query-engine log carried the block's exact pattern in the window (`run_benchmark.py:327`). | Query lane — kept (resolution 6; spec §8 item 3). |
| `attestation.write_count` | RETIRE | 2xx `POST /v1/write` count to the agent IP (`run_benchmark.py:328-329`). | Write census dropped with the ingest-attestation feature (resolution 6; spec §8 item 3); `/v1/write` itself survives as the core v4 write path — only the log census goes. |
| `attestation.archive_count` | RETIRE | 2xx `POST /v1/archive` count to the agent IP (`run_benchmark.py:330-331`). | Archive census dropped (resolution 6); the `/v1/archive` route itself is deleted in Phase 1 (spec §2.3). |
| `attestation.source_count` | RETIRE (never wired) | — (does not exist in v15; the would-be `/v1/source` census). | The census rewire is dropped — no `source_count` (resolution 6; spec §8 item 3). |
| `attestation.window` | KEEP | `[case setup restart, grade time]` bounds every lane (`run_benchmark.py:332`). | Structural bound for the kept query lanes (spec §8 item 3). |
| `history_window.attested_retrieve_calls` | KEEP | Grade-JSON echo of `access_count` (`run_benchmark.py:1061`). | Query census field kept (spec §8 item 3: query fields kept). |
| `history_window.attested_write_calls` | RETIRE | Grade-JSON echo of `write_count` (`run_benchmark.py:1062`). | Ingest census field removed (spec §8 item 3). |
| `history_window.attested_archive_calls` | RETIRE | Grade-JSON echo of `archive_count` (`run_benchmark.py:1063`). | Ingest census field removed (spec §8 item 3 cites this line). |
| `history_window.persist_receipts` | KEEP | Count of in-window `BRIDGE-PERSIST-OK` receipts (`run_benchmark.py:1058`, via `history_parse.py:119-121`). | Feeds `window_persist_receipts` — the receipts-only `E_NO_INGEST` evidence (spec §2.6; §8 item 2). |
| `history_window.archive_receipts` | RETIRE | Count of in-window `ARCHIVE-OK` receipts (`run_benchmark.py:1059`). | Removed (spec §8 item 3 cites this line); `ARCHIVE-OK` retires with the archive skill (D7; spec §2.5). |
| `history_window.add_atom_shas` | RETIRE | In-window add-atom `git:<sha>` tokens (`run_benchmark.py:1060`, via `history_parse.py:110-116`). | The lane retires from the v4 grade path (spec §8 item 6; resolution 4); v4 write receipts carry `top=<handle>`, not git shas (spec §2.5). |
| `history_window.mode` / `.retrieve_calls` / `.retrieve_args` / `.placeholder_calls` | KEEP | Window mode + real das-retrieve args + placeholder census (`run_benchmark.py:1054-1057`). | Serve the Q-gate history checks (`Q_NOT_IN_HISTORY`, `Q_PLACEHOLDER`) — `Q_*` unchanged (spec §2.6). |

**(f) history_parse.py lanes:**

| Lane | Classification | Current trigger (v15 source) | v4 disposition + rationale (spec anchor) |
|---|---|---|---|
| `window_from_texts` | KEEP | Slices history to the case window from pre/post snapshots (`history_parse.py:38-55`). | The window is the Q-gate's evidence boundary and the receipts census's scope — unchanged under v4 (spec §2.6: receipts are extracted "from history windows"). |
| `normalize_query` | KEEP | Reduces a das-retrieve arg (raw or JSON payload) to the query pattern (`history_parse.py:73-90`). | Used by the Q-gate (`grading.py:98`; `run_benchmark.py:1000`) — `Q_*` unchanged (spec §2.6). |
| `extract_retrieve_args` | KEEP | Real das-retrieve args from the window (`history_parse.py:93-98`). | Feeds `history_queries` → `Q_NOT_IN_HISTORY` (`grading.py:621`); `Q_*` unchanged (spec §2.6). |
| `count_placeholder_retrieves` | KEEP | Counts `$_`-placeholder das-retrieve calls (`history_parse.py:101-107`). | Feeds `placeholder_calls` → `Q_PLACEHOLDER` (`grading.py:632`); `Q_*` unchanged (spec §2.6). |
| `extract_persist_receipts` | KEEP | `BRIDGE-PERSIST-OK` receipt lines from the window (`history_parse.py:119-121`). | Load-bearing for receipts-only `E_NO_INGEST` — spec §2.6 cites this exact site; §8 item 2. |
| `extract_add_atom_shas` | RETIRE (from the v4 grade path) | `git:<sha>` tokens from add-atom lines (`history_parse.py:110-116`); callers `run_benchmark.py:955` (sequential) / `:1312` (batch). | Retires from the v4 grade path — kept for legacy history texts, no v4 grade-path callers (spec §8 item 6; resolution 4); v4 receipts carry `top=<handle>` (spec §2.5). |
| `extract_archive_receipts` | RETIRE (from the v4 grade path) | `ARCHIVE-OK` receipt lines (`history_parse.py:124-126`); callers `run_benchmark.py:954` (sequential) / `:1311` (batch). | Same — no v4 grade-path callers (spec §8 item 6; resolution 4); `ARCHIVE-OK` retires with the archive skill (D7; spec §2.5). |

**Audit tally:** 36 audited rows over the current surface — 27 distinct condition codes (3 `A_*`, 10 `Q_*`, 7 `E_*`, 3 `P_*`, 4 `R_*`), where the `P_UNRESOLVED:<COND>` family expands to 9 concrete COND values — classified **24 KEEP / 4 MODIFY / 8 RETIRE**. New in v17: 4 condition codes (`H_MISSING`, `H_COUNT_MISMATCH`, `H_MISMATCH` blocking per D4; `P_SOURCE_SET_MISMATCH` informational) and the 8-value `P_UNRESOLVED` COND set (2 carried over, 1 renamed, 5 new). Attestation/census and history-parse lanes: 21 fields classified (14 + 7).
