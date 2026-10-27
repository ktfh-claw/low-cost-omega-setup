# Implementation Plan: Transparent Provenance (Issue #2)

**Branch**: `issue-2-transparent-provenance` | **Date**: 2026-10-27 | **Spec**: `specs/002-transparent-provenance/spec.md`

**Input**: `docs/issue-2-implementation-spec.md` (v4) — **NORMATIVE on any disagreement with SDD artifacts** (per Balazs). `§N` citations below refer to that document.

**Note**: This plan maps 1:1 to the implementation spec's phases 0-8 in its exact order; file lists and function-level behavior are pulled from the phase sections (§3-§13). Do not re-order or re-invent.

## Summary

Provenance becomes custom-attribute-primary with a fresh single-file `SOURCE-LEDGER.json` git repo as the anchor: the v3 write grammar (`(add-atom &persistent <expr> "<ref>" [(stv s c)])`, ref mandatory, no agent fingerprint, no git sha), the das-write plugin resolves refs / computes sha256 / ledger-appends via the facade, `/v1/write` gains a pre-write citation gate and `top_handle`, a standalone mongo-direct reconstruction script is the provenance gate, and the benchmark harness gates on reconstruction output + a new `HANDLES:` cross-check line. The agent is never aware of provenance tracking (implementation-spec §1 data flow).

## Technical Context

**Language/Version**: Python 3 (facade, plugin, harness, tools); MeTTa skill clause (das-write.metta); bash (migration helper); git CLI (ledger repo); mongosh via `docker exec`.

**Primary Dependencies**: existing write-bridge facade (Flask-style app.py + runner), das-write plugin (`das_write_bridge.py`), existing pytest suites + conftest registries; NO new third-party deps.

**Storage**: mongo (atomdb links keyed `_id` = handle) + the ledger git repo (host `/home/ubuntu/omega-provenance`, container `/var/lib/omega-provenance`, env `WRITE_PROVENANCE_REPO` — compose.write-bridge.yaml:67,71); `SOURCE-LEDGER.json` single file.

**Testing**: pytest — write-bridge suite (`deploy/das/write-bridge/tests/`), windowless-room unit suite (`tests/reasoning-windowless-room/unit/`, registry `run_tests.py`), plugin suite (`deploy/omega/plugins/das-write/tests/`); e2e = the harness `full` flow on the OVH host.

**Target Platform**: Linux (OVH host, docker compose); agent container (`:ro`-mounted plugin overlay).

**Project Type**: config-driven deployment repo (no upstream DAS/Omega source changes — constitution I).

**Performance Goals**: bounded fetch ≤2 MB / ≤20 s; plugin cache makes subsequent same-source writes 1 POST; reconstruction = ONE bounded `find({_id: {$in: [...]}})` per run.

**Constraints**: facade egress-free, 16 KiB write-body cap; two disjoint service buses — reconstruction never joins a bus (mongo-direct); history channel collapses tool results to `$_` (receipts + record files load-bearing).

**Scale/Scope**: phases 0-8; ~3 test suites; one live 3-case benchmark run; ledger = one line + one commit per unique `(ref, sha256)`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- I. Config-driven only: all changes under `deploy/` (plugin/bridge, `:ro` overlay wiring unchanged) and `tests/` — PASS.
- II. Direct-verification evidence: reconstruction script + R-gate are the load-bearing evidence; log-census ingest attestation retired (resolution 6) — PASS by design.
- III. Fire-and-forget + mandatory read-back: `/v1/write` 200 `{handles, verified, missing, top_handle}`; custom-attribute persistence best-effort, detected at reconstruction — PASS.
- IV. Handle determinism: provenance spine = deterministic handle chain; mongo-direct only — PASS.
- V. Agent transparency: no shas/bookkeeping in the grammar; handles copied verbatim from receipts only — PASS.
- VI. Ledger-only anchors: `SOURCE-LEDGER.json`, one commit per entry, dedup on `(ref, sha256)` — PASS.
- Commit discipline (§14): `issue-2:` prefix + `Refs #2` trailer, elementary commits, fork-only push — enforced across all phases.

