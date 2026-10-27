# Feature Specification: Transparent Provenance (Issue #2)

**Feature Branch**: `issue-2-transparent-provenance`

**Created**: 2026-10-27

**Status**: Approved for implementation (decision gate CLEARED — D1-D7 resolved, Balazs 2026-10-27 22:37 UTC)

**Input**: `docs/issue-2-implementation-spec.md` (v4, 450 lines, §1-§14 + Appendix) + `docs/issue-2-provenance-analysis.md`

> **NORMATIVE SOURCE:** This specification is a decomposition of `docs/issue-2-implementation-spec.md`. **On any disagreement between this SDD artifact set (spec/plan/tasks/constitution) and that document, the implementation-spec document is normative** (per Balazs, SDD execution note, implementation-spec header §SDD addendum 2026-10-27 22:20 UTC). Section citations below (`§N`) refer to that document.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Live-Probe De-Risking (Phase 0, §3) (Priority: P0)

The implementer verifies — does not assume — the two assumptions the design rests on: (P0a) mongo link/node docs are keyed `_id` = handle and `custom_attributes` (incl. `provenance_git_commit/ref/blob_sha256`) are visible in mongo but invisible to pattern answers; (P0b) the overwrite semantics of re-writing the same expression (deterministic same handle) with different provenance attrs — overwrite, merge, or append.

**Why this priority**: the whole deterministic handle chain (§2.4 spine) and the Phase-4 script's attribute handling depend on these findings; decision-independent, cheapest first.

**Independent Test**: one canary fact written via the bridge with a v4 provenance payload, then `docker exec <mongo> mongosh … --eval 'db.links.find({_id: "<top_handle>"})'`; second canary with a distinct `provenance_ref`; mongosh inspection of the single top-link doc (§3 P0a/P0b).

**Acceptance Scenarios** (§3 acceptance, verbatim):
1. **Given** the live OVH host, **When** both probes run, **Then** both are recorded with raw evidence (mongosh outputs + receipts) in the probe scripts' result notes (`deploy/das/write-bridge/tests/iter18_probe_mongo_attrs.py` + result notes, pattern of `iter16_probe.py`/`iter16_groundtruth.js`); the mongo handle field name is confirmed live against the LIVE writer; overwrite semantics are documented.
2. **Given** probe completion, **When** Phase 1/4 unit tests are written, **Then** the findings are encoded as fixtures/assumptions (§3 test strategy: probes are one-off scripts, excluded from the pytest registry).

---

### User Story 2 - Ledger-Backed Facade: `/v1/source` + `/v1/write` v4 (Phase 1, §4) (Priority: P1)

The write-bridge facade records provenance in a fresh single-file `SOURCE-LEDGER.json` git repo and gates every provenance write on a verified ledger commit BEFORE any DAS write.

**Why this priority**: every later phase (plugin, reconstruction, gates) consumes this API; foundational.

**Independent Test**: `POST /v1/source {"ref","sha256"}` appends exactly one line to `SOURCE-LEDGER.json` with a pure +1-line `git diff` and returns `{commit, deduped, entry_date}`; `POST /v1/write` with a fabricated `(commit, ref, sha)` triple is rejected 400 with the actionable §2.5 string; a valid one returns `top_handle`.

**Acceptance Scenarios** (§4 acceptance, verbatim):
1. **Given** a fresh ledger repo, **When** `/v1/source` appends/dedups, **Then** behavior is per §2.2 with pure +1-line diffs (verified with `git diff` in tests); dedup on `(ref, sha256)` returns the original commit, no file change, no new commit.
2. **Given** `/v1/write`, **When** the citation gate runs, **Then** hallucinated/mismatched (commit, ref, sha) triples are rejected with the §2.5 strings, before any DAS write.
3. **Given** a successful write, **Then** the 200 response carries `top_handle` (alongside `handles`, `verified`, `missing`); no companion atoms are emitted; 16 KiB caps hold; the facade still has zero outbound HTTP.

---

### User Story 3 - v3 Write-Skill Grammar: Agent-Transparent Citation (Phase 2, §5) (Priority: P1)

The agent writes `(add-atom &persistent <expr> "<ref>" [(stv s c)])` and stays unaware of provenance; the plugin resolves the ref, computes sha256 of the source content itself, ledger-appends via the facade, and returns `BRIDGE-PERSIST-OK: verified=<n> top=<handle> [stv=(s,c)]`.

**Why this priority**: the agent-facing surface; required by the benchmark prompt slim and the HANDLES vocabulary.

