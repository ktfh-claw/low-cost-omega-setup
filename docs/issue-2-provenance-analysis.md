# Issue #2 — Move provenance data from agent instructions to write-das

**Impact analysis + implementation plan + input specification** (analysis-only deliverable, 2026-10-27)
Repo: `ktfh-claw/low-cost-omega-setup` (the bridge repo). Issue: ktfh-claw/low-cost-omega-setup#2 — *"move provenance data from agent instructions to write-das"*.

> **v4 amendment (2026-10-27, Balazs directive 22:15 UTC — supersedes this document's former §3.2/§5/§6 schema and the v3-with-fingerprint grammar):** the proposed `SourceRecord` atom and **every dedicated fact→source link atom are dropped** (custom-attribute-primary); the offline provenance repo is re-designed as a **single-file `SOURCE-LEDGER.json`** git store (source **content is no longer archived anywhere** — ledger-only, decision D1); the write-skill grammar becomes **v3: ref-only, mandatory in the v3 shape, no agent-supplied fingerprint, no git sha anywhere in the grammar**; the answers block gains a **`HANDLES:`** line (fabrication tripwire, decision D4); the reconstruction script is **mongo-direct** and standalone. §2 (verified current state) is unchanged. The next-iteration work order (phases, files, acceptance criteria, tests) is `docs/issue-2-implementation-spec.md`.

---

## 1. The issue and the intent

### 1.1 Issue text (verbatim summary)

Today DAS entries do not automatically save their source data and don't link it to the archive store in the local git repo. In the windowless-room reasoning-and-provenance test, all the archiving rules are built into the task prompt. They should be made independent of the test: the archives addition (if new source) should happen automatically; a new atom should represent the source (git sha) and DAS should link to it all the concepts/predicates derived from that source. A standalone script to reconstruct the list of sources for each used predicate in a reasoning trace should be part of the repo, and the windowless test script should just use that script and fail the test if any source is missing.

### 1.2 Clarifying intent (Balazs, voice, 2026-10-27; superseded for the schema details by the 22:15 UTC directive)

Provenance/archivation becomes **transparent to the agent**. The write-das skill input includes the **source reference** (local file path or URL) plus a **content fingerprint** (e.g. sha256). Inside the skill, a deterministic path ensures that when a new source is referenced, the atom for the fact AND the atom for the source record AND the link between them are written to DAS **together**. The agent only worries about writing its facts + naming the source. The benchmark prompt no longer instructs archiving/provenance bookkeeping; the evaluation reconstructs sources deterministically from the reasoning trace + provenance atoms, **without agent cooperation**.

> **v4 directive (2026-10-27 22:15 UTC), which wins where it conflicts with §1.2:** no dedicated source atom and no dedicated link atom at all — *"we don't need a dedicated Atom"*; provenance lives in the fact atom's `custom_attributes` + the ledger repo; the fingerprint is plugin-computed (never agent-supplied); the agent is not even aware of provenance tracking (no archive-source step, no sha handling, no SOURCES line — it only writes facts citing the source ref, records `expr` lines + handles, queries, reasons, answers).

### 1.3 Hard constraints

- NO modification to upstream DAS or Omega source. Everything config-driven within this repo's existing pattern: the `das-write` plugin (runtime `:ro` mount of `deploy/omega/plugins/das-write/`, wired via `deploy/omega/plugins.yaml.overlay`) intercepts the `&persistent` hook; the write-bridge facade is a compose service (`deploy/das/write-bridge/`).
- This iteration delivers the amended analysis + the implementation specification only. No implementation.

---

## 2. Current state (verified, with file:line)

### 2.1 The write path (v2, live since 2026-10-21)

**Plugin** — `deploy/omega/plugins/das-write/das_write_bridge.py` (540 lines):
- `intercept()` rebinds the `metta` skill clause (remove-then-add single-definition invariant, `das-write.metta:24-36`) and handles `(add-atom &persistent <expr> [suffix])`:
  - v1 shape: bare expression → POST `/v1/write` `{metta, verify:true}` (`das_write_bridge.py:344-349`).
  - v2 suffix: quoted http(s) URL **plus** quoted `"git:<40hex>"` (must appear together), optional `(stv s c)` (`:235-302`, rule at `:297-298`). Suffix limits: URL ≤ 480 chars, no whitespace (`:88`, `:262`); expression ≤ 2048 chars (`:85`, `:347`, `:356`).
- `archive_source(url)` skill (`:443-540`): **agent-side** fetch (2 MB cap, text content types only, 20 s timeout), then POST `/v1/archive` `{url, content, content_type}` → returns `ARCHIVE-OK git:<sha> sha256:<blob> path=<repo path> (new|deduped)`.
- Gated on Omega config keys `dasWriteEnabled` / `dasWriteOrigin` (stock config API; `:107-117`, `:369`). Statuses: `BRIDGE-PERSIST-OK: verified=<n> handles=<...> [provenance=<link>] [source=archived] [stv=(s,c)]` (`:394-406`; today only the **first 3** of all atom handles are shown, `:395-398`), `BRIDGE-PERSIST-WRITE-FAILED: <reason>` (never raises).

**Facade** — `deploy/das/write-bridge/app.py` (ThreadingHTTPServer):
- `/v1/write` body keys `{metta, verify, provenance, tv}` (`:31`); body cap 16 KiB (`:14`); provenance writes require `WRITE_PROVENANCE_REPO` configured (`:50-52`).
- **Citation gate** (provenance v2.1): `ProvenanceStore.verify_commit(git_commit, url)` runs BEFORE any DAS write — commit must exist in the archive repo AND its subject must archive exactly that URL; failures are actionable 400s (`:56-60`). Note: `verify_commit`'s **return value (which includes `blob_sha256`, `provenance_store.py:268-275`) is discarded** by `app.py:58` — relevant to §3.2.
- `/v1/archive` body cap 8 MiB (`:18`), delegates to the store.
- Provenance repo env/mount: `WRITE_PROVENANCE_REPO=/var/lib/omega-provenance`, host bind `/home/ubuntu/omega-provenance` (`compose.write-bridge.yaml:67,71`).

**Write runner** — `deploy/das/write-bridge/write_client.py`:
- `write()` (`:204-264`): parse via `metta_to_atoms.parse_fact` (single expression; **no escapes, no raw newlines in quoted literals**; caps: 2048 chars, 256 atoms, depth 32, 512 chars/literal — `metta_to_atoms.py:30-32`, `:307-339`); decorate the fact's TOP link `custom_attributes` with `metta_expression` + `provenance_url` + `provenance_git_commit` (+ stv) (`:108-128`, best-effort server-side extraction); build the companion atom `(WriteProvenance "fact:<top_handle>" "git:<sha>" "url:<url>" "ts:<fetched_at>")` (`:131-139`); write **fact atoms + companion atoms in ONE `add_atoms` batch** (`:241-245`); mandatory read-back verifies BOTH the fact links and the companion links (`:253-256`).
- `add_atoms` is **fire-and-forget** (client-constructed handles, no server ack; `:20-27`, `:266-278`); a failed/unverified write raises `WriteFailure` with the deterministic handles.
- Handles are deterministic (type+targets hash only; decoration never changes identity/dedup — `:60-63`).
- Two structurally disjoint service buses (atomdb vs pattern query) — **a mis-routed atomdb command crashes the query engine** (upstream defect; `:8-19`).

**Archive store** — `deploy/das/write-bridge/provenance_store.py`:
- Content-addressed blob `sources/<yyyy>/<mm>/<sha256>.<ext>` + append-only `index.jsonl` (url, blob_sha256, path, content_type, fetched_at, archived_at); one commit per source, subject `archive: <url> <blob12>`; dedupe by `(url, blob_sha256)` returns the ORIGINAL commit; flock-serialized (`:108-199`).
- `verify_commit()` (`:212-278`): commit exists + subject URL match; returns `{commit, url, blob_sha256, path, archived_at}`.
- `_validate_url` is **http(s)-only** (`:354-367`) — relevant for local-path refs (§4.4).

### 2.2 The benchmark (windowless room, v16)

`tests/reasoning-windowless-room/`: `run_benchmark.py` (1723 lines), `grading.py` (855), `provenance_check.py` (178), `history_parse.py` (126), `facts.py`, `agent_prompt_template.md` (105), plus 16 unit test modules.

Five strict gates per case (blocking unless listed informational — `grading.py:529-533`):
- **A** — LLM judge on the FINAL ANSWER line (single TRUE/FALSE call).
- **Q** — query-first: quoted `DAS_RETRIEVE_OK ... count=<n>` receipt, non-degenerate, in-window history or log-attested, harness re-issue with matching count.
- **E** — extraction-record discipline: non-empty facts-index; **first case must show ≥1 `ARCHIVE-OK` AND ≥1 `BRIDGE-PERSIST-OK` receipt in-window** (`E_NO_INGEST`, `grading.py:676-692`; attested via facade-log lane `E_INGEST_ATTESTED_VIA_FACADE_LOG`, `:684-690`); FACTS line resolves against the index (`E_FACTS_NOT_IN_INDEX`, `:695-702`); query literals from the extracted vocabulary (`:705-710`); presence probes (`E_INDEXED_NOT_PERSISTED`, informational, `:719-733`).
- **R** — executed, grounded MeTTa reasoning trace (`:747-822`).
- **P** — citations from the answers block's `SOURCES:` line resolve through the provenance git repo: commit exists → exactly one `sources/` blob + `index.jsonl` change → index entry at commit matches blob path → sha256(blob) matches entry → entry url matches citation (`provenance_check.py:70-147`); blob reconstructed + byte-compared against the repo background files (`run_benchmark.py:1017-1045`).

**The prompt carries the entire provenance discipline** (`agent_prompt_template.md`): pinned ledger, step 1 = per-file `archive-source` call + full-receipt `source <filename> git:<sha> sha256:<blob> path=<repo path> <url>` record lines + per-fact `expr` record lines; copy-not-compose rules for FACTS: and SOURCES: lines (`:43-46`, `:59-60`, `:81-92`).

### 2.3 Known environment quirks (live-verified, load-bearing)

1. Ground (variable-free) patterns **never complete** in the pinned engine — read-back and presence probes use variable-bearing forms (leading-variable form `metta_to_atoms.py:127-150`; alternate form with variable at position 2, `:153-192`; last-element-variable form in `grading.py:199-250`). **Multi-variable patterns have never been live-validated.**
2. `add_atoms`/`delete_atoms` are fire-and-forget; delete apply is starved by sustained query traffic (alternate-pattern oracle + bounded standby, `cleanup.py:60-78`).
3. History channel collapses tool results to `$_` (PeTTa superpose/collapse) — hence record files + docker-log attestation lanes (`run_benchmark.py:255-333`).
4. Per-wake restarts collapse tool results — the record file + pinned ledger are the only cross-cycle memory.
5. Quoted literals become Symbol nodes **with the quotes kept in the name** (`metta_to_atoms.py:9-11`); the engine's own MettaParser follows the same convention (live-proven: metta-form das-retrieve queries with quoted literals match stored atoms, and WriteProvenance read-back verification passes — `docs/status.md:239` records `verified=16 … provenance=<handle>`).
6. **Mongo link/node documents are keyed by `_id` = the atom handle** (`deploy/das/write-bridge/tests/iter16_groundtruth.js:8-12` — `db.links.countDocuments({_id: …})`, `db.nodes.countDocuments({_id: …})`); `custom_attributes` ride on the link documents (`write_client.py:111-117`) and are **invisible to the pattern-matching engine** (pattern answers carry handles only — `write_client.py:307-343`).

---

## 3. Analysis (v4 design)

### 3.1 Separation design: who does what, and what the agent may be trusted with

**The core move (unchanged in spirit, radical in the agent surface):** today the agent executes a 3-step discipline (fetch+archive via `archive-source`, transcribe the sha into the record, attach the sha to every `add-atom`). Issue #2 pushes ALL of it into the skill. Under v4 the agent performs exactly one provenance-relevant act: **it writes the fact and names the source ref**. It is not aware of provenance tracking at all — no archive step, no source record lines, no SOURCES line, no sha handling (§3.5).

**Who resolves the ref — the plugin (agent-side), NOT the facade.** Unchanged rationale from v3, still valid:

- The plugin runs **inside the agent container** (`das-write.metta:1` mounts `das_write_bridge.py` into the Omega plugin tree), so it can both fetch URLs (existing bounded fetch, `das_write_bridge.py:461-489`, 20 s timeout `:90`) and read container-local files. The facade runs in a different container whose **only** host mount is the provenance repo (`compose.write-bridge.yaml:71`) — it structurally cannot read agent paths, and it has **zero outbound HTTP code** today; adding egress would move an SSRF surface into the network segment that hosts mongo/query-engine traffic. Keep the facade egress-free.
- Facade-side fetch would put a network timeout inside `/v1/write` latency; agent-side fetch keeps the write POST bounded at its current 15 s (`das_write_bridge.py:99`).

**Who computes the fingerprint — the plugin, over content it fetched/read itself.** The v4 grammar has **no agent-supplied fingerprint** (the v3-with-fingerprint design is dropped): the plugin resolves the ref, computes `sha256` of the source content, and ledger-appends via the facade. Because the sha is **plugin-computed code, not agent-claimed text**, the fake-sha fabrication vector (three confirmed cases, `docs/status.md:234`) is structurally eliminated — the agent never types a hex digest anywhere. The URL-drift window (content changed between the agent's read and the skill's fetch) remains and is **detected, not prevented**: the harness byte-hash check compares `sha256(repo background file) == entry sha256` at grade time (§7, residual risk §11 of the spec).

**What crosses to the facade — the pair `{ref, sha256}` only, never content.** The facade stays egress-free and keeps its 16 KiB body cap (`app.py:14`); the 8 MiB `/v1/archive` content path dies with the old store (`app.py:18`, `:82-99`). The poisoning surface *shrinks*: today `/v1/archive` accepts arbitrary content into the host repo; under v4 the ledger records only `(ref, sha)` metadata.

**Failure modes of the new flow** (URL unreachable at write time; path unreadable; path outside configured roots; content-type unsupported; facade down): all surface as `BRIDGE-PERSIST-WRITE-FAILED: <reason>` — the plugin never raises; the agent sees a single actionable status per attempt, same contract as today (`das_write_bridge.py:45-54`). Retry is idempotent: ledger dedup on `(ref, sha256)` returns the original commit, and handles are deterministic so a re-write is a no-op server-side (`write_client.py:60-63`).

**Latency:** first write per source = one bounded fetch (≤20 s) + 2 POSTs (`/v1/source`, then `/v1/write`); a per-process `ref → (sha256, commit)` cache makes every subsequent fact citing the same source a single `/v1/write` POST.

### 3.2 Provenance representation — custom-attribute-primary, NO new atoms (v4)

**Dropped from the v3 design (Balazs 22:15 UTC: "we don't need a dedicated Atom"):** the `SourceRecord` atom, the `DerivedFrom` link, the 6-arity WriteProvenance extension — and, for **new writes**, the WriteProvenance companion itself (decision D2, default: drop; the design is custom-attribute-primary).

**What remains:** the fact atom's TOP-link `custom_attributes` (already written today, `write_client.py:108-128`) become THE provenance channel:

| Attribute | Value | Source |
|---|---|---|
| `metta_expression` | the written expression | unchanged (`write_client.py:121`) |
| `provenance_git_commit` | `"git:<40hex>"` — the **ledger commit** sha (the provenance anchor) | changes meaning: ledger commit, not archive commit |
| `provenance_ref` | the http(s) URL or absolute container path | replaces `provenance_url` |
| `provenance_blob_sha256` | `"sha256:<64hex>"` — plugin-computed sha256 of the source content | NEW |
| `stv_strength` / `stv_confidence` | PLN truth value | unchanged (`:126-127`) |

- Decoration never changes atom identity or dedup — handles are type+targets hash only (`write_client.py:60-63`), so the custom-attribute store is a pure enrichment of the same atoms the pattern engine serves.
- `custom_attributes` are invisible to pattern-matching queries (answers carry handles only, `write_client.py:307-343`), so **mongo-direct is THE provenance access mode** (§3.4): link documents are keyed by `_id` = handle (`iter16_groundtruth.js:8-12`), and the harness already has the `docker exec mongosh` precedent (`run_benchmark.py:504-510`).
- **The join is fully deterministic and client-side:** the reconstruction script re-parses each trace expression with `parse_fact` (`metta_to_atoms.py:90`) and re-derives `top_handle` (`:196-257`) — no DAS query is needed to get from expression to handle. The old §3.2 multi-variable-pattern probe, candidate-probe fallbacks and read-proxy reverse-lookup tables are ALL obsolete: mongo-direct does not touch the pattern engine, so none of the §2.3.1 quirks apply to provenance anymore.
- **Read-back contract change (honest):** today `verified=<n>` covers the fact links AND the companion links (`write_client.py:253-256`); with the companion gone, the receipt verifies only the fact's own atoms. Custom-attribute persistence is best-effort server-side (`write_client.py:111-117`) and **cannot be verified through the pattern engine** — a silently-dropped attribute no longer fails the write receipt; detection moves to the reconstruction gate (case FAIL, exit 2). Accepted residual risk (spec §11); an optional Phase-1 mongo-side post-write attribute canary is specified there.

### 3.3 The source ledger repo (new provenance store format)

**Old store — retired, backed up (decision D6):** content-addressed blobs `sources/<yyyy>/<mm>/` + `index.jsonl` (`provenance_store.py:108-199`), url-keyed with http(s)-only validation (`:354-367`), at host `/home/ubuntu/omega-provenance` / container `/var/lib/omega-provenance` / env `WRITE_PROVENANCE_REPO` (`compose.write-bridge.yaml:67,71`).

**New store — a FRESH repo at the SAME host path (compose/env unchanged) containing a single file `SOURCE-LEDGER.json`:**

- A JSON **array**; each element contains **exactly three fields**: `ref` (http(s) URL or absolute container path), `sha256` (of the source content, plugin-computed), `entry_date` (ISO-8601 UTC, `%Y-%m-%dT%H:%M:%SZ` — the `archived_at` precedent, `provenance_store.py:139`).
- **Serialization: one array element per line, so each append is exactly a +1-line diff.** The unique valid-JSON form with pure one-line insertions uses **leading commas** (first element line starts `{`, every later element line starts `,{`):

```json
[
{"ref": "https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/main/tests/reasoning-windowless-room/background/spatial-knowledge.md", "sha256": "9f2c…64hex", "entry_date": "2026-10-28T09:00:00Z"}
,{"ref": "https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/main/tests/reasoning-windowless-room/background/lighting.md", "sha256": "1ab3…64hex", "entry_date": "2026-10-28T09:00:01Z"}
]
```

  An append inserts one line before the final `]` — no existing line changes, `git diff` is exactly one added line, and the file remains a valid JSON array. (A conventional trailing-comma-free array makes every append a 2-add/1-del diff — the leading-comma form is what literally satisfies the directive; format is pinned in the spec §2.3.)
- **Each new ledger entry = exactly ONE new git commit; the commit hash is the provenance anchor.** Commit subject: `ledger: <sha12> <ref>` (informational only — verification NEVER parses the subject, unlike the v2.1 gate).
- **Dedup:** if `(ref, sha256)` is already in the ledger, `record()` returns the ORIGINAL entry's commit — idempotent, no new commit, no file change. (The original commit is re-found deterministically via `git log -S"<entry line>" --reverse` — the pickaxe finds the commit that added that exact line.) The same ref with *different* content (drift across runs) is a **new** entry and a new commit — atoms carry both `provenance_ref` and `provenance_blob_sha256`, so the atom→commit→entry check stays unambiguous.
- **Ledger verification chain (replaces the old commit→blob→index chain, `provenance_check.py:70-147` → legacy):** commit exists → `git show` diff of that commit touches **only** `SOURCE-LEDGER.json` and adds **exactly one line** → the added entry's `(ref, sha256)` equals the atom's provenance attributes → optional byte-check: `sha256(known source file) == entry.sha256`. Simpler, fully deterministic, no subject parsing, no blob reads.

**Decision D1, stated honestly:** the ledger has exactly 3 fields and the repo a single file — accepted per directive. **Trade-off: source content is no longer archived anywhere.** Verification = sha256 vs harness-known files; the benchmark is unaffected (the harness holds the background files and can hash them directly — the existing byte-compare lane, `run_benchmark.py:1030-1037`, changes input from blob-bytes to file-bytes); **general campaigns lose byte-level evidence of what the agent actually read.** Default: ledger-only per directive; a content-blob extension (a second file or sidecar blob per entry) is a possible later addition, out of scope here.

**Migration & legacy:** backup + retire the old repo (git bundle + tar to a sibling path, e.g. `/home/ubuntu/omega-provenance.legacy-<date>.bundle`); fresh init at the SAME host path with an initial commit containing the empty array `[`↵`]` (operator runbook — spec Phase 3, NOT automated). Old atoms (campaign corpus + old benchmark companions) reference old-repo commits: keep the backed-up repo readable at a known path; the reconstruction script accepts an optional `--legacy-repo` fallback resolving pre-migration shas through the OLD chain — **informational only**. Campaign atoms keep their `CampaignProvenance` companions (`deploy/das/import-wrapper/import_wrapper.py:249-256`); old benchmark-run companions are swept once (§4.5, D2).

### 3.4 The reconstruction script (mongo-direct, standalone)

**Interface (full spec §7):** trace in → per-expression / per-predicate source lists out. Exit `2` = some used stored fact's source is missing/unresolvable (= case FAIL); exit `0` = all sources resolve in the ledger repo; exit `1` = harness error. Optional `--source-paths-out` emits the list of source path files used (for byte-hash checks).

**Deterministic handle chain (per the directive):** trace expr → `parse_fact` → `top_handle` → claimed-`HANDLES` cross-check → `db.links` lookup by handle (`_id`, verified `iter16_groundtruth.js:8-12`; live-canary re-verification is a Phase-0 probe) → `custom_attributes.provenance_git_commit` → git commit in the ledger repo → diff adds exactly one ledger line → entry `(ref, sha256, entry_date)` → optional `sha256(known source file) == entry.sha256` byte-check.

**Access mode: mongo-direct** (`docker exec mongosh`, `run_benchmark.py:504-510` precedent). Custom attributes are invisible to the pattern-matching engine (§2.3.6) — **mongo is THE provenance channel now**. This also retires the v3 design's read-proxy enumeration mode, its multi-variable pattern probe, and the mis-routed-bus risk for the script: mongosh never joins a service bus.

**Classification rules (documented in the script):**
- *Stored facts* — ground expressions present in DAS (`db.links` hit on the re-derived handle): each MUST carry ≥1 resolvable source (attrs → ledger chain). A link that exists without provenance attributes is a **missing source** (condition `NO_PROVENANCE_ATTRS`) — except the documented legacy carve-out (pre-migration atoms resolve via `--legacy-repo`, informational).
- *Query clause* (variable-bearing first step) — **exempt**: not a stored fact.
- *Interpreter-derived outputs* (`exec` lines; `call => output` steps) — **exempt**: not stored atoms; a derivation's sources = its premises' sources (`grading._split_derivation_atoms` reuse, `grading.py:447-460`).
- **Per-predicate aggregation** = group by leading symbol of the stored steps — so "the list of sources for each used predicate" is served at both granularities.

**Agent cooperation: none.** The script is a pure function of (trace, DAS content, ledger repo state); no LLM, no prompt reading. The claimed `HANDLES:` line is an INPUT (cross-check only) — handles are deterministically re-derivable client-side, so the agent's claim is a **fabrication tripwire, not a lookup dependency** (§3.5, D4).

**Where it lives:** `deploy/das/write-bridge/tools/reconstruct_sources.py` + its own README (documented, invocable independently of the e2e test). Rationale: it imports the bridge's `metta_to_atoms.parse_fact` for deterministic handles and lives next to the schema it reads; the benchmark harness invokes it as a CLI (it already shells out to `docker exec`/`sudo git`, `run_benchmark.py:504-510`, `:391-396`).

### 3.5 Benchmark impact — what can go, what stays, what breaks (v4 touchpoint table)

**Prompt (`agent_prompt_template.md`) — the agent is NOT aware of provenance tracking. Removable:**
- The entire step-1 archive sub-step (`:43`): the `archive-source` call, the `source <filename> git:<sha> sha256:<blob> path=... <url>` record lines — gone. This removes the whole class of sha-transcription failures (wr3m: re-typed sha; wr3m: fabricated URL; wr3i: one-position sha/url mispairing).
- The `add-atom` call form loses the `"git:<sha>"` argument (`:44`) → `(add-atom &persistent (<expr>) "<source-url>" (stv 0.9 0.8))` — the agent cites the ref only, copies from `urls.txt`.
- The `SOURCES:` line + ALL its copy-not-compose rules (`:60`, `:81`, `:91-92`) — the P-gate switches to reconstruction-derived sources.
- The first-cycle ledger bootstrap's archive lane (`:34`) — the ledger keeps its shape but step 1 has no archive sub-step.
- The "pin a few critical receipts (counts, shas, stv outputs)" sha component (`:101`) — the agent never handles a sha at all.

**Prompt — must stay:** the two deliverables; the gate-format rules for QUERY/FACTS/REASONING/FINAL ANSWER; the `expr` record lines (**E-gate FACTS grounding reads only `expr` lines — verified: `parse_facts_index` (`grading.py:175-196`) strips the `expr` label and takes the balanced expression prefix (`grading.py:144-172`), skipping `source ...` lines by design; the NEW record line `expr <expression> top=<handle>` is a tolerated trailing annotation under the exact same v9 mechanism); `exec` lines (R-gate, `grading.py:113-126`); the query/retrieve discipline; anti-loop rules; STOP rule. `urls.txt` stays as the source-ref vocabulary (rendered from `SOURCE_URLS`, `run_benchmark.py:733`; `facts.py:12-18`) — one line of instruction instead of a receipt pipeline.

**Prompt — NEW:**
- The record line becomes `expr <expression> top=<handle>` — the handle copied verbatim from the write receipt.
- The answers block gains `HANDLES: <h1> <h2> ...` — the atom handles of the FACTS-line expressions, aligned by order, each copied from the write receipt (the receipt must therefore surface the fact's TOP-LINK handle; today it shows only the first 3 of all handles, `das_write_bridge.py:395-398` — the facade response gains `top_handle`).

**grading.py / run_benchmark.py — exact touchpoints that break under transparency (must change in the same iteration):**

| # | Touchpoint | What breaks | Required change (v4) |
|---|---|---|---|
| 1 | `grading.py:676-692` (`E_NO_INGEST`) | requires ≥1 `ARCHIVE-OK` receipt — no agent archive calls exist under v4 → first case always fails | condition reduces to `window_persist_receipts == 0` (the write IS the ingest); attested lane: `write_count ≥ 1 AND source_count ≥ 1` |
| 2 | `grading.py:684-690` + `run_benchmark.py:328-331` (attestation lane) | `archive_count` counts `POST /v1/archive` — the endpoint dies | lane rewires to `POST /v1/source` → `source_count` (regex change); `write_count` unchanged |
| 3 | `grading.py:824-839` + `run_benchmark.py:964-1045` (P-gate) | citations come from the block's SOURCES line + in-window `add-atom` shas — both gone under v4 | P-gate rewires to the **reconstruction script output** over the case's trace (+ FACTS/HANDLES lines); the reconstruction/byte-compare lane's shas come from the same output |
| 4 | NEW: HANDLES gate | `HANDLES:` line did not exist | new conditions `H_MISSING`, `H_COUNT_MISMATCH`, `H_MISMATCH` — claimed handles vs **deterministically re-derived** `top_handle` (fabrication tripwire; blocking per D4) |
| 5 | `history_parse.py:110-116` (`extract_add_atom_shas`), `:124-126` (`extract_archive_receipts`) | v3 add-atom lines carry refs, not `git:<sha>`; no ARCHIVE-OK receipts exist | retire both lanes from the v4 grade path (keep the functions for legacy-run re-grades — they read old history formats) |
| 6 | preflight (`run_benchmark.py:367-370` smoke write; `:410-415`, `:427-438` grep checks) | smoke writes a suffix-less fact (D3); no check that the v3 grammar is deployed | keep the smoke (permissive D3 default); ADD a grammar-version grep on the mounted `das-write.metta` (same pattern as `skill_description_upgraded` / `metta_skill_upgraded`) |
| 7 | cleanup nets (`run_benchmark.py:513-584`) | N1 regexes `custom_attributes.provenance_url` (`:533-542`) — new writes carry `provenance_ref`; **companion links leak past both nets** (§4.5) | N1 matches `provenance_ref` **and** keeps `provenance_url` (pre-migration residue); NEW one-time sweep net N3 for old WriteProvenance companions, scoped to cleaned benchmark fact handles (§4.5) |
| 8 | pinned unit tests (`unit/test_v14_prompt.py` ×5, `test_v11_prompt.py` ×4, `test_v12_prompt.py` ×4, `test_v8_prompt.py` ×9, `test_v6_prompt.py` ×10, + `test_grading.py`, `test_v3/v9/v10/v11_gates.py`, `test_history_parse.py`, `test_prompts_render.py`) | assert the removed archive/SOURCES/sha rules | rewrite to the slim prompt + new gates; new modules for the ledger chain, reconstruction script, HANDLES gate (spec Phase 6 lists them) |

**Gates that stay unchanged in substance:** A (judge), Q (query-first — untouched), R (trace shape/execution/grounding), and the E-gate's FACTS/vocabulary/presence logic. `E_FACTS_NOT_IN_INDEX` keeps working against `expr … top=<h>` record lines via the balanced-prefix parser (`grading.py:144-172`).

**Wake-cycle budget:** step 1 loses ~1 call per source (archive) + the record line + the sha-transcription churn; the largest win is eliminating the highest-variance failure classes that burned whole 75-minute windows (sha corruption, URL fabrication, receipt-backfill loops). The agent's per-fact work is: add-atom + one record line — strictly less than today.

**New failure modes introduced by transparency (and answers):**
- **Bridge down ⇒ no facts at all?** Only if the write path hard-requires a source ref. Default D3: **permissive** — v1 suffix-less writes stay valid (preflight smoke `run_benchmark.py:367-370`, canaries, and dormant campaign prompts keep working unchanged); enforcement lives in the gate (reconstruction fails any graded fact without a resolvable source).
- **Fact↔source correctness becomes undetectable?** Same honest answer as v3: semantic misattribution (citing file A while deriving from file B) is not mechanically decidable — the agent chooses the ref. It becomes MORE detectable at the bookkeeping level: the reconstruction output is per-fact, so the harness cross-checks that the set of sources attached to the case's facts ⊆ the case's background source set (informational `P_SOURCE_SET_MISMATCH`), and the byte-hash check pins each entry's sha to the repo background file.
- **Orphan companions / stale residue:** the pre-existing leak (§4.5) is fixed in the same iteration with net N3.

---

## 4. Critical review — inconsistencies, races, security, design conflicts (v4)

### 4.1 The 2048-char cap and suffix headroom (grammar got simpler)

The 2048 cap applies to the **fact expression only** (`das_write_bridge.py:347,356`; facade `WRITE_MAX_METTA_CHARS`, `app.py:24`) — not to the suffix (parsed plugin-side, sent as JSON fields). Suffix budget: ref ≤ 480 (existing `MAX_PROV_URL_CHARS`, `das_write_bridge.py:88`) + optional `(stv s c)` (~20 chars) ⇒ ≤ ~510 chars of suffix; benchmark fact expressions are ~60–120 chars. Headroom is ample. **The plugin suffix parser SIMPLIFIES:** the `git:<40hex>` token branch (`:266-272`, `:279-286`), the url+git pairing rule (`:297-298`), and the fingerprint token (v3 design, never shipped) all disappear; a `git:` token in the suffix becomes an actionable error ("pass the source reference, not a commit"). **The v2 shape (`"url" "git:<sha>"`) becomes INVALID after the store migration:** its citation gate verifies commit subjects against the ledger repo — v2 commits are `archive:`-subject commits that do not exist there, so every v2 write would 400. The spec therefore says **v2 is removed** (plugin-side rejection with an actionable message), not silently tolerated. Suffix-less v1 writes are decision D3 (default: permissive).

### 4.2 The evaluator join — mongo-direct, no engine queries at all

The v3 design's hardest question (can the evaluator enumerate provenance through the pinned engine's variable-pattern quirks?) is **moot under v4**: `custom_attributes` are invisible to the pattern engine (§2.3.6), so mongo-direct is the only possible channel anyway — and it is deterministic. The handle side of every join is computed client-side by re-parsing trace expressions with `parse_fact` (deterministic handles, `write_client.py:60-63`); the attribute side is one `db.links.find({_id: <handle>})` per distinct handle. No multi-variable patterns, no read-proxy fallbacks, no bus-joining crash risk (§2.3's mis-routed-command invariant never applies to mongosh). The quoted-literal conventions (§2.3.5) remain relevant only for reading LEGACY companion atoms in the one-time sweep (§4.5).

### 4.3 Transactionality and partial-write semantics

- Fact atoms + their custom attributes go out in **one `add_atoms` batch**; `add_atoms` is fire-and-forget (`write_client.py:20-27`), so "together" means one submission. Partial application is caught by mandatory read-back of the fact's links (`:253-256`, companion branch deleted); the agent sees `BRIDGE-PERSIST-WRITE-FAILED: written but read-back verification missing handles: ...` and can retry — handles are deterministic, so a retry is idempotent.
- **Attribute persistence is best-effort** (`write_client.py:111-117` — "the pinned server persists custom_attributes on link documents; the companion was the guaranteed queryable record either way"). With the companion gone (D2), there is NO write-time verification that the attributes landed; a dropped attribute surfaces only at reconstruction (case FAIL). This is the honest cost of custom-attribute-primary; mitigations specified: Phase-0 probe of attribute-overwrite/persistence semantics (VERIFY, do not assume), optional post-write mongo attribute canary, and the reconstruction gate as the deterministic detector.
- **Gate ordering preserved:** the ledger commit must exist and verify BEFORE any DAS write (today's ordering `app.py:56-62` carries over) — DAS can never carry a `provenance_git_commit` that is not a real ledger commit.
- **Races:** `record()`/`verify_commit()` remain flock-serialized (`provenance_store.py:141-199,226-278` precedent); two concurrent first-writes of the same source serialize and the second dedups to the original commit. Commits are append-only; no TOCTOU. The plugin's per-process `ref → (sha, commit)` cache clears on agent restart (per-case restarts, `run_benchmark.py:720-722`), and dedup absorbs the re-POST — note the attestation interplay: a deduped `/v1/source` POST is still a real 2xx POST from the agent IP, so the `source_count ≥ 1` attestation holds whenever ≥1 provenance write happened in-window with a cold cache (documented in the spec).
- **Residual asymmetry from v2 is gone:** the companion's `ts:` timestamp made its handle unstable across re-writes; with no companion, re-writing the same fact from the same source is now a byte-identical idempotent operation (same handle, same attrs).

### 4.4 Local file paths as source refs — the honest split

- The agent container's filesystem ≠ host's; background files live in the `omega-curiosity-memory` volume at `/PeTTa/repos/Omega/memory/benchmark/background/`. The facade sees only the ledger bind-mount — **a local-path ref can only be resolved agent-side** (the plugin reads it; the facade cannot), reinforcing the plugin-resolves design (§3.1). Under v4 the facade never needs a path-form store key: the ref is an **opaque ledger string** (shape-checked: ≤480 chars, no whitespace, http(s) scheme or absolute path) — the old store's `_validate_url` http(s)-only restriction (`provenance_store.py:354-367`) is replaced by a ref-shape check.
- **Security — `dasWriteSourceRoots` (optional config key, allowed path prefixes; default unset = path refs disabled):** archiving arbitrary agent-readable container files into a host-side operator-trusted evidence store is an exfiltration/poisoning channel. Under v4 the exposure is metadata-only (`(path, sha)` lines, no content), but the names themselves can carry sensitive path information — the roots gate stays. The benchmark sets it to the benchmark background dir if path refs are exercised; **default D5: the benchmark cites URL refs** from `urls.txt` (`facts.py:12-18`, `run_benchmark.py:733`) — the harness byte-hash check then maps entries to background files by URL → filename (the `url.rsplit("/", 1)[-1]` convention, `run_benchmark.py:1028`). Path refs remain a general-skill capability behind the roots gate.
- Facade trust posture: `/v1/source` accepts any shape-valid `(ref, sha256)` from the private network — same posture as today's `/v1/archive` (which accepted arbitrary CONTENT; strictly larger exposure than v4). The plugin is the only intended caller; roots enforcement lives plugin-side.

### 4.5 Cleanup: net re-scoping + the one-time companion sweep (pre-existing leak, now fixable)

- **N1** (`run_benchmark.py:533-542`): regexes `custom_attributes.provenance_url` — must match `provenance_ref` for new writes **and keep `provenance_url`** for pre-migration residue (old atoms stay in DAS until cleaned; both fields can appear across runs).
- **N2** (`:544-575`, `metta_expression` literals incl. `BenchmarkPreflight`) — unchanged; still catches suffix-less smoke facts (D3 keeps the smoke suffix-less).
- **N3 (NEW, one-time sweep):** WriteProvenance companion atoms carry **no custom_attributes** and escape both nets — every benchmark run to date has leaked its companion links into DAS permanently (verified on the live wr3n artifact: `cleanup-das.json` `discovered_expressions` contains only fact expressions, `remaining_count: 0` — the nets cannot see companions). New writes no longer create companions (D2), but past runs' companions are still in DAS and would pollute reconstruction lookups. **Sweep scoping is load-bearing:** WriteProvenance companions are NOT benchmark-only — the live research agent's own provenance writes create them too (`docs/status.md:239` records a live coincentral.com companion), and campaign imports create `CampaignProvenance` links (`import_wrapper.py:249-256`). The sweep must therefore delete ONLY companions whose `"fact:<h>"` literal names a handle h belonging to a **cleaned benchmark fact** (handles derived client-side from the N1/N2-discovered expressions via `parse_fact`), with the leading-symbol check (`WriteProvenance`) as defense-in-depth — NEVER all WriteProvenance links, and NEVER CampaignProvenance links. Campaign companions are explicitly untouched (directive).
- The residue invariant extends: `remaining companions == 0` after cleanup (phase-check addition, `run_benchmark.py:658-679`).

### 4.6 The ledger repo: growth, quota, determinism

The ledger grows by one line + one commit per unique `(ref, sha256)` — bytes instead of the old 2 MiB-per-source blobs; re-runs dedup to the original commit, so **shas are stable across runs** (good for determinism and re-grading). Cleanup-das performs no git operations (evidence must survive) — correct, unchanged (`run_benchmark.py:612-679`). Consequences: (a) first-write-during-case semantics key on **write receipts**, never on ledger novelty (touchpoint 1); (b) a quota preflight check (ledger line/commit ceiling) is a cheap guard, specified as optional in the spec.

### 4.7 Config-driven constraint — confirmed within bounds

The skill grammar lives entirely in this repo's runtime-mounted artifacts: `deploy/omega/plugins/das-write/das-write.metta` (skill clause + description) + `das_write_bridge.py`, wired by `deploy/omega/plugins.yaml.overlay`, mounted `:ro` by `start.sh`. Changing the grammar, removing the `archive-source` clause (`das-write.metta:35-36`, decision D7) and rewriting the skill description touch **only bridge-repo files** — no upstream Omega/DAS source. The plugin's double gate (`is_enabled()`, `das_write_bridge.py:107-117`) means a not-yet-upgraded container keeps v2 behavior until redeployed. **No new Omega config keys strictly required**; the only optional key is `dasWriteSourceRoots` (§4.4). Preflight gains a grammar-version check (touchpoint 6).

### 4.8 Backward compatibility & migration

- **v2 (`"url" "git:<sha>"`): REMOVED** — after the ledger migration its citation gate fails by construction (§4.1); the plugin rejects the `git:` token with an actionable message pointing at the v3 form. Rollout note: redeploy the plugin in the same window as the repo migration (the spec sequences this).
- **v1 (suffix-less): stays valid** (D3 default permissive) — preflight smoke (`run_benchmark.py:367-370`), canaries, and dormant campaign prompts (`deploy/omega/prompts/research-continuation-20261020.txt`, which references the `BRIDGE-PERSIST` vocabulary) keep working unchanged.
- **Old v2-written atoms** (5-arity WriteProvenance, `provenance_url` attrs, old-repo commit shas): remain readable — reconstruction accepts `--legacy-repo` (informational fallback for pre-migration shas); old benchmark companions are swept once (§4.5); campaign corpus untouched.
- **`archive-source` skill: REMOVED** (D7 default) — subsumed by the write skill; the standalone clause (`das-write.metta:35-36`), `archive_source()` (`das_write_bridge.py:443-540`), and the skill README/description must be rewritten in the same phase.

### 4.9 Ledger verification chain vs the old chain — what the grader gains

Old chain per citation (`provenance_check.py:70-147`): commit → exactly one `sources/` blob → `index.jsonl` readable at commit → entry-for-blob → blob readable → sha256(blob) == entry → url match. New chain: commit → changed-paths == `[SOURCE-LEDGER.json]` → exactly one added line → added entry parses → `(ref, sha256)` == atom attrs → optional file byte-hash. Fewer git calls, no subject parsing, no blob I/O — and the matched fields come from the **atom's own attributes** (not from an agent-typed SOURCES line), closing the transcription failure class at the evidence level, not the discipline level. `provenance_check.py` survives as the LEGACY resolver (old-run re-grades + `--legacy-repo` fallback).

### 4.10 Pin/ledger interaction

Orthogonal, load-bearing, and SIMPLER: the ledger machinery (`agent_prompt_template.md:28-38`, pin plugin) survives unchanged in shape; step 1's ledger entries shrink (no archive lane, no sha pins — §3.5); the record line `expr <expression> top=<handle>` is the cross-cycle carrier for the HANDLES line (receipts do not survive wake cycles, §2.3.4 — the record file does).

---

## 5. Input specification — the extended write skill (v3 grammar)

### 5.1 Grammar

```metta
(add-atom &persistent <balanced-expression> [v3-suffix])

v3-suffix :=  SOURCEREF [STV]
SOURCEREF :=  "<http(s)-url>"               (≤ 480 chars, no whitespace)
            |  "<absolute-container-path>"  (≤ 480 chars, no whitespace;
                                             only when dasWriteSourceRoots is
                                             configured and the path is inside it)
STV := (stv <strength> <confidence>)        (both floats in [0,1])

Removed at v3 rollout (migration-sequenced):
  v2: (add-atom &persistent <expr> "<url>" "git:<40hex>" [(stv s c)])   — INVALID;
      the plugin rejects the "git:" token: pass the source reference instead.
Kept (decision D3, default permissive):
  v1: (add-atom &persistent <expr>)          — suffix-less write; unprovenanced;
      the benchmark gate (not the grammar) enforces refs on graded facts.
```

A v3 suffix's first quoted token starting with `git:` is an error (`archiving is automatic — give the source reference, not a commit`). No fingerprint token exists in the grammar (the plugin computes the sha256 itself).

### 5.2 Examples

```
(metta "(add-atom &persistent (Inheritance (Concept \"room\") (Concept \"enclosed-space\")) \"https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/main/tests/reasoning-windowless-room/background/spatial-knowledge.md\" (stv 0.9 0.8))")

(metta "(add-atom &persistent (Evaluation (Predicate \"has-part\") (Concept \"room\") (Concept \"wall\")) \"https://…/spatial-knowledge.md\")")

(metta "(add-atom &persistent (Inheritance (Concept \"local-corpus\") (Concept \"source\")) \"/PeTTa/repos/Omega/memory/benchmark/background/perspective.md\")")
```

### 5.3 Validation rules (plugin-side, before any HTTP call)

| Rule | Error status (prefix `BRIDGE-PERSIST-WRITE-FAILED:`) |
|---|---|
| expression balanced, ≤ 2048 chars | `expected one balanced expression after &persistent` / `expression exceeds 2048 characters` (existing) |
| source ref: http(s) URL ≤ 480 chars, no whitespace; or absolute path ≤ 480 chars, no whitespace, within configured roots | `source ref must be an http(s) URL or an allowed absolute path (≤480 chars, no whitespace)` / `source path outside the configured roots (dasWriteSourceRoots)` |
| `git:` token in the suffix | `git citations are no longer accepted — pass the source reference; archiving is automatic` |
| stv: 2 floats in [0,1] | existing v2 messages |
| unknown trailing content | `unexpected content after the source reference` |

Facade-side: provenance `{ref, git_commit, blob_sha256}` shape checks (replacing `write_client.py:70-87`); citation gate = `LedgerStore.verify_commit` (commit exists + its diff adds exactly the one matching ledger entry). New facade error strings are enumerated in the spec §2.

### 5.4 Skill-internal flow (v3)

1. Resolve the ref: URL → bounded fetch (2 MB cap, text content types only, 20 s — the `archive_source` fetch internals, `das_write_bridge.py:461-489`, move into the write path); path → read the file (same size cap; only within configured roots).
2. Compute `sha256` of the fetched/read content (plugin-side).
3. Per-process cache lookup `ref → (sha256, commit)`; on miss: POST `/v1/source` `{ref, sha256}` → `{commit, deduped, entry_date}`.
4. POST `/v1/write` `{metta, verify:true, provenance:{ref, git_commit: commit, blob_sha256: sha}}` → facade gate → one `add_atoms` batch (fact atoms + custom attributes) → read-back → 200 with `top_handle`.
5. Receipt: `BRIDGE-PERSIST-OK: verified=<n> top=<top-handle> [stv=(s,c)]`.

### 5.5 Status strings (returned to the agent)

- `BRIDGE-PERSIST-OK: verified=<n> top=<top-handle> [stv=(s,c)]` — the `verified=<n>` leading segment is preserved (the prompt's "success is ONLY `BRIDGE-PERSIST-OK: verified=<n>`" contract, `agent_prompt_template.md:44`, and `extract_persist_receipts`'s substring match, `history_parse.py:119-121`, keep working); `handles=<first3>` is retired in favor of `top=`.
- `BRIDGE-PERSIST-WRITE-FAILED: <reason>` — reasons include the existing set plus: `source fetch failed (<…>)`, `source unreadable at <path>`, `source path outside the configured roots (dasWriteSourceRoots)`, `unsupported content type <…> (text only)`, `source content empty`, `ledger append failed (<facade error>)`, `git citations are no longer accepted — pass the source reference`.
- `ARCHIVE-OK` / `ARCHIVE-FAILED` retire with the `archive-source` skill (D7).

Sizes: expression ≤ 2048; ref ≤ 480; total skill string comfortably < 3 KiB; facade `/v1/write` body unchanged (≤ 16 KiB, `app.py:14`); `/v1/source` body is a few hundred bytes.

---

## 6. Provenance data schema (v4: custom attributes + ledger — no new atoms)

### 6.1 Fact atom's TOP-link `custom_attributes`

```
custom_attributes = {
  "metta_expression":       "<the written expression>",          (unchanged)
  "provenance_ref":         "<http(s) url | absolute container path>",
  "provenance_git_commit":  "git:<40hex>",                       (the LEDGER commit)
  "provenance_blob_sha256": "sha256:<64hex>",                     (plugin-computed)
  ["stv_strength": <f>, "stv_confidence": <f>]
}
```

All on the fact's top link only (the decoration point, `write_client.py:108-128`); handles remain deterministic — decoration never changes identity or dedup (`:60-63`). No companion atom, no SourceRecord, no DerivedFrom (§3.2). Absence of the three `provenance_*` attributes on a stored benchmark fact = missing source (reconstruction condition `NO_PROVENANCE_ATTRS`), except the documented legacy carve-out (`--legacy-repo`).

### 6.2 Ledger entry (SOURCE-LEDGER.json element)

```json
{"ref": "<http(s) url | absolute container path>", "sha256": "<64 lowercase hex>", "entry_date": "<YYYY-MM-DDTHH:MM:SSZ>"}
```

Exactly three fields (directive); serialization per §3.3 (leading-comma, one element per line, `+1`-line appends); one commit per new entry; dedup on `(ref, sha256)` returns the original commit.

### 6.3 Example write (v4)

Input: `(add-atom &persistent (Inheritance (Concept "room") (Concept "enclosed-space")) "https://…/spatial-knowledge.md" (stv 0.9 0.8))`
Facade batch: the fact's atoms only (nodes `Inheritance`, `Concept`, `"room"`, `"enclosed-space"`, inner + top Expression links); top link decorated with §6.1's attributes; read-back probes each fact link in variable-leading form. Response: `{handles, verified, missing, top_handle}`. Receipt: `BRIDGE-PERSIST-OK: verified=5 top=<top-handle> stv=(0.9,0.8)`.

---

## 7. Reconstruction script interface (spec)

```
reconstruct_sources.py (--trace-file <path> | --trace "<s-exprs;semicolon-separated>")
                       --ledger-repo <dir>
                       [--facts "<expr;…>"] [--handles "<h1> <h2> …>"]
                       [--mongo-container <name>] [--case <id>]
                       [--json <out-path>] [--source-paths-out <path>]
                       [--background-dir <dir>] [--legacy-repo <dir>]
```

- **Inputs:** the reasoning trace (the `REASONING:` line shape; the query clause and `exec` outputs tolerated and classified), the ledger repo, mongo (docker exec mongosh). `--facts`/`--handles` supply the FACTS-line expressions and the claimed HANDLES for the cross-check.
- **Pipeline:** per directive §3.4's handle chain. Classification + exemptions + per-predicate aggregation per §3.4.
- **Outputs (JSON):** `per_expression: [{expr, top_handle, stored, sources: [{commit, ref, sha256, entry_date, resolved, conditions}], conditions}]`, `per_predicate: {<leading-symbol>: {expressions, sources}}`, `handles_check: {claimed, derived, conditions}`, `missing: [...]`, `conditions: [...]`, `source_paths: [...]`; human summary on stdout.
- **Exit codes:** `0` all used stored facts have ≥1 fully-resolved source; `2` some used stored fact's source is missing/unresolvable (the benchmark maps this to the case FAIL); `1` harness/environment error (mongo unreachable, ledger repo unreadable, trace unparseable). The H_* cross-check conditions ride in the JSON (blocking via the gate, D4) — the exit code is the coarse source-verdict, per the directive's wording.
- **`--source-paths-out`:** writes the list of local source files used (enables the harness byte-hash check without re-deriving filenames).
- **Determinism:** pure function of (trace, DAS content, ledger repo state); no LLM, no agent cooperation, no pattern-engine queries.
- **Benchmark wiring:** `grade_case` invokes the script on the case's REASONING + FACTS/HANDLES lines, maps `conditions` to the P-gate/H-gate condition codes, and feeds resolved `(ref, sha256)` pairs into the byte-compare lane.

---

## 8. Implementation plan — superseded

The phased plan (live probes → facade → plugin → host migration runbook → reconstruction script → benchmark rewiring → tests) now lives in full detail in **`docs/issue-2-implementation-spec.md`** (per-phase files, function-level behavior, acceptance criteria, test strategy, all string/gate/exit-code tables). Summary of the phase order and its rationale:

- **Phase 0 — probes:** mongo handle-field re-verification (live canary write → `db.links.find({_id})`) and attribute-overwrite semantics on re-write (VERIFY, do not assume).
- **Phase 1 — facade:** `LedgerStore` (rewrite of `provenance_store.py`), `/v1/source`, `/v1/write` v4 payload + ledger citation gate + `top_handle` response, attribute changes in `write_client.py`.
- **Phase 2 — plugin:** v3 grammar + ref resolution + sha256 + cache + `top=` receipt; `archive-source` removal (D7).
- **Phase 3 — host migration runbook:** operator/SSH steps (backup + fresh repo) — NOT automated.
- **Phase 4 — reconstruction script:** `deploy/das/write-bridge/tools/reconstruct_sources.py` + its own README.
- **Phase 5 — benchmark rewiring:** prompt slim, HANDLES line + gate conditions, E_NO_INGEST/P-gate/attestation/cleanup updates, `GATES-REFERENCE.md` + `test-spec.md` history entries.
- **Phase 6 — tests per component:** write-bridge pytest suite; windowless-room unit suite incl. new modules (ledger chain, reconstruction script, HANDLES gate, slim prompt); enumerated changes to the existing pinned tests.

Order matters: facade first (the new gate + endpoint must exist before the plugin speaks v3), plugin before benchmark (the harness consumes the new receipts), migration runbook before the first live run (the gate reads the new repo), script before benchmark rewiring (the P-gate calls it).

---

## 9. Decision points (decision-gated — implementation must NOT start before Balazs resolves each or accepts the default)

| # | Decision | Options | Recommended default |
|---|---|---|---|
| **D1** | Ledger-only vs ledger+content store | (a) ledger-only (3 fields, single file — as directed); (b) + content blobs | **(a) ledger-only** per directive. Stated trade-off (§3.3): source content is no longer archived anywhere — verification = sha256 vs harness-known files; general campaigns lose byte-level evidence. Benchmark unaffected (harness holds background files). Content-blob extension noted as a possible later addition. |
| **D2** | WriteProvenance companion for new writes | (a) drop (custom-attribute-primary); (b) keep writing companions | **(a) drop** — consistent with "we don't need a dedicated Atom"; one-time N3 sweep of OLD benchmark-fact companions (§4.5, handle-scoped); campaign companions untouched. |
| **D3** | Suffix-less (v1) writes | (a) strict-reject (forces provenance discipline; preflight smoke + canaries must carry a ref); (b) permissive-accept (unprovenanced write succeeds; the gate enforces refs on graded facts) | **(b) permissive** — preflight smoke (`run_benchmark.py:367-370`), canaries, and dormant campaign prompts keep working unchanged; enforcement lives in the gate. |
| **D4** | HANDLES-line strictness | (a) required + blocking on missing/mismatch (fabrication tripwire); (b) informational (P-gate works via re-derived handles anyway) | **(a) required + blocking** — cheap for the agent (copy from receipt; the `expr … top=<h>` record line carries it across wake cycles) and preserves the gate's agent-evidence philosophy. |
| **D5** | Benchmark source-ref form | (a) URL refs (`urls.txt` exists, `facts.SOURCE_URLS` maps file→URL for byte-compare); (b) container path refs | **(a) URL refs** for the benchmark; path refs remain a general-skill capability behind `dasWriteSourceRoots`. |
| **D6** | Old-repo migration mechanics | (a) git bundle + tar backup to a sibling path, fresh init at the SAME path (compose/env unchanged), `SOURCE-LEDGER.json` initial commit = empty array, `--legacy-repo` fallback; (b) in-place conversion script | **(a) bundle + fresh init** — operator-run (SSH runbook), no in-place mutation of evidence; compose/env unchanged (`compose.write-bridge.yaml:67,71`). |
| **D7** | Standalone `archive-source` skill clause | (a) remove (subsumed by the write skill); (b) keep, rewired to the ledger | **(a) remove** — smaller agent surface (the agent no longer knows archiving exists); requires the `das-write.metta` clause removal (`:35-36`) + README/skill-description rewrite. |

---

## 10. Summary of the most important findings (v4)

1. **The first case would still fail without grading changes:** `E_NO_INGEST` requires an in-window `ARCHIVE-OK` receipt (`grading.py:676-692`) — transparency removes agent archive calls entirely. Eight enumerated harness touchpoints (§3.5 table) must change in the same iteration, now including the new HANDLES gate and the `/v1/archive → /v1/source` attestation rewire (`run_benchmark.py:328-331`).
2. **The E-gate's FACTS grounding survives** the removal of `source` record lines AND the new `top=` annotation — `parse_facts_index` never read them, and the balanced-prefix parser tolerates trailing annotations (`grading.py:144-196`). The `expr` lines must stay.
3. **Custom-attribute-primary is only viable because handles are deterministic and mongo is keyed by `_id` = handle** (`iter16_groundtruth.js:8-12`): the whole evaluator join is client-side handle re-derivation + one mongosh lookup per handle. The pattern engine is nowhere in the provenance path — every engine-quirk risk from the v3 design evaporates.
4. **The write-time verification guarantee weakens honestly:** with the companion dropped, `verified=<n>` covers only the fact's own links, and custom-attribute persistence (best-effort, `write_client.py:111-117`) cannot be read-back through the pattern engine — a dropped attribute surfaces at reconstruction, not as a write failure. Phase-0 probes + optional post-write canary + the gate as detector.
5. **The companion cleanup leak is real and the sweep must be scoped:** companions escape both cleanup nets today (live wr3n evidence), and WriteProvenance atoms exist beyond benchmark runs (live research companions, `docs/status.md:239`) — N3 must key on cleaned benchmark fact handles, never on the leading symbol alone.
6. **The v2 grammar must be removed, not tolerated:** after the ledger migration its citation gate fails by construction (v2 commits are archive-subject commits, absent from the ledger) — plugin-side rejection with an actionable message, deployment sequenced with the repo migration.
7. **The fake-sha failure class is structurally eliminated:** the agent never types a fingerprint or a git sha anywhere in the v4 pipeline; the ledger sha is plugin-computed over content the plugin itself fetched/read.
8. **Source content is no longer archived (D1)** — the deliberate directive trade-off; the benchmark's byte-level guarantee moves to the harness-side `sha256(background file) == entry.sha256` check, which the reconstruction script exposes via `--source-paths-out`.