## Project Structure

### Documentation (this feature)

```text
specs/002-transparent-provenance/
├── spec.md              # Requirements decomposition (this feature's SDD spec)
├── plan.md              # This file
└── tasks.md             # Phase-ordered checklist
```

### Source Code (repository root)

```text
deploy/das/write-bridge/
├── provenance_store.py        # Phase 1: LedgerStore REWRITE
├── app.py                     # Phase 1: /v1/source, /v1/write v4, /v1/archive deleted
├── write_client.py            # Phase 1: v4 decoration, top_handle, companion deletion
├── README.md                 # Phase 1: endpoint/attr docs
├── tools/
│   ├── migrate_ledger_repo.sh # Phase 3: verification-only helper (--check)
│   ├── reconstruct_sources.py # Phase 4: standalone reconstruction script
│   └── README.md              # Phase 4: usage/classification/exit codes
└── tests/
    ├── iter18_probe_mongo_attrs.py  # Phase 0: live probe (+ result note)
    ├── test_provenance_store.py     # Phase 6: REWRITE
    ├── test_app.py                  # Phase 6: EXTEND
    ├── test_write_client.py         # Phase 6: EXTEND
    └── test_reconstruct_integration.py  # Phase 6: NEW

deploy/omega/plugins/das-write/
├── das_write_bridge.py        # Phase 2: v3 grammar + resolver + sha256 + cache + receipt
├── das-write.metta           # Phase 2: archive-source clause removed, description v3
├── README.md                  # Phase 2: v3 contract
└── tests/
    ├── test_provenance_suffix.py   # Phase 6: EXTEND to v3
    └── test_das_write_bridge.py    # Phase 6: EXTEND to v3 (archive_source cases deleted)

deploy/omega/plugins/das-read/
└── das-read.metta             # Phase 5 item 10: handles clause in skill description only

tests/reasoning-windowless-room/
├── grading.py                 # Phase 5: E_NO_INGEST, P/H wiring, gate audit
├── run_benchmark.py           # Phase 5: preflight v4, attestation lanes, cleanup N1+N3, P-gate invoke
├── history_parse.py           # Phase 5: retire extract_archive_receipts/add_atom_shas from v4 path
├── agent_prompt_template.md   # Phase 5: slim prompt + HANDLES line + top= record line
├── GATES-REFERENCE.md         # Phase 5 item 9: gate-audit table + H-gate section
├── test-spec.md               # Phase 5 item 9: version + history entry
├── provenance_check.py        # Phase 8: kept standalone unwired (legacy --legacy-repo fallback)
└── unit/                      # Phase 6: test suite rewrites/extensions (see tasks.md)

docs/
└── issue-2-ledger-migration-runbook.md  # Phase 3: operator runbook (NEW)
```

**Structure Decision**: existing repo layout preserved; no new top-level dirs; the feature docs live under `specs/002-transparent-provenance/` per the specify convention.

## Phase Map (implementation-spec order — DO NOT RE-ORDER)

