# write-bridge tools

Standalone operator-side tools for the write-bridge deployment. They run on
the host (over SSH), never inside the container, and are invoked
independently of the pytest suite.

## `migrate_ledger_repo.sh` — verification-only ledger repo format check

Helper for the issue #2 Phase 3 host migration (decision D6: evidence is
never mutated by scripts). It CHECKS the provenance repo format and never
writes, creates or deletes anything — every git invocation is read-only
(`rev-parse` / `log` / `diff-tree`), every file access is a read. The
migration itself is operator-executed per
`docs/issue-2-ledger-migration-runbook.md`.

### Usage

```bash
# over SSH on the OVH host (root owns the repo dir, hence sudo — the
# helper passes -c safe.directory=<repo> per the run_benchmark.py convention)
sudo bash deploy/das/write-bridge/tools/migrate_ledger_repo.sh --check

# non-default locations (e.g. testing against a copy)
bash deploy/das/write-bridge/tools/migrate_ledger_repo.sh \
  --repo /home/ubuntu/omega-provenance --file SOURCE-LEDGER.json
```

### Checks (in order; first failure exits 1)

1. The repo directory exists and is a git repository.
2. `HEAD` exists and touches ONLY the ledger file — or is the init commit
   (init-commit detection: subject exactly `ledger: init` OR empty tree).
3. The ledger file exists and `json.load` parses it as a JSON list.
4. Every element is a JSON object with EXACTLY the keys
   `ref`/`sha256`/`entry_date` (mirrors `provenance_store._ENTRY_KEYS` and
   the entry shape at `provenance_store.py:8`): `sha256` is 64 lowercase
   hex characters, `entry_date` is a non-empty string.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | all checks passed (final line: `OK: ledger repo format verified: …`) |
| `1` | first failed check (see the `FAIL:` line) |
| `2` | usage error (unknown flag or missing flag value) |

Flags: `--check` (default mode; also the default with no arguments),
`--repo PATH` (default `/home/ubuntu/omega-provenance`),
`--file NAME` (default `SOURCE-LEDGER.json`), `--help`.

### Preflight wiring — Phase 5 (NOT yet wired)

`--check` is the preflight `ledger_repo_format` **source of truth**
(spec §6 test strategy, resolution 5 — it replaces the old
`provenance_repo` check, `run_benchmark.py:391-396`, and becomes a
REQUIRED preflight check). **The harness wiring happens in Phase 5**
(spec §8 item 7b); until then this helper is run manually by the operator
(runbook step 6). Unit tests: `tests/test_migrate_ledger_repo.py`.

## `reconstruct_sources.py` — standalone provenance reconstruction (issue #2 Phase 4)

Deterministically reconstructs every trace expression's provenance:
`trace expression -> re-derived top_handle -> mongo link doc ->
custom_attributes -> ledger commit -> ledger entry -> optional
background byte-verify`. It is **standalone and host-side** (over SSH),
with **zero LLM calls and zero pattern-engine queries** — the DAS is
touched ONLY mongo-direct via `docker exec <mongo-container> mongosh`
(the script never joins a DAS bus; spec §0). Same inputs (same
mongo/ledger state) always produce byte-identical JSON and the same exit
code — no timestamps, no random ordering.

The `--facts`/`--handles` cross-check re-derives handles client-side
(metta_to_atoms handles are deterministic type+targets hashes), so it
needs no mongo access. `hyperon_das` is optional: where it is not
installed the script falls back to mirror atom classes with the exact
pinned-client handle formulas (handles identical either way,
live-verified iter16/iter18).

**Phase-0b attribute semantics (live-verified):** re-writing the same
expression with different provenance OVERWRITES the top link's
`custom_attributes` (last write wins per fact handle — iter18/P0b), so
reconstruction always sees exactly one provenance per fact; the script
treats the attribute set as single-valued (no multi-valued resolution
order needed).

### Usage

```bash
# over SSH on the OVH host (root-owned ledger repo -> the script's git
# calls default to sudo, mirroring provenance_check; mongo root creds
# come from the container env, mirroring run_benchmark.py:504-510):

# happy path: trace + FACTS/HANDLES cross-check + background byte-verify
python3 deploy/das/write-bridge/tools/reconstruct_sources.py \
  --trace '(match &self (Inheritance $X (Concept "ceiling")));(Inheritance (Concept "ceiling") (Concept "above-observer"))' \
  --facts '(Inheritance (Concept "ceiling") (Concept "above-observer"))' \
  --handles '<top-handle-from-the-receipt>' \
  --ledger-repo /home/ubuntu/omega-provenance \
  --background-dir ~/low-cost-omega-setup/tests/reasoning-windowless-room/background \
  --case original \
  --json /tmp/reconstruct-original.json \
  --source-paths-out /tmp/reconstruct-original.paths
# -> exit 0; the JSON lists per-expression/per-predicate sources; the
#    .paths file lists one resolved source path per line

# a failing case: a stored fact without provenance attributes
python3 deploy/das/write-bridge/tools/reconstruct_sources.py \
  --trace '(Inheritance (Concept "ceiling") (Concept "above-observer"))' \
  --ledger-repo /home/ubuntu/omega-provenance \
  --json /tmp/reconstruct-fail.json
# -> exit 2; conditions: ["NO_PROVENANCE_ATTRS"]; missing lists the expr

# pre-migration evidence (OPTIONAL, informational only — never in the
# default grade path; resolution 4 / decision D6):
python3 deploy/das/write-bridge/tools/reconstruct_sources.py \
  --trace '…' --ledger-repo /home/ubuntu/omega-provenance \
  --legacy-repo /home/ubuntu/omega-provenance.legacy-<date>
```