**Independent Test**: fake-facade flow test asserts `/v1/source`→`/v1/write` call order, cache hit (second write same ref = 1 POST), receipt format incl. `top=`; v2 `git:` token rejected with the actionable string; v1 suffix-less write unchanged (D3 permissive).

**Acceptance Scenarios** (§5 acceptance, verbatim):
1. **Given** the v3 grammar, **When** a URL ref (or a path ref inside `dasWriteSourceRoots`) is used, **Then** it is accepted; a `git:` token is rejected with `BRIDGE-PERSIST-WRITE-FAILED: git citations are no longer accepted — pass the source reference; archiving is automatic`; v1 stays valid.
2. **Given** repeated writes of the same source, **Then** first-write-per-source = 1 fetch + 2 POSTs, subsequent facts = 1 POST (per-process cache); receipts carry `top=`.
3. **Given** the plugin redeploy, **Then** the plugin file contains no `archive-source` references; `das-write.metta` loads cleanly (MeTTa import + clause rebind smoke).

---

### User Story 4 - Host Migration Runbook (Phase 3, §6) (Priority: P2)

The legacy provenance repo is retired (git bundle + tar backups) and a fresh ledger repo is initialized at the SAME host path — operator-executed over SSH, never scripted mutation (D6).

**Why this priority**: required before live e2e; not code — operator steps; sequenced in the same window as the plugin redeploy (v2 writes fail loudly at the gate between the two — the designed safe state).

**Independent Test**: the verification-only helper (`deploy/das/write-bridge/tools/migrate_ledger_repo.sh --check`) asserts repo exists, HEAD touches only SOURCE-LEDGER.json or is the init commit, `json.load` of the ledger is a list, every element has exactly the 3 keys.

**Acceptance Scenarios** (§6 acceptance, verbatim):
1. **Given** the runbook executed, **Then** the fresh repo has exactly one init commit and a valid empty-array ledger; facade healthy; legacy bundle verified; `--legacy-repo` paths recorded.
2. **Given** preflight, **Then** the REQUIRED `ledger_repo_format` check (resolution 5, replacing the old `provenance_repo` check) passes.

---

### User Story 5 - Standalone Reconstruction Script (Phase 4, §7) (Priority: P1)

`deploy/das/write-bridge/tools/reconstruct_sources.py` turns a MeTTa reasoning trace into per-expression/per-predicate source lists via the deterministic handle chain (mongo-direct + ledger git; zero LLM, zero pattern-engine queries).

**Why this priority**: this is the provenance gate — the direct-verification evidence the owner cares about (constitution principle II).

**Independent Test**: CLI per §2.4; a full happy-path trace resolves with exit 0; a missing-attr fact yields exit 2 + `NO_PROVENANCE_ATTRS`; a fabricated handle yields `H_MISMATCH` in the JSON; mongo/ledger outages yield exit 1 with a clear message.

**Acceptance Scenarios** (§7 acceptance, verbatim):
1. **Given** the exact §2.4 CLI, **Then** output is deterministic (same inputs → same JSON + exit code) with exit codes 0/2/1 per §2.4.
2. **Given** classification rules (§2.4), **Then** stored facts each carry ≥1 resolvable source; query clause and interpreter-derived outputs are exempt; a derivation's sources = its premises' sources; per-predicate aggregation groups by leading symbol.

---

### User Story 6 - Benchmark Rewiring (Phase 5, §8) (Priority: P1)

The windowless-room harness gates on the reconstruction output: HANDLES line (H_MISSING/H_COUNT_MISMATCH/H_MISMATCH, blocking — D4), receipts-only `E_NO_INGEST`, P-gate from the script, prompt slim, preflight v4, cleanup N3.

**Why this priority**: the grade surface is the deliverable the owner reads; items 0-10 per §8.

**Independent Test**: dry-run of `full` renders the slim prompt with the HANDLES line; unit fixtures pass; grep confirms no `ARCHIVE-OK`/`SOURCES:`/`add_atom_shas` references in the v4 grading path.

**Acceptance Scenarios** (§8 acceptance, verbatim):
1. **Given** the item-0 gate audit, **Then** the full keep/modify/retire table is committed in `GATES-REFERENCE.md` with every condition code classified (per code: keep/modify/retire + rationale).
2. **Given** the P-gate, **Then** a fabricated-handle fixture fails (H_MISMATCH) and a missing-source fixture fails (P_UNRESOLVED:NO_PROVENANCE_ATTRS); no ingest-census fields (`write_count`/`archive_count`/`source_count`) remain in the grade path (query lanes only).
3. **Given** item 10, **Then** the das-read skill description carries the handles clause and `das-read.metta` loads cleanly (import smoke); NO engine/proxy changes.

