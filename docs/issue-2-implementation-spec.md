# Issue #2 — Transparent Provenance: Implementation Specification (v4)

**Work order for coder-opencode — branch `issue-2-transparent-provenance` (NEXT iteration). State (2026-10-27 22:37 UTC): decision gate CLEARED — implementation authorized; docs only so far (the two issue-2 documents are the only existing artifacts; nothing committed yet). Next step: cut the branch + SDD bootstrap (`specify init`) per the SDD note and §14.**
Repo: `ktfh-claw/low-cost-omega-setup`. Companion analysis: `docs/issue-2-provenance-analysis.md` (v4 amendment, 2026-10-27). This document is self-contained.

> **DECISION GATE — CLEARED (Balazs, 2026-10-27 22:37 UTC):** decisions D1–D7 (§10) are RESOLVED — approved as defaulted ("For the D1-7 decision, I approve all the listed defaults."), and the six open inconsistency points are resolved (recorded in §11, "Resolved inconsistencies"). **Implementation is authorized.** Every phase below states which decisions it depends on.

**Design in one paragraph (Balazs directive 2026-10-27 22:15 UTC):** the proposed `SourceRecord` atom and every dedicated fact→source link atom are dropped — provenance is **custom-attribute-primary** (fact top-link `custom_attributes`), the agent is **not aware of provenance tracking**, the write-skill grammar is **v3: `(add-atom &persistent <expr> "<http(s)-url | abs-container-path>" [(stv s c)])`** (ref mandatory in the v3 shape, stv optional, NO agent fingerprint, NO git sha), the **das-write plugin** resolves the ref (fetch/read), computes **sha256 of the source content itself**, and ledger-appends via the facade; the offline provenance repo is replaced by a **fresh single-file `SOURCE-LEDGER.json` git repo** (one array element per line; each new entry = exactly one commit; the commit hash is the provenance anchor; dedup on `(ref, sha256)` returns the original commit); the answers block gains a **`HANDLES:` line** (cross-checked against deterministically re-derived handles); a **standalone reconstruction script** (trace in → per-expression/per-predicate source lists out; mongo-direct) is the provenance gate.