Other flags: `--trace-file <path>` (exactly one of `--trace` /
`--trace-file` is required), `--mongo-container <name>` (default
`omega-das-integration-mongodb-1`).

### Classification rules (spec §2.4)

- **(a) stored facts** — ground expressions whose re-derived handle hits
  `db.links`. Each MUST carry ≥1 resolvable source: a stored link without
  provenance attributes (or with an incomplete attribute set — e.g. a
  v1 suffix-less write) is condition `NO_PROVENANCE_ATTRS`, blocking by
  default. Legacy carve-out: with `--legacy-repo` the condition is
  recorded but marked `legacy: true`, informational.
- **(b) query clause** — the FIRST trace step when it is variable-bearing
  (contains a `$` token): exempt (no handle, no sources, no conditions).
- **(c) derivations** — any step containing `=>`: split into component
  atoms (top-level s-expressions of the left + right side, the
  `grading._split_derivation_atoms` convention). Each ground component
  atom gets the full handle→mongo→ledger chain; the derivation's
  `sources` = union of its stored components' sources; variable-bearing
  components are exempt; unstored components (exec/`=>` output atoms are
  typically not written) carry no requirement. `top_handle` for a
  derivation entry is `null`.
- Variable-bearing non-first plain steps → classification `"variable"`,
  exempt. Ground expressions NOT in `db.links` → classification
  `"unstored"`, exempt (the P_MISSING judgment — nothing citable — is
  the harness's, not the script's; an empty trace is vacuously exit 0).

Per-predicate aggregation groups every stored ground expression (and
stored ground derivation components) by the LEADING SYMBOL of the
expression, first-appearance order.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | all used stored facts' sources resolve (vacuously 0 for an empty trace) |
| `2` | some used stored fact's source is missing/unresolvable — any blocking condition, except legacy-informational cases (case FAIL) |
| `1` | harness error: usage error, mongo unreachable, ledger repo unreadable, trace unparseable, internal error |

Usage errors exit **1**, never argparse's default 2 — exit 2 is
RESERVED for case-FAIL semantics.

### Condition codes

Blocking (contribute to exit 2; `P_UNRESOLVED:<expr12>:<COND>` per spec
§2.6) unless the source entry is legacy-informational:

| Code | Trigger |
|---|---|
| `NO_PROVENANCE_ATTRS` | stored link doc without a complete `(provenance_ref, provenance_git_commit, provenance_blob_sha256)` attribute set |
| `COMMIT_NOT_IN_REPO` | cited commit absent from the ledger repo (`git cat-file -e <sha>^{commit}` fails) |
| `COMMIT_UNREADABLE` | `git show` of the cited commit fails |
| `COMMIT_NOT_A_LEDGER_COMMIT` | commit's changed paths do not include `SOURCE-LEDGER.json` |
| `COMMIT_TOUCHES_OTHER_FILES` | commit touches `SOURCE-LEDGER.json` plus other files |
| `COMMIT_ADDS_NOT_ONE_LINE` | the commit's ledger diff does not add exactly one entry-shaped line (e.g. the init commit, or a two-entry append) |
| `ENTRY_PARSE_FAILED` | the single added line is not a valid `{ref, sha256, entry_date}` entry (bad JSON, wrong keys, non-hex sha256) |
| `REF_SHA_MISMATCH` | the entry's `(ref, sha256)` ≠ the atom's attributes, or `--background-dir` byte-verify failed (content drift — the ledger's hash does not match the actual source bytes) |

JSON-only (never affect the exit code — decision D4; the harness maps
them to blocking gate conditions):

| Code | Trigger |
|---|---|
| `H_MISSING` | `--facts` given (non-empty) and `--handles` absent/empty |
| `H_COUNT_MISMATCH` | claimed handle token count ≠ FACTS expression count (pairs still compared over the shorter length) |
| `H_MISMATCH` | an aligned claimed handle ≠ the re-derived `top_handle` (an unparseable facts expression derives `null` → any claim for it mismatches) |

`--background-dir` byte-verify: for each resolved source the script
looks for `<background-dir>/<ref tail>` (URL refs, the
`url.rsplit("/",1)[-1]` convention; absolute-path refs use the path
itself under the background dir); a missing file SKIPS the check (no
condition, `background_file`/`background_match` stay `null`), a hash
mismatch is `REF_SHA_MISMATCH` (blocking).

`--legacy-repo` semantics (OPTIONAL — informational only; resolution 4):
if a stored expression's ledger chain fails at `COMMIT_NOT_IN_REPO`
(its commit predates the migration) and `--legacy-repo` is given, the
OLD chain (sources/ blob + index.jsonl, the standalone
`provenance_check.py` resolver) is attempted; on success the source is
`"resolved": true, "legacy": true` — never blocking, never contributing
to exit 2. With `--legacy-repo` a stored link with NO provenance
attributes gets `NO_PROVENANCE_ATTRS` recorded but marked
`legacy: true` (pre-migration atoms carried provenance in companion
atoms, not custom_attributes). If legacy resolution fails, the primary
ledger condition stands (blocking). Legacy-resolved sources do not run
the background byte-verify; their `source_paths` entry is the ref
itself. The harness's default grade path never passes `--legacy-repo`.

### Output

Human summary on stdout always; full JSON to `--json <path>` with
`per_expression` / `per_predicate` / `handles_check` / `missing` /
`conditions` / `source_paths` (+ `case` when `--case` given) — shape per
spec §2.4. `--source-paths-out` writes the resolved source paths, one
per line (the harness byte-compare input): the background file path
when `--background-dir` was given and the file exists, else the ref
itself.

Tests: `tests/reasoning-windowless-room/unit/test_reconstruct_sources.py`
(stdlib shim, no docker/hyperon_das needed) and
`deploy/das/write-bridge/tests/test_reconstruct_integration.py`
(bridge pytest image).