- **Phase 0 — live probes** (§3): `deploy/das/write-bridge/tests/iter18_probe_mongo_attrs.py` + result notes (P0a mongo `_id`/attribute visibility; P0b attribute-overwrite semantics). Probes are one-off scripts, excluded from the pytest registry; findings become fixtures/assumptions for Phase 1/4 tests. No repo behavior change.
- **Phase 1 — facade** (§4): `provenance_store.py` (LedgerStore REWRITE: keep `ArchiveError` + flock/git conventions; delete `archive()`, `lookup()`, subject parsing, `_validate_url`); `app.py` (`/v1/source` route; delete `/v1/archive` + `MAX_ARCHIVE_BODY_BYTES`; `/v1/write` v4 provenance keys + ledger gate + `top_handle`); `write_client.py` (`_validate_provenance` v4; `_decorate_top_link` attr set; DELETE `_provenance_expression` + companion emission; `write()` returns `top_handle`; read-back covers fact links only); `README.md`. Depends on D1, D2, D6.
- **Phase 2 — plugin** (§5): `das_write_bridge.py` (`_parse_suffix` v3 with `git:` rejection + roots check; `_resolve_source`; sha256; per-process cache; two-call flow; `top=` receipt; DELETE `archive_source()` + `ARCHIVE_PATH`); `das-write.metta` (archive-source clause removed; v3 description); `README.md`; optional `dasWriteSourceRoots` config (no other Omega config keys). Depends on D3, D5, D7.
- **Phase 3 — migration runbook** (§6): `docs/issue-2-ledger-migration-runbook.md` + `deploy/das/write-bridge/tools/migrate_ledger_repo.sh` (verification-only, `--check` mode: repo exists, HEAD touches only SOURCE-LEDGER.json or is init commit, `json.load` is a list, 3-key entries). Operator-executed over SSH; bundle + tar backups; fresh init at the SAME host path; sequencing rule with the plugin redeploy. Depends on D1, D6.
- **Phase 4 — reconstruction script** (§7): `deploy/das/write-bridge/tools/reconstruct_sources.py` + `tools/README.md` (classification rules, exit codes, examples, Phase-0b attribute-semantics note). Imports `metta_to_atoms` from the bridge dir; grader-helper semantics (`normalize_expression`, `_split_derivation_atoms`, `parse_reasoning_trace`); ONE bounded mongo `find`; `--legacy-repo` optional-informational only; `--source-paths-out` for the harness byte-compare. Depends on D4, D1/D6.
- **Phase 5 — benchmark rewiring** (§8, items 0-10): gate-condition audit (item 0, full keep/modify/retire table in `GATES-REFERENCE.md`); prompt slim (item 1); `E_NO_INGEST` receipts-only (item 2); attestation census drop (item 3); P-gate from reconstruction (item 4); HANDLES gate (item 5); `history_parse` retirements (item 6); preflight full-v4 adaptation (item 7); cleanup N1 `$or` + N3 sweep (item 8); docs (item 9); das-read handles clause (item 10 — description only, NO engine/proxy changes). Depends on D3, D4, D5, D7, D2.
- **Phase 6 — tests per component** (§9): write-bridge suite (REWRITE `test_provenance_store.py`; EXTEND `test_app.py`, `test_write_client.py`; NEW `test_reconstruct_integration.py`); windowless-room unit suite (NEW `test_reconstruct_sources.py`, `test_handles_gate.py`, `test_v17_prompt.py`; REWRITE pinned prompt tests; EXTEND grading/gate/history fixtures; UNCHANGED `test_provenance_check.py`, `test_facts.py`, `test_v15_judge.py`, `test_v4_levers.py`); plugin suite (EXTEND both modules, delete archive_source cases).
- **Phase 7 — live e2e validation** (§12): operator/SSH on the OVH host; rebuild write-bridge, redeploy plugin overlay, migration executed; sequential `full` flow for ALL 3 cases; root-cause classification (agent/harness/bridge/environment) with evidence for EVERY failure; baseline `wr3n-20261026` (0/3, commit `6684f4f`); iterate until 3/3 PASS or genuine external blocker.
- **Phase 8 — repo asset review** (§13): candidate list items 1-7 (incl. `deploy/omega/das-read/` duplicate + `start.sh:24` fallback mount removal in one commit; `test_provenance_app.py` absorbed into `test_app.py`; iter5/6/6b/7/8/11 probe retirement; KEEP `iter16_groundtruth.js` + `iter16_probe.py`); each removal its own elementary commit with rationale; grep-verify nothing load-bearing references removed assets. Depends on D1, D2, D7.

**Commit sequence** per §14: docs first (done, `8428fde`), then Phase 0 probe scripts → Phase 1 elementary sub-commits (LedgerStore+tests; /v1/source+/v1/archive deletion+/v1/write v4 gate+tests; write_client decoration+tests) → Phase 2 → Phase 3 → Phase 4 → Phase 5 → asset-removal commits → results/evidence commits. Every commit: `issue-2:` prefix + `Refs #2` trailer; `Closes #2` only at 3/3 PASS.

## Complexity Tracking

> No constitution violations to justify — the design is a reduction (fewer plugin branches, companion atoms dropped, one census lane kept of two).