---

### User Story 7 - Tests Per Component (Phase 6, §9) (Priority: P2)

Consolidated unit suites across the three components, with pinned legacy prompt tests re-pointed at the slim prompt.

**Why this priority**: the unit suite IS Phase 5's test strategy; e2e validation follows the migration.

**Independent Test**: the suites listed in §9 pass; residue invariants (expressions + companions) zero after cleanup; budget-exhaustion rate compared to the wr3n baseline (0/3, commit `6684f4f`).

**Acceptance Scenarios** (§9, verbatim scope):
1. Write-bridge suite: `test_provenance_store.py` REWRITE, `test_app.py`/`test_write_client.py` EXTEND, NEW `test_reconstruct_integration.py`; `test_metta_to_atoms.py`/`test_cleanup.py` unchanged.
2. Windowless-room unit suite: NEW `test_reconstruct_sources.py`, `test_handles_gate.py`, `test_v17_prompt.py`; REWRITE pinned prompt tests (`test_v14/v12/v11/v8/v6_prompt.py`, `test_prompts_render.py`); EXTEND `test_grading.py`, gate fixtures, `test_history_parse.py`; UNCHANGED `test_provenance_check.py` (standalone unwired, resolution 4), `test_facts.py`, `test_v15_judge.py`, `test_v4_levers.py`.
3. Plugin suite: `test_provenance_suffix.py` + `test_das_write_bridge.py` extended to v3; `archive_source` cases deleted with the function.

---

### User Story 8 - Live E2E Validation (Phase 7, §12) (Priority: P1)

All 3 cases through the sequential `full` flow on the OVH host — the definitive e2e exit criterion; every failure gets a classified root-cause note with evidence.

**Why this priority**: the final gate; supersedes the Phase 5/6 single-run smoke.

**Independent Test**: preflight PASS → cleanup-das → per-case setup/agent/grade → report; baseline to beat `wr3n-20261026` (0/3 agent-side, commit `6684f4f`).

**Acceptance Scenarios** (§12 acceptance, verbatim):
1. **Given** Phases 0-6 merged and deployed, **Then** 3/3 PASS, or a documented genuine external blocker with evidence.
2. **Given** any failure in any iteration, **Then** a classified root-cause note (agent-side / harness-side / bridge-side / environment, with grade JSON conditions, receipts, docker logs, mongo state) is recorded in the run's `results/` dir.

---

### User Story 9 - Repo Asset Review (Phase 8, §13) (Priority: P3)

Systematic removal/update list for assets outdated under v4; every candidate verified before marking; each removal its own elementary commit with rationale.

**Why this priority**: hygiene; closes the loop on retired lanes (resolution 4).

**Independent Test**: grep-verified that nothing load-bearing references a removed asset.

**Acceptance Scenarios** (§13 acceptance, verbatim):
1. **Given** the candidate list (§13 items 1-7), **Then** the removal/update list is committed with verification citations for every line.
2. **Given** each executed removal, **Then** it is its own elementary commit with rationale in the message.

### Edge Cases

