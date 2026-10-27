# Iteration-18 probe results — issue-2 Phase-0 live verification

**Run:** 2026-10-27 23:28-23:29 UTC, live OVH deployment (`/home/ubuntu/low-cost-omega-setup/deploy/das/write-bridge`, md5-verified against repo HEAD 2de1ef4 before the run). Probe scripts: `iter18_probe_mongo_attrs.py` (write + cleanup modes, drives `DasWriteRunner` directly per spec §3), `iter18_groundtruth.js` (host-side mongosh inspection). Raw logs: `memory/issue-2-transparent-provenance/logs/iter18/` (workspace).

Canary: `(Inheritance (Concept "omega-bridge-canary-20261027-iter18") (Concept "write-bridge-test-20261027-iter18"))`, top link `53db949169a33d28dbb84f07df4fdcf8`.

## P0a — mongo `_id` = handle; v4 attributes persist; invisible to pattern answers — CONFIRMED

- Write A (v4-shaped top-link decoration: `metta_expression`, `provenance_ref`, `provenance_git_commit`, `provenance_blob_sha256`): `add_atoms` of 7 atoms, structural read-back `verified: true, missing: []`; handles identical to the deterministic pre-parsed set (`same_handles_as_parsed: true`).
- Read-proxy query of the canary: 200, 1 answer, `handles: [<top_link>]`, assignment only — **no custom_attributes leak into pattern answers** (they ride link docs only; mongo is THE provenance channel).
- mongosh ground truth: `db.links.findOne({_id: topLink})` → doc exists, `targets` = [leading-symbol, node, node] handles, `custom_attributes` = exactly `{"provenance_blob_sha256": "ddd…", "provenance_git_commit": "cccc…", "provenance_ref": "https://example.invalid/iter18-source-b.md", "metta_expression": "(Inheritance …)"}`.
- `docsWithProvRef: [<top_link>]` — decoration lands on the TOP link doc ONLY (sub-links clean). Unique nodes present (2); symbol node checked by name.

**Live-verified:** link docs keyed `_id` = handle; the v4 attribute set persists through the pinned server's `add_atoms`; pattern answers carry handles only.

## P0b — re-write semantics = OVERWRITE (last write wins) — CONFIRMED

- Same expression re-written with PROV_B (same deterministic handles, distinct ref/commit/sha): `verified: true`.
- mongosh inspection AFTER write B: `custom_attributes.provenance_ref` = PROV_B's URL, `provenance_git_commit` = "cccc…", `provenance_blob_sha256` = "ddd…"; **exactly one value per attribute** (`provRefCount: 1`) — no merge, no append, no array. The second `add_atoms` **overwrites** the top-link document's `custom_attributes`.
- Consequence (per spec §3 P0b branch): document that the LAST write wins per fact handle. Benchmarks unaffected (cleanup removes cross-run residue). The Phase-4 reconstruction script may treat the attribute set as single-valued — no multi-valued resolution order needed. Spec branch "merge/append" is CLOSED.

## Cleanup — zero residue — CONFIRMED

- Default cleanup oracle: `absent: true` in 5.5 s (1 check, 0 s standby), 3 Expression links deleted.
- Explicit unique-node deletion: 2 nodes, `absent: null` (bare nodes invisible to patterns, expected).
- Read-proxy re-query: 200, 0 answers. mongosh: canary links 0, canary nodes 0; totals back to baseline (links 4690, nodes 3321 — delta = 3 links + 2 nodes exactly).

## Findings encoded for later phases

- **Phase 1 facade** (§4): no behavioral surprises to design around; `top_handle` is stable across re-writes and can be threaded into the response.
- **Phase 4 reconstruction** (§7): `db.links.find({_id: <handle>}).custom_attributes` is single-valued per attribute; the deterministic handle chain spine holds live.
- **Spec docs need no update** (both P0a/P0b confirmed the assumed behavior; the P0b merge/append contingency is moot).