> **SDD EXECUTION NOTE (addendum 2026-10-27 22:20 UTC):** implementation will be executed **spec-driven** — specify/spec-kit 1.2.0 (installed at `~/.local/bin/specify`; this repo is not yet initialized). The pipeline (constitution → spec → plan → tasks → implement → converge) is bootstrapped on the new branch via `specify init`, using THIS document as source material; SDD artifacts live under `.specify/` (or the specify CLI's conventional directory) on the branch. **When SDD artifacts and this document disagree, this document remains the normative reference unless Balazs says otherwise.**

---

## 0. Hard constraints (unchanged)

- NO modification to upstream DAS or Omega source. Everything config-driven: the `das-write` plugin (`deploy/omega/plugins/das-write/`, `:ro`-mounted, wired via `deploy/omega/plugins.yaml.overlay`) intercepts `&persistent`; the write-bridge facade is a compose service (`deploy/das/write-bridge/`).
- `add_atoms`/`delete_atoms` are fire-and-forget; handles are deterministic (type+targets hash, `deploy/das/write-bridge/write_client.py:60-63`); `custom_attributes` never change identity/dedup.
- Two disjoint service buses (atomdb vs pattern query); a mis-routed atomdb command crashes the query engine — **the reconstruction script never joins a bus** (mongo-direct).
- The plugin runs inside the agent container and is the ONLY component that fetches URLs / reads container paths. The facade stays egress-free with its 16 KiB write body cap (`app.py:14`).
- History channel collapses tool results to `$_` — record files + the query-side docker-log attestation lane remain load-bearing (the ingest-attestation lane is dropped — resolution 6, §11).

---

## 1. Component map (v4 data flow)

```
agent (unaware of provenance)
  └─ (metta "(add-atom &persistent <expr> "<ref>" [(stv …)])")
       └─ PLUGIN das_write_bridge.py (agent container)
            1. parse v3 suffix (ref [+ stv]); reject git: tokens
            2. resolve ref: URL → bounded fetch (≤2 MB, text, ≤20 s) | path → read (within dasWriteSourceRoots)
            3. sha256 := sha256(content)                       # plugin-computed
            4. cache[ref] or POST /v1/source {ref, sha256} → {commit, deduped, entry_date}
            5. POST /v1/write {metta, verify:true, provenance:{ref, git_commit, blob_sha256}}
                 └─ FACADE app.py (write-bridge container)
                      a. LedgerStore.verify_commit(commit, ref, sha256)   # citation gate, BEFORE any DAS write
                      b. runner.write(): parse_fact → decorate TOP-link custom_attributes
                         (metta_expression, provenance_ref, provenance_git_commit,
                          provenance_blob_sha256 [, stv_*]) → ONE add_atoms batch
                         → read-back of the fact's links → 200 {handles, verified, missing, top_handle}
       └─ receipt: "BRIDGE-PERSIST-OK: verified=<n> top=<top-handle> [stv=(s,c)]"

LEDGER REPO (host /home/ubuntu/omega-provenance, container /var/lib/omega-provenance, env WRITE_PROVENANCE_REPO — compose.write-bridge.yaml:67,71)
  SOURCE-LEDGER.json — JSON array, one element per line:
    {"ref": "<url|path>", "sha256": "<64hex>", "entry_date": "<ISO-8601 UTC>"}
  one commit per new entry (dedup returns the original commit)

HARNESS (grade-case)
  reconstruct_sources.py (mongo-direct + ledger git)
    trace expr → parse_fact → top_handle → claimed HANDLES cross-check
    → db.links.find({_id: handle}) → custom_attributes.provenance_git_commit
    → ledger commit → diff adds exactly one entry line → (ref, sha256) match
    → [optional] sha256(background file) == entry.sha256
  → per-expression/per-predicate source lists; exit 0 / 2 / 1
```

---

## 2. Normative interface specifications

### 2.1 Write-skill grammar (v3) — full spec

```metta
(add-atom &persistent <balanced-expression> [v3-suffix])

v3-suffix :=  SOURCEREF [STV]
SOURCEREF :=  "<http(s)-url>"               (≤ 480 chars, no whitespace)
            |  "<absolute-container-path>"  (≤ 480 chars, no whitespace; enabled only
                                             when dasWriteSourceRoots is configured and
                                             the path resolves inside one of its roots)
STV := (stv <strength> <confidence>)        (both floats in [0,1])
```

- The 2048-char cap applies to the **expression only** (plugin `MAX_METTA_CHARS=2048`, `das_write_bridge.py:85`, enforced `:347`, `:356`; facade `WRITE_MAX_METTA_CHARS`, `app.py:24`). Suffix headroom: ref ≤ 480 + stv ≈ 20 — ample.
- **v2 shape REMOVED:** `(add-atom &persistent <expr> "<url>" "git:<40hex>" [...])` — after the ledger migration its citation gate cannot verify (v2 commits are `archive:`-subject commits, absent from the ledger repo). The plugin rejects any quoted `git:` token in the suffix with an actionable status (§2.5).
- **v1 shape (suffix-less) KEPT — decision D3, default permissive (RESOLVED, §10):** the write succeeds unprovenanced; the benchmark gate enforces refs on graded facts. Canaries and dormant campaign prompts keep working unchanged; the preflight smoke itself is upgraded to exercise the FULL v4 path (resolution 5 — Phase 5 item 7).
- Disambiguation: a quoted suffix token starting `http://` / `https://` or `/` → SOURCEREF; starting `git:` → error; anything else → error.

### 2.2 Ledger repo format — `SOURCE-LEDGER.json`

- A single file at the repo root; a JSON **array**; each element has **exactly three fields**: `ref` (http(s) URL or absolute container path), `sha256` (64 lowercase hex, of the source content — plugin-computed), `entry_date` (ISO-8601 UTC, `%Y-%m-%dT%H:%M:%SZ`).
- **Serialization (pinned — the unique valid-JSON form where each append is a pure +1-line diff): leading commas.** Line 1 = `[`; each element on its own line, the FIRST element line starting `{` and every subsequent element line starting `,{`; final line = `]`:

```json
[
{"ref": "https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/main/tests/reasoning-windowless-room/background/spatial-knowledge.md", "sha256": "9f2c1d0a…64hex", "entry_date": "2026-10-28T09:00:00Z"}
,{"ref": "https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/main/tests/reasoning-windowless-room/background/lighting.md", "sha256": "1ab3e57f…64hex", "entry_date": "2026-10-28T09:00:01Z"}
]
```

  An append inserts one line before `]` — **no existing line changes**; `git diff` per entry commit is exactly one added line; the file remains a valid JSON array (leading commas are legal inside arrays). The fresh-repo initial commit contains exactly:
  ```
  [
  ]
  ```
  (empty array). Rationale: the conventional trailing-comma-free array would make every append a 2-add/1-del diff (the previous last element line gains a comma); the leading-comma form satisfies the directive's "each append is exactly a +1-line diff" literally.
- **Owner resolution 3 (2026-10-27 22:37 UTC):** Balazs explicitly accepts the alternative too — "2add/1del diff, its fine, no prob with that". The leading-comma +1-line form stays PINNED as a simplicity choice (strictly simpler to verify: "commit diff adds exactly one entry line"), NOT a requirement.
- **One commit per new entry.** Commit subject: `ledger: <sha256[:12]> <ref[:96]>` — informational only; verification NEVER parses the subject (unlike the v2.1 gate, `provenance_store.py:241-258`).
- **Dedup:** `record(ref, sha256)` with `(ref, sha256)` already present returns the ORIGINAL entry's commit, `deduped: true`, no file change, no new commit. The original commit is re-found deterministically: `git log --reverse --format=%H -S"<exact entry line>" -- SOURCE-LEDGER.json` → first hit. Same ref, different content (drift across runs) = new entry + new commit (atoms carry both `provenance_ref` and `provenance_blob_sha256`, so per-atom resolution stays unambiguous).
- **Entry lookup by line number is FORBIDDEN as an identity** — the `(ref, sha256)` pair is the entry identity; the commit is the anchor.

### 2.3 Facade API changes

**NEW endpoint `POST /v1/source`** (ledger append; content NEVER crosses to the facade):

- Request: `{"ref": "<string>", "sha256": "<64 lowercase hex>"}` — body cap 16 KiB (`app.py:14`); unknown keys → 400.
- Validation errors (400, `{"error": …}`): `"ref must be a non-empty string of at most 480 characters"`, `"ref must not contain whitespace"`, `"ref must be an http(s) URL or an absolute path"`, `"sha256 must be 64 lowercase hex characters"`. Unconfigured store → 503 `{"error": "ledger requires the configured provenance repo (WRITE_PROVENANCE_REPO unset)"}` (mirrors `app.py:52`).
- Behavior: flock-serialized (`provenance_store.py:141-199` pattern) → dedup scan → append one line before `]` → `git add SOURCE-LEDGER.json` → commit → 200 `{"commit": "<40hex>", "deduped": false, "entry_date": "<ISO>"}`; dedup hit → 200 `{"commit": "<original>", "deduped": true, "entry_date": "<original>"}`.
- Trust note: the facade accepts any shape-valid `(ref, sha256)` from the private network (same trust posture as today's `/v1/archive`; strictly smaller exposure — metadata only, no content). `dasWriteSourceRoots` enforcement is plugin-side; the facade validates shape only. `MAX_ARCHIVE_BODY_BYTES` (8 MiB, `app.py:18`) and the `/v1/archive` route (`app.py:82-99`, `:105-108`) are DELETED.

**`POST /v1/write` changes** (`app.py:30-80`):

- `provenance` payload keys become exactly `{"ref", "git_commit", "blob_sha256"}` (replacing `{url, git_commit, fetched_at}`, `write_client.py:70-87`).
- **Citation gate (before any DAS write — ordering preserved from `app.py:50-60`):** `LedgerStore.verify_commit(git_commit, ref, sha256)` must hold: commit exists in the ledger repo → its diff touches only `SOURCE-LEDGER.json` → adds exactly one entry-shaped line → the entry's `(ref, sha256)` equals the payload's. Failure → 400 with an actionable, retryable message (§2.5).
- Response 200 gains `"top_handle": "<fact top-link handle>"` (alongside `handles`, `verified`, `missing`; `provenance_link` retires with the companion). `runner.write()` must thread `fact.top_handle` into its result.

**`LedgerStore`** (rewrite of `deploy/das/write-bridge/provenance_store.py`; keep the module name, the `ArchiveError` exception name for import continuity with `app.py:11`, and the flock/git plumbing conventions `provenance_store.py:46-47,141-199,322-351`):

- `ensure_repo()` — create repo if missing; write `[\n]` SOURCE-LEDGER.json if missing; initial commit `ledger: init` if the file was just created. (Called at facade boot, `app.py:26-28` pattern.)
- `record(ref, sha256)` → `{commit, deduped, entry_date}` — per §2.3.
- `verify_commit(git_commit, ref, sha256)` → `{commit, ref, sha256, entry_date}` — the gate chain; raises `ArchiveError` with actionable messages (§2.5).
- Retired methods: `archive()`, `lookup()`, subject parsing (`parse_archive_subject`, `:60-76`), `_validate_url` (`:354-367`) — replaced by `_validate_ref` (http(s) URL or absolute path, ≤480, no whitespace).

### 2.4 Reconstruction script CLI (exact, per directive)

```
python3 reconstruct_sources.py \
  (--trace-file <path> | --trace "<s-exprs;semicolon-separated>") \
  --ledger-repo <dir> \
  [--facts "<expr;expr;…>"]            # FACTS-line expressions (aligned order)
  [--handles "<h1> <h2> …>"]           # claimed HANDLES (aligned with --facts)
  [--mongo-container <name>]           # default: the benchmark mongo container
  [--case <id>] [--json <out-path>] \
  [--source-paths-out <path>]          # list of source path files used
  [--background-dir <dir>]              # enables the optional byte-hash check
  [--legacy-repo <dir>]                 # pre-migration repo fallback (OPTIONAL-informational only — never blocking, never in the default grade path; resolution 4)
```

- **Input:** trace in (the `REASONING:` line shape; query clause + `exec` outputs tolerated and classified). **Output:** per-expression and per-predicate source lists (JSON via `--json`; human summary on stdout). **Exit codes:** `0` = all sources resolve in the ledger repo; `2` = some used stored fact's source is missing/unresolvable (case FAIL); `1` = harness error (mongo unreachable, ledger unreadable, trace unparseable). `--source-paths-out` writes the source file paths used. The H_* cross-check conditions ride in the JSON (mapped to blocking gate conditions by `grading.py`, D4); the exit code is the coarse source-verdict per the directive's wording.
- **Deterministic handle chain (the spine):** trace expr → `metta_to_atoms.parse_fact` → `top_handle` → claimed-HANDLES cross-check → `db.links.find({_id: <handle>})` (mongo handle field = `_id`, verified `deploy/das/write-bridge/tests/iter16_groundtruth.js:8-12`; re-verified live in Phase 0) → `custom_attributes.provenance_git_commit` → git commit in ledger repo → diff adds exactly one ledger line → entry `(ref, sha256, entry_date)` → optional `sha256(known source file) == entry.sha256`.
- **Classification rules (documented in the script's README):** (a) *stored facts* = ground expressions whose re-derived handle hits `db.links` — each MUST carry ≥1 resolvable source; a stored link without provenance attributes = condition `NO_PROVENANCE_ATTRS` (legacy carve-out: pre-migration atoms resolve via `--legacy-repo`, informational); (b) *query clause* (variable-bearing first step) — exempt; (c) *interpreter-derived outputs* (`exec` lines / `call => output` steps) — exempt; a derivation's sources = its premises' sources (`grading._split_derivation_atoms` convention, `grading.py:447-460`). **Per-predicate aggregation** = group by leading symbol of stored steps.
- **Output JSON:** `{"per_expression": [{"expr", "top_handle", "stored", "sources": [{"commit", "ref", "sha256", "entry_date", "resolved", "conditions"}], "conditions"}], "per_predicate": {"<symbol>": {"expressions", "sources"}}, "handles_check": {"claimed", "derived", "conditions"}, "missing", "conditions", "source_paths"}`.
- Location: `deploy/das/write-bridge/tools/reconstruct_sources.py` + `deploy/das/write-bridge/tools/README.md` (standalone usage doc — invocable independently of the e2e test). Imports `metta_to_atoms` from the bridge dir.

### 2.5 Status strings, error strings (complete lists)

**Plugin statuses (returned to the agent; never raises):**
- `BRIDGE-PERSIST-OK: verified=<n> top=<top-handle> [stv=(s,c)]` — the `verified=<n>` leading segment is preserved (prompt contract `agent_prompt_template.md:44`; `extract_persist_receipts` substring match `history_parse.py:119-121`); `handles=<first3>` segment RETIRED.
- `BRIDGE-PERSIST-WRITE-FAILED: <reason>` — existing reasons plus the new ones:
  - `source fetch failed (<reason>)` / `fetch timed out` (URL fetch, ≤20 s, ≤2 MB, text-only — reused from `das_write_bridge.py:461-489`)
  - `source unreadable at <path>` / `source path outside the configured roots (dasWriteSourceRoots)`
  - `unsupported content type <ct> (text only)` / `source content empty` / `source exceeds the 2,000,000 character limit`
  - `ledger append failed (<facade error>)` (non-2xx or malformed `/v1/source` response)
  - `git citations are no longer accepted — pass the source reference; archiving is automatic` (v2 token in suffix)
  - `source ref must be an http(s) URL or an allowed absolute path (≤480 chars, no whitespace)` / `unexpected content after the source reference`
  - all existing transport/parse reasons (`request timed out`, `HTTP <code>`, `invalid response from facade`, …)
- `ARCHIVE-OK` / `ARCHIVE-FAILED` / the `archive-source` skill: **RETIRED** (D7) — clause removed from `das-write.metta:35-36`, `archive_source()` deleted, README/skill-description rewritten.

**Facade errors (400/503 bodies, `{"error": …}`):**
- `/v1/source`: §2.3's validation strings; `503 ledger requires the configured provenance repo (WRITE_PROVENANCE_REPO unset)`.
- `/v1/write` gate failures (actionable, retryable — the v2.1 wording pattern `provenance_store.py:236-257`):
  - `provenance git_commit "<sha>" not found in the ledger — write the source first via the skill, then retry`
  - `provenance git_commit "<sha>" is not a ledger commit (touching only SOURCE-LEDGER.json)`
  - `provenance git_commit "<sha>" does not add the cited source entry — re-run the skill write, then retry`
  - `provenance must contain ref, git_commit and blob_sha256` (shape)

### 2.6 Gate condition codes (benchmark; changes and additions)

| Code | Blocking? | Trigger (v4) |
|---|---|---|
| `E_NO_INGEST` | blocking | FIRST case only, RECEIPTS-ONLY (resolution 6): blocking iff first case AND no in-window `BRIDGE-PERSIST-OK` receipt (`window_persist_receipts == 0`). Receipts ARE extractable from history windows (verified live, `extract_persist_receipts` `history_parse.py:119-121`); the ARCHIVE-OK half AND the facade-log attestation branch are dropped (was `grading.py:676-692`). |
| `E_INGEST_ATTESTED_VIA_FACADE_LOG` | RETIRED | dropped entirely (resolution 6) — log-census ingest attestation is gone; `E_NO_INGEST` is receipts-only. `collect_attestation`'s query lanes (`access_count`, `qe_pattern_match`) SURVIVE — they serve `Q_ATTESTED_VIA_ACCESS_LOG`, a DIFFERENT gate covering the known history-collapse defect for queries. |
| `P_MISSING` | blocking | knowledge case: reconstruction finds no used stored facts carrying any provenance attributes (nothing citable). Unsolvable exempt. |
| `P_UNRESOLVED:<expr12>:<COND>` | blocking | a used stored fact's source failed resolution; `COND` ∈ {`COMMIT_NOT_IN_REPO`, `COMMIT_UNREADABLE`, `COMMIT_NOT_A_LEDGER_COMMIT`, `COMMIT_TOUCHES_OTHER_FILES`, `COMMIT_ADDS_NOT_ONE_LINE`, `ENTRY_PARSE_FAILED`, `REF_SHA_MISMATCH`, `NO_PROVENANCE_ATTRS`}. (Old blob/index codes `COMMIT_MULTIPLE_SOURCE_BLOBS`, `INDEX_*`, `BLOB_*`, `URL_MISMATCH` retire with the old store; `provenance_check.py` keeps them as a STANDALONE UNWIRED tool — historical/legacy reference, no harness import — resolution 4.) |
| `P_SOURCE_SET_MISMATCH` | informational | sources attached to the case's facts ⊄ the case's background source set (semantic-misattribution visibility). |
| `H_MISSING` | blocking (D4) | knowledge case: no (or empty) `HANDLES:` line in the block. |
| `H_COUNT_MISMATCH` | blocking (D4) | HANDLES token count ≠ FACTS expression count. |
| `H_MISMATCH` | blocking (D4) | a claimed handle ≠ the deterministically re-derived `top_handle` of the aligned FACTS expression (fabrication tripwire; handles are re-derivable client-side — the agent's claim is a cross-check, not a lookup dependency). |
| `Q_*`, `A_*`, `E_NO_EXTRACTION`, `E_NO_FACTS`, `E_FACTS_NOT_IN_INDEX`, `E_LITERAL_NOT_EXTRACTED`, `E_INDEXED_NOT_PERSISTED`, `R_*` | unchanged | verified: none of these read SOURCES lines or ARCHIVE-OK receipts. |

**Design principle (Balazs, resolution 6, 2026-10-27 22:37 UTC):** "I care about the direct verification evidence of the MeTTa reasoning trace leading to the answer" — the R-gate's executed-trace evidence and the deterministic reconstruction chain are the load-bearing DIRECT evidence; log-census attestation crutches are not, and are retired accordingly.

**Exit codes (unchanged semantics):** harness `0` = gate PASS, `2` = gate FAIL (valid negative), `1` = harness error; reconstruction script `0`/`2`/`1` per §2.4.

### 2.7 Answers-block format (v4)

```
### CASE <id>
QUERY: <the exact metta pattern executed>
DAS_RETRIEVE_OK untrusted=true count=<n> …
FACTS: <expr;expr;… — verbatim copies of recorded `expr` lines>
HANDLES: <h1> <h2> … — aligned by order with the FACTS expressions, each copied from a receipt the agent holds: the write receipt (top=) or a das-retrieve results handle (addendum 2026-10-27; §8 item 10)>
REASONING: <question clause; fact steps; derivation steps with (stv …) outputs>
FINAL ANSWER (<id>): <answer>
```

`SOURCES:` line: REMOVED. Extraction-record lines: `source …` lines REMOVED; `expr <expression> top=<handle>` replaces `expr <expression> verified=<n>` (the handle copied verbatim from the receipt; carries the HANDLES line across wake cycles); `query`/`exec`/`trace` lines unchanged.

---

## 3. Phase 0 — live probes (de-risk; no repo behavior change)

**Purpose:** verify the two assumptions the whole design rests on. VERIFY — do not assume.

**P0a — mongo handle field name + attribute visibility.**
- Evidence already in repo: link/node documents keyed by `_id` = handle (`deploy/das/write-bridge/tests/iter16_groundtruth.js:8-12`); `custom_attributes` on link docs (`write_client.py:108-128`), invisible to pattern answers (`write_client.py:307-343`).
- Probe (live, SSH): write one canary fact via the bridge (`POST /v1/write` with a v4 provenance payload — may be done by hand-running the runner in the write-bridge container); then `docker exec <mongo> mongosh … --eval` with: `db.links.find({_id: "<top_handle>"})` → confirm the doc exists and shows `custom_attributes.provenance_git_commit/ref/blob_sha256`; one pattern query through the read-proxy for the same expression → confirm the answer carries handles only (no attributes).
- Deliverable: `deploy/das/write-bridge/tests/iter18_probe_mongo_attrs.py` + results note (pattern of `iter16_probe.py`, `iter16_groundtruth.js`).

**P0b — attribute-overwrite semantics on re-write (VERIFY, do not assume).**
- Question: writing the SAME expression twice (deterministic same handle) with DIFFERENT provenance attrs — does the second write's `add_atoms` **overwrite**, **merge**, or **append** the top link's `custom_attributes`? (Relevant when a fact is re-written from a different source, or across runs after a background-file change.)
- Probe: two writes of one canary expression with distinct `provenance_ref` values; mongosh inspection of the single top-link doc; record the semantics.
- Consequence: if overwrite — document that the LAST write wins per fact handle (benchmarks unaffected: cleanup removes cross-run residue); if merge/append — the reconstruction script must treat the attribute set as potentially multi-valued and define the resolution order (spec update before Phase 4 merge).
- Deliverable: probe script + result note; the Phase-4 script documents the observed semantics.

**Acceptance criteria:** both probes recorded with raw evidence (mongosh outputs + receipts) in the probe scripts' result notes; the mongo handle field name confirmed live against the LIVE writer; overwrite semantics documented.
**Test strategy:** probes are one-off scripts (excluded from the pytest registry); their findings are encoded as fixtures/assumptions in Phase 1/4 unit tests.
**Decisions depended on:** none (probes are decision-independent).

## 4. Phase 1 — facade: LedgerStore + `/v1/source` + `/v1/write` v4

**Files touched:**
- `deploy/das/write-bridge/provenance_store.py` — REWRITE as `LedgerStore` (keep `ArchiveError` name, flock/git plumbing conventions; delete `archive()`, `lookup()`, subject parsing, `_validate_url`).
- `deploy/das/write-bridge/app.py` — add `/v1/source` route (dispatcher `app.py:105-108`); delete `/v1/archive` + `MAX_ARCHIVE_BODY_BYTES` (`:16-18`, `:82-99`); `/v1/write`: new provenance key set, ledger gate, `top_handle` in the 200 response (`:73-80`).
- `deploy/das/write-bridge/write_client.py` — `_validate_provenance` v4 shape (`:70-87`); `_decorate_top_link` attribute set (`:108-128`); DELETE `_provenance_expression` + companion emission (`:131-139`, `:234-240`, `:251-256`, `:263`); `write()` returns `top_handle`; read-back covers fact links only.
- `deploy/das/write-bridge/README.md` — endpoint/attr documentation.

**Function-level behavior:**
- `LedgerStore.record(ref, sha256)`: validate ref (http(s) URL or absolute path, ≤480, no whitespace) + sha256 (64 lowercase hex); flock; ensure_repo; dedup scan (parse each ledger line; match `(ref, sha256)`) → hit: pickaxe `git log --reverse -S"<line>" -- SOURCE-LEDGER.json` → original commit, `deduped: true`; miss: insert one line before `]` (leading-comma form §2.2), `git add`, `git commit -m "ledger: <sha12> <ref[:96]>"`, return `{commit, deduped: false, entry_date}`.
- `LedgerStore.verify_commit(git_commit, ref, sha256)`: `git:<40hex>` shape; `rev-parse --verify <sha>^{commit}`; `git show --name-only --format=` → changed paths must be exactly `["SOURCE-LEDGER.json"]`; `git show <sha> -- SOURCE-LEDGER.json` diff → added lines (filter `^+`, strip leading `,`) that parse as JSON objects with exactly `{ref, sha256, entry_date}` → exactly one; its `(ref, sha256)` == payload; return entry metadata; else raise `ArchiveError` with §2.5 strings.
- `WriteApplication.handle`: provenance shape check `{ref, git_commit, blob_sha256}`; gate BEFORE `runner.write` (ordering preserved, `app.py:50-62`); response `{"handles", "verified", "missing", "top_handle"}`.
- `DasWriteRunner.write`: decorate top link with `metta_expression`, `provenance_ref`, `provenance_git_commit`, `provenance_blob_sha256`, optional `stv_*`; single-batch write; `verify_handles(fact)` only; result adds `"top_handle": fact.top_handle`.
- Optional (recommended, from Phase-0b findings): a post-write mongosh-free canary is NOT possible in-facade (no mongo access) — instead add a `--canary-attrs` CLI to the reconstruction script (Phase 4) for operator-side verification; facade-side best-effort stays as-is (documented residual risk §11).

**Acceptance criteria:** `/v1/source` appends/dedups per §2.2 with pure +1-line diffs (verify with `git diff` in tests); the citation gate rejects hallucinated/mismatched (commit, ref, sha) triples with the §2.5 strings; `/v1/write` 200 carries `top_handle`; no companion atoms are emitted; 16 KiB caps hold; the facade still has zero outbound HTTP.
**Test strategy (write-bridge pytest suite, `deploy/das/write-bridge/tests/`):**
- `test_provenance_store.py` — REWRITE: fresh-repo init (empty array + init commit); record→append (+1-line diff, leading-comma validity, `json.load` round-trip); dedup (same `(ref, sha)` → original commit, no new commit; same ref new sha → new entry); verify_commit chain (each failure condition: not-found / touches-other-files / adds-two-lines / entry-parse-fail / ref-sha-mismatch); flock serialization (two threads, both succeed, one commit).
- `test_app.py` — `/v1/source` routes (200/400/503, body-cap), `/v1/archive` gone (404), `/v1/write` v4 payload + gate threading + `top_handle` in response, legacy `{url, git_commit}` payload rejected with the shape error.
- `test_write_client.py` — attr decoration set; NO companion in the batch/read-back; `top_handle` in result; WriteFailure still carries deterministic handles.
**Decisions depended on:** D1 (ledger-only), D2 (companion drop), D6 (same-path fresh repo).

## 5. Phase 2 — plugin: v3 grammar + resolver + sha256 + cache + receipt

**Files touched:**
- `deploy/omega/plugins/das-write/das_write_bridge.py` — `_parse_suffix` v3 (drop git-token branches `:266-272`, `:279-286`, pairing rule `:297-298`; add `git:` rejection + path-ref roots check); NEW `_resolve_source(ref)` (fetch internals absorbed from `archive_source`, `:461-489`); NEW sha256 + per-process cache `ref → (sha256, commit)`; `_post_to_facade` two-call flow + `top=` receipt (`:394-406` rework); DELETE `archive_source()` (`:443-540`) + `ARCHIVE_PATH` (`:82`).
- `deploy/omega/plugins/das-write/das-write.metta` — REMOVE the `archive-source` clause (`:35-36`); update the description block (v3 grammar, `top=` receipt, no archive skill).
- `deploy/omega/plugins/das-write/README.md` — rewrite to the v3 contract.
- OPTIONAL config key `dasWriteSourceRoots` (comma/whitespace-separated allowed path prefixes; read via `config_get_by_key`, default unset → path refs disabled). No other Omega config keys.

**Function-level behavior:**
- `intercept()` add-atom path: balanced expression → suffix parse → v3: `{ref, tv}`; v2 `git:` token → `BRIDGE-PERSIST-WRITE-FAILED: git citations are no longer accepted — pass the source reference; archiving is automatic`; v1 (no suffix) → plain write (D3).
- `_resolve_source(ref)`: URL → bounded fetch (reuse: 2 MB cap, text content types, 20 s, `:88-93`); path → `dasWriteSourceRoots` prefix check then read (same cap). Returns `(content, content_type?)`.
- sha256: `hashlib.sha256(content.encode("utf-8")).hexdigest()`.
- Cache: module-level dict, per-process (clears on agent restart — per-case restarts `run_benchmark.py:720-722` make it cold per case window; dedup absorbs cross-window re-POSTs — a deduped `/v1/source` POST returns the original commit, so retries are idempotent end-to-end; the ingest-attestation lane this once fed is dropped, resolution 6).
- Flow: cache miss → `POST /v1/source {ref, sha256}` → `{commit, deduped, entry_date}` → `POST /v1/write {metta, verify:true, provenance:{ref, git_commit: commit, blob_sha256: sha}}` → receipt `BRIDGE-PERSIST-OK: verified=<n> top=<handle> [stv=(s,c)]`.
- Every failure mode (fetch/read/roots/content-type/ledger/write/transport) → `BRIDGE-PERSIST-WRITE-FAILED: <reason>` (§2.5); never raises.

**Acceptance criteria:** v3 grammar accepted (URL + path refs behind roots); v2 rejected with the actionable string; v1 unchanged; first-write-per-source = 1 fetch + 2 POSTs, subsequent facts = 1 POST (cache); receipts carry `top=`; the plugin file contains no `archive-source` references; `das-write.metta` loads cleanly (MeTTa import + clause rebind smoke).
**Test strategy:**
- `deploy/omega/plugins/das-write/tests/test_provenance_suffix.py` (existing module — EXTEND) — v3 shapes (ref only; ref+stv; path ref in/out of roots), v2 rejection, v1 unchanged, `git:` rejection, oversized/whitespace refs.
- `deploy/omega/plugins/das-write/tests/test_das_write_bridge.py` (existing module — EXTEND; DELETE the `archive_source`/`ARCHIVE-OK` test cases with the function) — fake-facade flow: `/v1/source`→`/v1/write` call order, cache hit (second write same ref = 1 POST), dedup propagation, failure statuses per §2.5, receipt format incl. `top=` from the response `top_handle`.
**Decisions depended on:** D3 (v1 permissive), D5 (benchmark URL refs — plugin supports both), D7 (archive-source removal).

## 6. Phase 3 — host migration runbook (operator/SSH steps — NOT automated)

**Deliverable:** `docs/issue-2-ledger-migration-runbook.md` (new doc in this repo) + a `deploy/das/write-bridge/tools/migrate_ledger_repo.sh` **verification-only** helper (checks, never mutates). The migration itself is operator-executed (decision D6 — evidence is never mutated by scripts).

**Steps (recorded verbatim in the runbook, executed over SSH on the OVH host):**
1. Preconditions: facade container healthy; note current repo state `sudo git -C /home/ubuntu/omega-provenance log --oneline | head`; confirm no benchmark run in flight.
2. Backup: `sudo git -C /home/ubuntu/omega-provenance bundle create /home/ubuntu/omega-provenance.legacy-<date>.bundle --all` (full history incl. blobs) + `sudo tar czf /home/ubuntu/omega-provenance.legacy-<date>.tar.gz -C /home/ubuntu omega-provenance` (working tree, belt-and-braces); verify: `git bundle verify`, tar listing; record both paths (the legacy paths feed `--legacy-repo`).
3. Retire: `sudo mv /home/ubuntu/omega-provenance /home/ubuntu/omega-provenance.legacy-<date>` (keep readable at the known path for legacy resolution; alternatively restore from the bundle at a sibling dir).
4. Fresh init (SAME host path — compose/env unchanged, `compose.write-bridge.yaml:67,71`):
   ```
   sudo mkdir -p /home/ubuntu/omega-provenance && sudo chown -R 65532:65532 /home/ubuntu/omega-provenance
   # as the container user or with matching ownership, create SOURCE-LEDGER.json containing:
   # [
   # ]
   sudo git -C /home/ubuntu/omega-provenance init && … initial commit "ledger: init" (identity: omega-write-bridge <write-bridge@omega.local>)
   ```
   (Container git runs as user 65532 — the per-invocation `-c` identity config convention, `provenance_store.py:14,46-47`, is preserved in `LedgerStore`.)
5. Restart the facade: `sudo docker compose -f deploy/das/write-bridge/compose.write-bridge.yaml up -d` (picks up the new code + repo; `ensure_repo()` is idempotent).
6. Verify: preflight's `provenance_repo` check (`run_benchmark.py:391-396`) passes; manual smoke: `POST /v1/source {"ref": "https://example.com/smoke", "sha256": "<64hex>"}` → 200 + commit; `git -C … show --stat` → exactly one SOURCE-LEDGER.json line added; delete nothing (ledger smoke entries are permanent evidence — use a clearly-labeled ref).
7. Sequencing rule: the plugin redeploy (Phase 2 rollout via the normal `start.sh` `:ro` mount path) happens in the SAME window as this migration — between the two, v2 writes fail loudly at the gate (actionable 400), which is the designed safe state.

**Acceptance criteria:** runbook committed; fresh repo has exactly one init commit and a valid empty-array ledger; facade healthy; legacy bundle verified; `--legacy-repo` paths recorded.
**Test strategy:** the verification helper (`--check` mode) asserts: repo exists, HEAD touches only SOURCE-LEDGER.json or is the init commit, `json.load` of the ledger is a list, every element has exactly the 3 keys; run as part of preflight as the REQUIRED `ledger_repo_format` check (resolution 5 — replaces the old `provenance_repo` check).
**Decisions depended on:** D1, D6.

## 7. Phase 4 — reconstruction script (standalone)

**Files touched (NEW):** `deploy/das/write-bridge/tools/reconstruct_sources.py`, `deploy/das/write-bridge/tools/README.md` (standalone usage, classification rules, exit codes, examples, the Phase-0b attribute-semantics note).

**Function-level behavior:**
- Inputs per §2.4. Parse the trace with the grader's helpers (import or mirror `grading.normalize_expression`, `grading._split_derivation_atoms`, `grading.parse_reasoning_trace` semantics — `grading.py:139-141`, `:266-286`, `:447-460`).
- Handle chain per §2.4's spine. Mongo access: `docker exec <mongo> mongosh … --eval` (the `run_benchmark.py:504-510` pattern; root creds via container env); ONE `find({_id: {$in: [...]}})` for all distinct handles (bounded batches), projecting `custom_attributes`.
- HANDLES cross-check: for each `--facts` expression (aligned order), re-derive `top_handle`; compare with `--handles` → `H_MISSING` (no handles supplied/empty), `H_COUNT_MISMATCH`, `H_MISMATCH` into `handles_check.conditions`.
- Ledger chain per element: `git cat-file -e <sha>^{commit}` → `git show --name-only --format=` (paths == `[SOURCE-LEDGER.json]`) → diff added lines → exactly one entry-shaped line → `(ref, sha256)` == the atom's attrs → optional `--background-dir` byte-hash (`sha256(background file) == entry.sha256`, filename from ref tail for URL refs — the `url.rsplit("/",1)[-1]` convention, `run_benchmark.py:1028`).
- `--legacy-repo`: if a commit is not in the ledger repo and `--legacy-repo` is given, resolve via the OLD chain (`provenance_check.resolve_citation`, `provenance_check.py:70-147`) and mark informational (`legacy: true`) — never blocking, and never in the default grade path (resolution 4: optional-informational only; the harness's default grade never passes it).
- `--source-paths-out`: writes the resolved source file paths used (one per line) — the harness's byte-compare input.
- Output + exit codes per §2.4; zero LLM; zero pattern-engine queries.

**Acceptance criteria:** CLI exactly per §2.4; deterministic (same inputs → same JSON + exit code); a full happy-path trace resolves with exit 0; a missing-attr fact yields exit 2 + `NO_PROVENANCE_ATTRS`; a fabricated handle yields `H_MISMATCH` in the JSON; mongo/ledger outages yield exit 1 with a clear message.
**Test strategy:** `tests/reasoning-windowless-room/unit/test_reconstruct_sources.py` — fixtures: scripted mongosh outputs (fake `docker exec` via monkeypatch), temp git ledger repos (init + scripted appends), classification rules (query clause exempt; exec outputs exempt; derivation = premises' sources), per-predicate aggregation, legacy fallback, exit codes, `--source-paths-out`, H cross-check cases. Plus the write-bridge-side unit: `deploy/das/write-bridge/tests/test_reconstruct_integration.py` (ledger fixtures from `test_provenance_store.py` helpers).
**Decisions depended on:** D4 (H blocking semantics live in the gate, not the exit code), D1/D6 (legacy fallback).

## 8. Phase 5 — benchmark rewiring

**Files touched:** `tests/reasoning-windowless-room/grading.py`, `run_benchmark.py`, `history_parse.py`, `agent_prompt_template.md`, `GATES-REFERENCE.md`, `test-spec.md`; plus `deploy/omega/plugins/das-read/das-read.metta` (item 10 — description clause only; NO engine/proxy code changes).

**Function-level behavior:**
0. **Gate-condition audit (owner directive — resolution 4: "removing the unnecesery or contradicting failure and info gates due to the new design"):** enumerate EVERY condition code in `grading.py`; classify each KEEP / MODIFY / RETIRE against v4; retire the unnecessary or contradicting ones — candidates: all retired P_* legacy codes (`COMMIT_MULTIPLE_SOURCE_BLOBS`, `INDEX_*`, `BLOB_*`, `URL_MISMATCH`) in any active path, ARCHIVE-OK-dependent branches, and any condition whose evidence source no longer exists under v4 (incl. the retired facade-log ingest-attestation lane, resolution 6). Document the full audit table in `GATES-REFERENCE.md` (per code: keep/modify/retire + rationale).
1. **Prompt slim** (`agent_prompt_template.md`): delete the step-1 archive sub-step + `source …` record lines (`:43`); add-atom call form → v3 (`:44`); delete the SOURCES line + copy rules (`:60`, `:81`, `:91-92`) and the first-cycle archive lane (`:34`); record line → `expr <expression> top=<handle>`; add the `HANDLES:` line to the REQUIRED FORMAT block (§2.7) with copy-from-receipt rules — retrieval or write receipts (item 10); keep `expr`/`exec`/`query`/`trace` lines, QUERY/FACTS/REASONING/FINAL ANSWER formats, ledger, anti-loop, STOP; `urls.txt` stays as the ref vocabulary (D5).
2. **E_NO_INGEST** (`grading.py:676-692`): RECEIPTS-ONLY (resolution 6) — blocking iff first case AND `window_persist_receipts == 0` (BRIDGE-PERSIST-OK receipts ARE extractable from history windows, verified live, `extract_persist_receipts` `history_parse.py:119-121`); DELETE the attested branch (`:684-690`) entirely.
3. **Attestation lane** (`run_benchmark.py:328-331`): the write/archive/source-count census is DROPPED — no `source_count` rewire (resolution 6); `collect_attestation` keeps ONLY the query lanes (`access_count`, `qe_pattern_match` — they serve `Q_ATTESTED_VIA_ACCESS_LOG`, a DIFFERENT gate covering the known history-collapse defect for queries); grade JSON census fields follow (`:1059`, `:1063` — ingest census fields removed, query fields kept).
4. **P-gate** (`grading.py:824-839` + `run_benchmark.py:964-1015`): citations no longer parsed from a SOURCES line; `grade_case` invokes `reconstruct_sources.py` (trace + FACTS + HANDLES) and maps JSON `conditions` → `P_UNRESOLVED:*` / `P_MISSING` / H_* codes; the reconstruction/byte-compare lane (`run_benchmark.py:1017-1045`) takes `(ref, sha256)` from the script output (byte-hash `sha256(background file) == entry.sha256`; `--source-paths-out` feeds it); `P_SOURCE_SET_MISMATCH` informational vs `facts.SOURCE_URLS` (`facts.py:12-18`).
5. **HANDLES gate**: parse `HANDLES:` line; alignment with FACTS expressions; `H_MISSING`/`H_COUNT_MISMATCH`/`H_MISMATCH` blocking (D4).
6. **history_parse** (`history_parse.py:110-116`, `:124-126`): retire `extract_add_atom_shas`/`extract_archive_receipts` from the v4 grade path (functions kept for legacy history formats — no v4 grade-path callers, the legacy batch-grade lane being retired per resolution 4); census fields updated (query lanes only, resolution 6).
7. **Preflight — full v4 adaptation (resolution 5: "adapt also preflight checks to the new design") — audit EVERY preflight check against v4:** (a) `write_bridge_smoke` exercises the FULL v4 path: `POST /v1/source` with a clearly-labeled smoke ref → `POST /v1/write` with the provenance payload → validate `top_handle` in the response (cleanup after; ledger smoke entries are permanent evidence — clearly-labeled ref, Phase 3 step 6); (b) the `provenance_repo` check (`run_benchmark.py:391-396`) becomes the LEDGER FORMAT check from Phase 3's helper (repo exists, `SOURCE-LEDGER.json` valid JSON array, 3-field entries) — REQUIRED, not optional; (c) ADD the das-write grammar-version check (grep the mounted `das-write.metta` for a v3 marker string, the `skill_description_upgraded` pattern `:410-415` / `metta_skill_upgraded` `:427-438`); (d) REMOVE/REPLACE any check referencing `/v1/archive` or `ARCHIVE-OK`; (e) judge/das-read/agent checks unchanged; (f) optional `dasWriteSourceRoots` check if path refs are exercised.
8. **Cleanup** (`run_benchmark.py:513-584`): N1 regex → match `custom_attributes.provenance_ref` AND keep `provenance_url` (`$or`) for pre-migration residue (`:533-542`); NEW one-time sweep net **N3**: for each discovered benchmark fact expression, compute `top_handle` client-side (`parse_fact`), then delete links whose targets include the Symbol node named `"fact:<top_handle>"` AND whose leading-symbol target is `WriteProvenance` — **never** all WriteProvenance links (live research companions exist, `docs/status.md:239`) and never `CampaignProvenance` (`deploy/das/import-wrapper/import_wrapper.py:249-256`); extend the residue invariant (`:658-679`) with `remaining companions == 0`; cleanup entries recorded in `cleanup-das.json`.
9. **Docs:** `GATES-REFERENCE.md` — the item-0 gate-audit table (EVERY condition code: keep/modify/retire + rationale), §2 informational (`E_INGEST_ATTESTED_VIA_FACADE_LOG` RETIRED — entry removed), §5 E-gate (receipts-only `E_NO_INGEST`), §7 P-gate (new chain + codes), NEW H-gate subsection, §8 attestation fields (query lanes only: `access_count`/`qe_pattern_match`; write/archive/source-count census dropped), §9 artifacts (`cleanup-das.json` N3, grade-case JSON handles/ledger fields), §10 classification, §11 history entry `v17 (2026-10-…): transparent provenance — v3 grammar, SOURCE-LEDGER.json, reconstruction-script P-gate, HANDLES line`. `test-spec.md` — version paragraph + history entry.
10. **das-retrieve handle vocabulary (addendum 2026-10-27 22:20 UTC — VERIFIED by orchestrator, do not re-derive):** the ENGINE/PROXY need NO changes — the read-proxy already returns per-answer `handles[]` + `assignments` (`deploy/das/proxy/das_client.py` `_normalize_answer`), and the agent-side client `das_retrieve()` already embeds the full answers JSON in the `DAS_RETRIEVE_OK … results=` receipt (`deploy/omega/plugins/das-read/das_skills_read.py` `das_retrieve()`). Work items: (a) the das-retrieve skill description (`deploy/omega/plugins/das-read/das-read.metta`, add-skill description) gains an explicit clause that results carry atom handles and receipts may be quoted — INSPECTED 2026-10-27: the current description mentions neither handles nor the results payload (0 occurrences of "handle"), so the clause is added; (b) the benchmark prompt's HANDLES copy rules (item 1) instruct the agent to copy atom handles from EITHER retrieval receipts (`DAS_RETRIEVE_OK … results=`) or write receipts (`BRIDGE-PERSIST-OK … top=`). NO new endpoints; NO engine/proxy changes.

**Acceptance criteria:** a dry-run of `full` renders the slim prompt with the HANDLES line; every gate's unit fixtures pass against the new parsing; grep confirms no `ARCHIVE-OK`/`SOURCES:`/`add_atom_shas` references remain in the v4 grading path; the item-0 gate-audit table is committed in `GATES-REFERENCE.md` with every condition code classified; no ingest-census fields (`write_count`/`archive_count`/`source_count`) remain in the grade path (query lanes only); the P-gate fails a fabricated-handle fixture (H_MISMATCH) and a missing-source fixture (P_UNRESOLVED:NO_PROVENANCE_ATTRS); the das-read skill description carries the handles clause and `das-read.metta` loads cleanly (import smoke).
**Test strategy:** Phase 6 (below) — the unit suite IS the test strategy for this phase; e2e validation comes after Phase 3's runbook is executed on the host (a preflight + smoke + one 75-minute live wr run against the slim prompt is the iteration's exit criterion; expected gate surface: Q/R/E unchanged in substance, P from reconstruction, H from the cross-check).
**Decisions depended on:** D3, D4, D5, D7 (prompt language), D2 (N3 sweep scope) — all RESOLVED (§10); resolutions 4, 5, 6 shape items 0, 7 and 2-3.

## 9. Phase 6 — tests per component (consolidated plan)

**Write-bridge pytest suite** (`deploy/das/write-bridge/tests/`, registry via existing conftest):
- `test_provenance_store.py` — REWRITE (ledger append/dedup/verify chains, +1-line diffs, flock, entry identity).
- `test_app.py` — EXTEND (`/v1/source`, `/v1/archive` removal, v4 write payload/gate/`top_handle`).
- `test_write_client.py` — EXTEND (attr set, no companion, `top_handle`, idempotent re-write).
- `test_metta_to_atoms.py`, `test_cleanup.py` — unchanged.
- NEW `test_reconstruct_integration.py` (script vs. ledger fixtures; see Phase 4).

**Windowless-room unit suite** (`tests/reasoning-windowless-room/unit/`, registry `run_tests.py`):
- NEW `test_reconstruct_sources.py` (Phase 4 fixtures: classification, chain conditions, exit codes, legacy fallback, `--source-paths-out`).
- NEW `test_handles_gate.py` (H_MISSING / H_COUNT_MISMATCH / H_MISMATCH; alignment; blocking semantics per D4; unsolvable exemption).
- NEW `test_v17_prompt.py` (slim prompt: no archive lane / no `source` lines / no SOURCES rules; `expr … top=<h>` record line; HANDLES line present in the REQUIRED FORMAT block; v3 add-atom form; `urls.txt` citation instruction).
- REWRITE (pinned tests asserting removed rules): `test_v14_prompt.py` (×5 — full-provenance `source` lines + SOURCES copy rules), `test_v12_prompt.py` (×4 — FACTS copy rules KEEP, SOURCES half drop), `test_v11_prompt.py` (×4), `test_v8_prompt.py` (×9), `test_v6_prompt.py` (×10) — each asserted rule re-pointed at the slim prompt; `test_prompts_render.py` (HANDLES placeholder + new record-line format).
- EXTEND: `test_grading.py` (E_NO_INGEST reduction, P/H wiring), `test_v3_gates.py` / `test_v9_gates.py` / `test_v10_gates.py` / `test_v11_gates.py` (gate-condition fixtures), `test_history_parse.py` (retired lanes remain valid for legacy texts).
- UNCHANGED: `test_provenance_check.py` (legacy resolver — covered as a STANDALONE UNWIRED tool; no harness lane calls it, resolution 4), `test_facts.py`, `test_v15_judge.py`, `test_v4_levers.py`.

**das-write plugin suite** (`deploy/omega/plugins/das-write/tests/` — covered per Phase 2): `test_provenance_suffix.py` + `test_das_write_bridge.py` extended to v3 (v2-rejection, resolver/cache/receipt flows); `archive_source` cases deleted with the function.

**E2E (after host migration):** preflight PASS (incl. the full-v4 smoke, grammar-version and REQUIRED ledger-format checks) → cleanup-das with N3 sweep → one live wr run; expected: Q/E/R unchanged in substance, P from the reconstruction script, H from the cross-check; budget-exhaustion rate compared to the wr3n baseline (0/3, commit `6684f4f`, artifacts `tests/reasoning-windowless-room/results/wr3n-20261026/`); residue invariants (expressions + companions) zero after cleanup. The definitive full validation follows in Phase 7 (§12); the asset review in Phase 8 (§13).

---

## 10. Decision points (RESOLVED 2026-10-27 22:37 UTC; defaults restated)

**Decision gate CLEARED — implementation authorized.** All seven decisions RESOLVED (approved as defaulted, Balazs 2026-10-27 22:37 UTC: "For the D1-7 decision, I approve all the listed defaults."). The six inconsistency resolutions of the same timestamp (§11, "Resolved inconsistencies") are cross-referenced below where they touch a decision.

- **D1 — Ledger-only vs ledger+content:** RESOLVED (approved as defaulted, Balazs 2026-10-27 22:37 UTC; resolution 1: "yes, ok to make this disappear" — content disappearing explicitly accepted). Default **LEDGER-ONLY** per directive (3 fields, single file). Honest trade-off: source content is no longer archived anywhere — verification = sha256 vs harness-known files; general campaigns lose byte-level evidence of what the agent read. Benchmark unaffected (harness holds background files and hashes them directly). Content-blob extension possible later.
- **D2 — WriteProvenance companion:** RESOLVED (approved as defaulted, Balazs 2026-10-27 22:37 UTC). Default **DROP for new writes** (custom-attribute-primary); one-time N3 sweep of OLD benchmark-fact companions (handle-scoped); campaign companions untouched.
- **D3 — Suffix-less (v1) writes:** RESOLVED (approved as defaulted, Balazs 2026-10-27 22:37 UTC; resolution 5 upgrades the preflight smoke to the full v4 path — the v1 grammar itself stays valid). Default **PERMISSIVE** (preflight smoke, canaries, dormant campaign prompts keep working; enforcement lives in the gate). Alternative strict-reject would force provenance discipline at the grammar but break the smoke/canaries until updated.
- **D4 — HANDLES strictness:** RESOLVED (approved as defaulted, Balazs 2026-10-27 22:37 UTC). Default **required + blocking** (missing/mismatch fail the case — fabrication tripwire; cheap for the agent: copy from a retrieval or write receipt, carried across wake cycles by the `expr … top=<h>` record line).
- **D5 — Benchmark source-ref form:** RESOLVED (approved as defaulted, Balazs 2026-10-27 22:37 UTC). Default **URL refs** (`urls.txt` + `facts.SOURCE_URLS` byte-compare mapping); container path refs remain a general-skill capability behind `dasWriteSourceRoots`.
- **D6 — Old-repo migration mechanics:** RESOLVED (approved as defaulted, Balazs 2026-10-27 22:37 UTC; resolution 4: `--legacy-repo` stays optional-informational only — never blocking, never in the default grade path; the legacy batch-grade citation lane is retired; `provenance_check.py` is kept as a standalone unwired tool). Default **git bundle + tar backup to a sibling path** (`/home/ubuntu/omega-provenance.legacy-<date>.bundle`), **fresh init at the SAME host path** (compose/env unchanged), `SOURCE-LEDGER.json` initial commit = empty array, `--legacy-repo` fallback; operator-run (Phase 3), never scripted mutation.
- **D7 — standalone `archive-source` skill clause:** RESOLVED (approved as defaulted, Balazs 2026-10-27 22:37 UTC). Default **REMOVE** (subsumed by the write skill; smaller agent surface; requires `das-write.metta` clause removal + README/skill-description rewrite).

---

## 11. Consistency review

**Resolved inconsistencies (2026-10-27 22:37 UTC — Balazs; folded into this spec, cross-referenced):**
1. **D1 trade-off** (source content no longer archived anywhere; ledger-only): "yes, ok to make this disappear" — APPROVED; D1 resolved-approved (§10; residual risk 1 below).
2. **URL-drift residual risk** (residual risk 2 below): "I dont understand it. clarify" — clarified to the owner out-of-band; the spec now makes the three moments explicit (agent reads at research time / skill re-fetches + hashes at write time / harness byte-compares at grade time — the ledger proves what was fetched at write time, NOT what the agent saw at read time) and records it as a documented, accepted bound (benchmark: repo-pinned sources, drift effectively nil).
3. **SOURCE-LEDGER.json serialization pin** (§2.2): "2add/1del diff, its fine, no prob with that" — the owner explicitly accepts the 2-add/1-del alternative; the leading-comma +1-line form stays pinned as a simplicity choice, not a requirement.
4. **Legacy-lane retention + harness gates**: "dont keep it if not necessary, you can change the harness to adapt to it. In general a lot of changes will be needed in the test harness script, including removing the unnecesery or contradicting failure and info gates due to the new design" — Phase 5 item 0 (full gate-condition audit); `--legacy-repo` optional-informational only (never blocking, never in the default grade path); legacy batch-grade citation lane retired from `run_benchmark.py` active paths; `provenance_check.py` kept as a standalone unwired tool (Phase 8 item 2).
5. **Preflight checks**: "adapt also preflight checks to the new design" — Phase 5 item 7: every preflight check audited against v4; full-v4-path smoke; REQUIRED ledger-format check; grammar-version check added; `/v1/archive`/`ARCHIVE-OK` checks removed; judge/das-read/agent checks unchanged.
6. **Facade-log ingest-attestation lane**: "you can drop this attestation feature. I care about the direct verification evidence of the MeTTa reasoning trace leading to the answer..." — `E_INGEST_ATTESTED_VIA_FACADE_LOG` retired entirely; `E_NO_INGEST` receipts-only; `collect_attestation` keeps ONLY the query lanes (`access_count`, `qe_pattern_match` → `Q_ATTESTED_VIA_ACCESS_LOG`, kept); design principle recorded in §2.6.

**Resolved design points (verified against current code, citations re-checked):**
1. The v3 grammar fits the existing plugin parser skeleton (`das_write_bridge.py:235-302`) with strictly fewer branches; the 2048-char cap is expression-only (`:347,356`) — headroom ample.
2. The custom-attribute-primary join is fully deterministic: handles are type+targets hashes (`write_client.py:60-63`), mongo link/node docs are keyed `_id` = handle (`iter16_groundtruth.js:8-12`), and the harness has the `docker exec mongosh` precedent (`run_benchmark.py:504-510`). No pattern-engine query is anywhere in the provenance path — the §2.3 engine quirks (ground-pattern non-completion, multi-variable unprovenance) are irrelevant to provenance.
3. The E-gate's FACTS grounding survives both the removal of `source` lines and the new `top=` annotation: `parse_facts_index` reads only `expr`-labeled / parenthesized lines (`grading.py:175-196`) and the balanced-prefix parser tolerates trailing annotations (`grading.py:144-172`, v9 live evidence).
4. The ingest-attestation lane is DROPPED entirely (resolution 6 — no `/v1/archive` → `/v1/source` census rewire, `run_benchmark.py:328-331`): `E_NO_INGEST` is receipts-only (receipts extractable from history windows, `history_parse.py:119-121`) and `collect_attestation` keeps only the query lanes (`access_count`, `qe_pattern_match` → `Q_ATTESTED_VIA_ACCESS_LOG`); the per-case agent restart (`:720-722`) keeps the plugin cache cold per window, and dedup makes cross-window re-POSTs idempotent.
5. Dedup + deterministic handles make retries idempotent end-to-end (ledger: original commit returned; DAS: same atoms).
6. `provenance_check.py`'s old chain is preserved verbatim as a STANDALONE UNWIRED legacy resolver (`--legacy-repo` optional-informational fallback only; the legacy batch-grade citation lane is retired from `run_benchmark.py` active paths and any remaining harness import retired with it — resolution 4), so no old artifact becomes unreadable.

**Residual risks (accepted, with mitigations):**
1. **Content is not archived (D1 — owner-accepted, resolution 1: "yes, ok to make this disappear"):** verification = sha256 vs harness-known files. General campaigns lose byte-level evidence of what the agent read. Mitigated for the benchmark by the harness byte-hash check; a content-blob extension can be added later without grammar changes.
2. **URL drift between the agent's read and the skill's fetch (clarified per resolution 2 — documented, accepted bound):** three distinct moments: the agent reads the source at RESEARCH time; the skill re-fetches and hashes it at WRITE time; the harness byte-compares at GRADE time. The ledger proves what was fetched at write time, NOT what the agent saw at read time. Detected by the harness byte-hash check (`sha256(background file) == entry.sha256`); recorded as `matches_repo_file`-style evidence + `P_SOURCE_SET_MISMATCH` visibility, not silently trusted. Residual: drift between the skill's fetch and the harness's hash at grade time would fail the byte-compare while the ledger is internally consistent — report-visible, operator-adjudicated. Accepted bound: benchmark sources are repo-pinned, so drift is effectively nil (raw-github `main` is the only drift surface).
3. **Provenance is invisible to das-retrieve / agent queries (accepted by design):** mongo is THE provenance channel; an agent (or any pattern-engine client) cannot read provenance attributes. Consequences: no write-time read-back of the attributes (custom-attribute persistence is best-effort, `write_client.py:111-117`) — a dropped attribute surfaces at reconstruction (case FAIL), not as a write failure; Phase-0b probes the overwrite/persistence semantics; the reconstruction gate is the deterministic detector.
4. **Semantic misattribution remains undetectable** (agent cites ref A while deriving from B) — same as today; bounded for the benchmark by the source-set + byte-hash cross-checks.
5. **v2 rejection window:** between the repo migration and the plugin redeploy, v2 writes fail loudly at the gate (actionable 400) — the designed safe state; Phase 3's sequencing rule makes the window explicit.
6. **Ledger growth:** one line + one commit per unique `(ref, sha256)` — unbounded but tiny; optional quota preflight check specified (Phase 3 helper).
7. **N3 sweep scope:** deleting by `WriteProvenance` leading symbol alone would destroy live research-companion evidence (`docs/status.md:239`) — the spec pins handle-scoped deletion (benchmark fact handles only); campaign `CampaignProvenance` links are never touched.

---

## 12. Phase 7 — live e2e validation (operator/SSH, on the OVH host)

**Precondition:** Phases 0-6 merged and deployed: rebuild the write-bridge container; redeploy the agent plugin overlay via the normal `start.sh` `:ro` mount path; ledger repo migration executed per the Phase 3 runbook.

**Procedure:** run the updated harness for ALL 3 cases — sequential `full` flow: preflight → cleanup-das → setup/agent/grade per case → report. This is the definitive e2e exit criterion (it supersedes the Phase 5/6 single-run smoke as the final gate).

**Requirement — root-cause analysis of ANY failure:** classify each failure as agent-side / harness-side / bridge-side / environment, with evidence (grade JSON conditions, receipts, docker logs, mongo state), recorded in the run's `results/` dir plus a root-cause note under `tests/reasoning-windowless-room/results/<run-id>/`. Iterate fixes until all 3 cases PASS or a genuine external blocker is reached; report evidence per iteration.

**Baseline to beat:** `wr3n-20261026` (0/3 agent-side; commit `6684f4f`; artifacts `tests/reasoning-windowless-room/results/wr3n-20261026/`).

**Acceptance criteria:** 3/3 PASS, or a documented genuine external blocker with evidence; every failure in every iteration carries a classified root-cause note with evidence in the run dir.
**Decisions depended on:** D1–D7 — all RESOLVED (approved as defaulted, Balazs 2026-10-27 22:37 UTC; §10).

## 13. Phase 8 — repo asset review (removal/update list)

**Purpose:** systematic review for assets/scripts that become outdated under the v4 design, producing a removal/update list executed as part of the implementation commits (each removal = its own elementary commit with rationale in the message, §14). Every candidate is VERIFIED before marking — cite what references it; "removable" = nothing load-bearing references it after its phase lands.

**Candidate list (seeded by the 2026-10-27 addendum; re-verify each at review time):**
1. Legacy `provenance_store` methods + `/v1/archive` route + plugin `archive_source` paths — already spec'd in Phases 1-2 (cross-reference only; no separate review action).
2. `tests/reasoning-windowless-room/provenance_check.py` old blob/index chain — KEEP as a STANDALONE UNWIRED tool (historical/legacy reference; §2.4 `--legacy-repo` optional-informational fallback, §2.6 legacy carve-out — resolution 4). Retire from `run_benchmark.py` active paths: the in-run citation lane (`:928-1045`, rewired per Phase 5) AND the legacy batch-grade citation lane (`:1274+`); if any harness import of `provenance_check` remains after the rewire, retire that import too.
3. `history_parse.py` `extract_archive_receipts`/`extract_add_atom_shas` — retire from the v4 grade path per Phase 5 item 6 (functions kept for legacy history formats — no v4 grade-path callers, resolution 4); confirm no other live callers remain.
4. `deploy/omega/prompts/*.txt` archive-source references (e.g. `research-provenance-20261021-v8.txt`) — LEAVE THEM: dormant campaign prompts are historical campaign records, not runtime-loaded assets; retiring them would falsify campaign history; if ever reused post-v4, the v2 grammar fails loudly with the actionable §2.5 error (the designed safe state).
5. Duplicate das-read adapter dir `deploy/omega/das-read/` vs `deploy/omega/plugins/das-read/` — VERIFIED 2026-10-27: `deploy/omega/das-read/das_skills.py` is byte-identical to `deploy/omega/plugins/das-read/das_skills_read.py` (`diff -q` clean); the WIRED copy is `deploy/omega/plugins/das-read/` (`plugins.yaml.overlay:77-79`, `start.sh:20`). The non-wired `deploy/omega/das-read/` is a REMOVAL CANDIDATE — its own small commit, which must ALSO drop the `start.sh:24` fallback bind-mount (`deploy/omega/das-read/das_skills.py:/PeTTa/repos/Omega/src/das_skills.py:ro`) in the same commit: that mount is the copy's only live reference (the `das-read.metta` header documents it as a fork-image fallback).
6. `deploy/das/write-bridge/tests/` iter5/6/6b/7/8/11 probe scripts — v2-era deployed-surface probes (cleanup-defaults tuning, absence-oracle matrix, canary loops); retire those whose subject the ledger rewrite removes or invalidates (verify each probe's subject against the post-v4 surface before marking). KEEP `iter16_groundtruth.js` (documents the mongo schema; cited by §2.4's handle chain); `iter16_probe.py` stays as the Phase-0 live-probe pattern.
7. Found during this review: `deploy/das/write-bridge/tests/test_provenance_app.py` — v2-citation-gate + `/v1/archive` tests (`:97-175`) become outdated with the Phase 1 rewrite — absorb its still-live assertions into the `test_app.py` extension (Phase 1 test strategy) and retire the file.

**Acceptance criteria:** the removal/update list is committed with verification citations for every line; each executed removal is its own elementary commit with rationale in the message; nothing load-bearing references a removed asset (grep-verified).
**Decisions depended on:** D1, D2, D7 (they define what "v2-era" means for the review scope).

## 14. Commit & branch plan

- **Branch:** `issue-2-transparent-provenance`, cut from current `main`.
- **Commits:** small and elementary — one logical change each, mapping 1:1 to spec phases/sub-phases; each phase's tests are included in that phase's commit (no separate test dumps).
- **Issue linking:** EVERY commit references issue #2 so GitHub links it: subject prefix `issue-2:` AND trailer `Refs #2`. The final/fusion commit (or PR body) carries `Closes #2` ONLY when the work is definitively done (all phases green + live e2e 3/3 PASS per Phase 7); otherwise `Refs #2`.
- **Push target:** the `ktfh-claw` fork remote ONLY — never upstream.

**Suggested commit sequence:**
1. `issue-2: docs — provenance analysis v4 + implementation spec (addendum 2026-10-27)` — docs FIRST (both docs).
2. Phase 0 probe scripts + result-note stubs (live evidence lands in a later results commit).
3. Phase 1 facade — elementary sub-commits as natural: `LedgerStore` rewrite (+ tests); `/v1/source` route + `/v1/archive` deletion + `/v1/write` v4 gate (+ tests); `write_client` decoration/`top_handle` (+ tests).
4. Phase 2 plugin — v3 grammar + resolver/sha256/cache/receipt + `das-write.metta` + README (+ plugin tests); optional `dasWriteSourceRoots` config.
5. Phase 3 — migration runbook doc + verification-only helper.
6. Phase 4 — reconstruction script + tools README (+ unit/integration tests).
7. Phase 5 — benchmark rewiring, including the item-10 das-read description clause (+ unit-suite rewrites + docs: `GATES-REFERENCE.md`, `test-spec.md`).
8. Asset-removal commits per the Phase 8 review list — one commit per removal, rationale in the message (includes the `deploy/omega/das-read/` + `start.sh` fallback-mount removal).
9. Results/evidence commits as they land (probe results, live-run artifacts, Phase-7 root-cause notes).

---

## Appendix — consolidated string/condition/exit-code tables

**Statuses:** `BRIDGE-PERSIST-OK: verified=<n> top=<handle> [stv=(s,c)]` · `BRIDGE-PERSIST-WRITE-FAILED: <reason>` (reasons §2.5) · `BRIDGE-PERSIST-REMOVE-UNSUPPORTED: …` (unchanged) · `ARCHIVE-OK`/`ARCHIVE-FAILED` RETIRED.
**Facade errors:** §2.3/§2.5 (all 400/503 bodies `{"error": …}`).
**Receipt-critical invariants:** the `verified=<n>` leading segment preserved (`history_parse.py:119-121` substring match; prompt contract); `top=` always present on OK.
**Gate conditions (v4):** new `H_MISSING`, `H_COUNT_MISMATCH`, `H_MISMATCH` (blocking, D4); `P_MISSING` redefined; `P_UNRESOLVED:<expr12>:<COND>` with `COND ∈ {COMMIT_NOT_IN_REPO, COMMIT_UNREADABLE, COMMIT_NOT_A_LEDGER_COMMIT, COMMIT_TOUCHES_OTHER_FILES, COMMIT_ADDS_NOT_ONE_LINE, ENTRY_PARSE_FAILED, REF_SHA_MISMATCH, NO_PROVENANCE_ATTRS}`; `P_SOURCE_SET_MISMATCH` (informational); `E_NO_INGEST` receipts-only (first case: `window_persist_receipts == 0`); `E_INGEST_ATTESTED_VIA_FACADE_LOG` RETIRED (resolution 6); all `A_*`, `Q_*`, `R_*`, remaining `E_*` unchanged; retired: `P_UNRESOLVED:COMMIT_MULTIPLE_SOURCE_BLOBS`, `INDEX_*`, `BLOB_*`, `URL_MISMATCH` (legacy-only) — plus the full keep/modify/retire audit sweep per Phase 5 item 0.
**Exit codes:** harness `0` PASS / `2` gate FAIL / `1` harness error; `reconstruct_sources.py` `0` all sources resolve / `2` missing-unresolvable / `1` harness error.
**Ledger fields:** `ref`, `sha256`, `entry_date` (exactly three; leading-comma one-element-per-line serialization; +1-line appends; one commit per entry; dedup on `(ref, sha256)`).
**Atom attributes:** `metta_expression`, `provenance_ref`, `provenance_git_commit`, `provenance_blob_sha256`, optional `stv_strength`/`stv_confidence` — top link only; no companion atoms for new writes.