- Same `(ref, sha256)` re-recorded → dedup returns the original commit (pickaxe `git log --reverse -S"<line>"`, §2.2); same ref + different content (drift) = new entry + new commit.
- v2 rejection window (§11 residual risk 5): between migration and plugin redeploy, v2 writes fail loudly at the gate — the designed safe state.
- URL drift across the three moments (agent reads / skill fetches / harness byte-compares — §11 residual risk 2): detected by the byte-hash check; report-visible, operator-adjudicated.
- Attribute overwrite semantics on re-write (Phase 0b): if merge/append, the Phase-4 script treats the attribute set as potentially multi-valued and defines resolution order (spec update before Phase 4 merge).
- Ledger growth (§11 residual risk 6): one line + one commit per unique `(ref, sha256)` — unbounded but tiny; optional quota preflight check (Phase 3 helper).
- N3 sweep scope (§11 residual risk 7): handle-scoped deletion only — never all `WriteProvenance` links, never `CampaignProvenance`.
- Dropped custom attributes are NOT write failures — they surface at reconstruction as case FAIL (§11 residual risk 3).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001 — Write-skill grammar (v3)** (§2.1): the plugin accepts `(add-atom &persistent <balanced-expression> [v3-suffix])` where `v3-suffix := SOURCEREF [STV]`; SOURCEREF = http(s) URL or absolute-container-path (≤480 chars, no whitespace; paths enabled only inside `dasWriteSourceRoots`); STV = `(stv <s> <c>)` floats in [0,1]. The 2048-char cap applies to the expression only. v2 shape REMOVED (quoted `git:` token → actionable rejection). v1 suffix-less KEPT (D3 permissive).
- **FR-002 — Ledger format** (§2.2): `SOURCE-LEDGER.json` at the repo root; JSON array; each element exactly `{"ref", "sha256" (64 lowercase hex), "entry_date" (ISO-8601 UTC)}`; leading-comma one-element-per-line serialization PINNED (+1-line pure diffs); fresh-repo initial commit = `[\n]`; one commit per new entry; subject `ledger: <sha256[:12]> <ref[:96]>` (informational — verification NEVER parses it); dedup on `(ref, sha256)`; entry identity = `(ref, sha256)`, never line number.
- **FR-003 — `POST /v1/source`** (§2.3): request `{"ref","sha256"}` (16 KiB cap; unknown keys → 400); the §2.3 validation error strings; unconfigured store → 503; flock-serialized append; 200 `{commit, deduped, entry_date}`; `/v1/archive` route + `MAX_ARCHIVE_BODY_BYTES` DELETED; content NEVER crosses to the facade.
- **FR-004 — `POST /v1/write` v4** (§2.3): provenance keys exactly `{ref, git_commit, blob_sha256}`; citation gate `LedgerStore.verify_commit(...)` BEFORE any DAS write; gate failure → 400 with the §2.5 actionable/retryable strings; 200 gains `top_handle`; `provenance_link` retires.
- **FR-005 — `LedgerStore`** (§2.3): rewrite of `provenance_store.py` keeping the module name, `ArchiveError`, flock/git plumbing; methods `ensure_repo()`, `record(ref, sha256)`, `verify_commit(git_commit, ref, sha256)`; `_validate_ref` replaces `_validate_url`; retired: `archive()`, `lookup()`, subject parsing.
- **FR-006 — Plugin resolver/sha256/cache/receipts** (§2.5, §5): `_resolve_source(ref)` — URL: bounded fetch (≤2 MB, text, ≤20 s); path: `dasWriteSourceRoots` prefix check then read; `sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()`; per-process cache `ref → (sha256, commit)`; two-call flow `/v1/source` → `/v1/write`; receipt `BRIDGE-PERSIST-OK: verified=<n> top=<top-handle> [stv=(s,c)]`; every failure mode → `BRIDGE-PERSIST-WRITE-FAILED: <reason>` (§2.5 complete list), never raises; `ARCHIVE-OK`/`ARCHIVE-FAILED`/`archive-source` skill RETIRED (D7).
- **FR-007 — Reconstruction script** (§2.4): CLI exactly per §2.4 (`--trace-file|--trace`, `--ledger-repo`, `--facts`, `--handles`, `--mongo-container`, `--case`, `--json`, `--source-paths-out`, `--background-dir`, `--legacy-repo` optional-informational only); exit codes 0/2/1; handle chain spine per §2.4; classification rules (stored facts / query clause exempt / exec outputs exempt / derivation = premises' sources); output JSON shape per §2.4; mongo via ONE bounded `find({_id: {$in: [...]}})`; zero LLM, zero pattern-engine queries; location `deploy/das/write-bridge/tools/reconstruct_sources.py` + `tools/README.md`.
- **FR-008 — Gate conditions** (§2.6): `E_NO_INGEST` blocking iff FIRST case AND `window_persist_receipts == 0` (receipts-only, resolution 6); `E_INGEST_ATTESTED_VIA_FACADE_LOG` RETIRED; `P_MISSING` blocking (knowledge case, reconstruction finds no citable provenance; unsolvable exempt); `P_UNRESOLVED:<expr12>:<COND>` blocking with `COND ∈ {COMMIT_NOT_IN_REPO, COMMIT_UNREADABLE, COMMIT_NOT_A_LEDGER_COMMIT, COMMIT_TOUCHES_OTHER_FILES, COMMIT_ADDS_NOT_ONE_LINE, ENTRY_PARSE_FAILED, REF_SHA_MISMATCH, NO_PROVENANCE_ATTRS}`; `P_SOURCE_SET_MISMATCH` informational; `H_MISSING`/`H_COUNT_MISMATCH`/`H_MISMATCH` blocking (D4); legacy codes retire (kept only in the standalone unwired `provenance_check.py`); `Q_*`, `A_*`, `R_*`, remaining `E_*` unchanged; harness exit codes 0/2/1 unchanged.
- **FR-009 — Preflight v4** (§8 item 7, resolution 5): `write_bridge_smoke` exercises the FULL v4 path (`/v1/source` clearly-labeled smoke ref → `/v1/write` → validate `top_handle`); the `provenance_repo` check becomes the REQUIRED ledger-format check; ADD das-write grammar-version check (v3 marker grep); REMOVE/REPLACE any `/v1/archive`/`ARCHIVE-OK` checks; judge/das-read/agent checks unchanged; optional `dasWriteSourceRoots` check.
- **FR-010 — Answers-block format v4** (§2.7): `HANDLES:` line added (aligned by order with FACTS; copied from write receipt `top=` or das-retrieve results handles); `SOURCES:` line REMOVED; `source …` record lines REMOVED; record line becomes `expr <expression> top=<handle>`; `query`/`exec`/`trace` lines unchanged.
- **FR-011 — Cleanup N3** (§8 item 8): for each discovered benchmark fact expression, compute `top_handle` client-side, delete links targeting the Symbol node `"fact:<top_handle>"` with leading-symbol target `WriteProvenance` — never all WriteProvenance links, never CampaignProvenance; residue invariant extended (remaining companions == 0); N1 regex keeps `$or` on `provenance_ref`/`provenance_url` for pre-migration residue.

### Key Entities *(include if feature involves data)*

- **SOURCE-LEDGER.json entry**: `{ref, sha256, entry_date}` — identity is the `(ref, sha256)` pair; anchor is the ledger commit.
- **Provenance atom attributes** (top link only; no companion atoms for new writes): `metta_expression`, `provenance_ref`, `provenance_git_commit`, `provenance_blob_sha256`, optional `stv_strength`/`stv_confidence` (Appendix).
- **Receipts**: `BRIDGE-PERSIST-OK: verified=<n> top=<handle> [stv=(s,c)]` (the `verified=<n>` leading segment is a preserved prompt contract; `handles=<first3>` segment RETIRED) and `DAS_RETRIEVE_OK … results=` (carries atom handles; item 10).
- **Gate conditions**: H_*, P_*, E_NO_INGEST per FR-008; harness exit codes 0/2/1.
- **Handles**: deterministic (type+targets hash); mongo `_id`; claimable by the agent from receipts, re-derivable deterministically client-side.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Live e2e 3/3 PASS on the OVH host (or documented genuine external blocker with evidence); every failure iteration carries a classified root-cause note (§12).
- **SC-002**: Every ledger append is a pure +1-line diff; dedup returns the original commit; the citation gate rejects every fabricated/mismatched triple with the §2.5 strings (§4).
- **SC-003**: The reconstruction script is deterministic (same inputs → same JSON + exit code), zero-LLM, zero pattern queries; happy path exit 0; missing-attr exit 2; outage exit 1 (§7).
- **SC-004**: grep confirms no `ARCHIVE-OK`/`SOURCES:`/`add_atom_shas` references remain in the v4 grading path; no ingest-census fields in the grade path; the full gate-audit table committed in `GATES-REFERENCE.md` (§8).
- **SC-005**: Budget-exhaustion rate ≤ the wr3n baseline (0/3 agent-side, commit `6684f4f`, artifacts `tests/reasoning-windowless-room/results/wr3n-20261026/`); residue invariants zero after cleanup (§9).

## Assumptions

- Decision gate CLEARED: D1-D7 RESOLVED as defaulted (Balazs 2026-10-27 22:37 UTC; §10); the six resolved inconsistencies (§11) are folded in and are not to be re-litigated.
- Phase 0 probes confirm the mongo `_id`=handle field name and the attribute-overwrite semantics live (VERIFY — do not assume; §3).
- The reconstruction script never joins a service bus (mongo-direct); the facade stays egress-free; the plugin is the ONLY egress point (§0).
- D1 trade-off accepted: source content is NOT archived anywhere — verification = sha256 vs harness-known files (§10, §11 residual risk 1).
- Migration is operator-executed (Phase 3 runbook over SSH); evidence is never mutated by scripts (D6, §6).
- Dormant campaign prompts (`deploy/omega/prompts/*.txt`) are historical records and are LEFT untouched (§13 item 4).
