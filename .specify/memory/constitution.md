# Low-Cost Omega Setup Constitution

> **Normative-source rule (Balazs, 2026-10-27):** on any disagreement between SDD artifacts (constitution/spec/plan/tasks) and `docs/issue-2-implementation-spec.md`, the implementation-spec document is the normative reference. This constitution summarizes it; it never overrides it.

## Core Principles

### I. Config-Driven Only (NON-NEGOTIABLE)
No modification to upstream DAS or Omega source. Everything is config-driven: the `das-write` plugin (`deploy/omega/plugins/das-write/`, `:ro`-mounted via `deploy/omega/plugins.yaml.overlay`) intercepts `&persistent`; the write-bridge facade is a compose service (`deploy/das/write-bridge/`). (Implementation spec §0.)

### II. Direct-Verification Evidence (NON-NEGOTIABLE)
The load-bearing evidence is the direct verification of the MeTTa reasoning trace leading to the answer — per Balazs 2026-10-27 22:37 UTC: "I care about the direct verification evidence of the MeTTa reasoning trace leading to the answer". Deterministic, replayable chains (the reconstruction handle chain, the R-gate's executed-trace evidence) are trusted; log-census attestation crutches are retired with the v4 design. (Implementation spec §2.6 design principle, §11 resolution 6.)

### III. Fire-and-Forget Writes + Mandatory Read-Back
`add_atoms`/`delete_atoms` are fire-and-forget; every write is verified by read-back of the fact's links (200 `{handles, verified, missing, top_handle}`). Handles are deterministic (type+targets hash, `deploy/das/write-bridge/write_client.py:60-63`); `custom_attributes` never change identity/dedup. Custom-attribute persistence is best-effort — a dropped attribute surfaces at reconstruction (case FAIL), not as a write failure. (Implementation spec §0, §1, §11 residual risk 3.)

### IV. Handle Determinism (`_id` = Handle)
Mongo link/node documents are keyed `_id` = handle; the provenance spine is the deterministic handle chain (trace expr → `parse_fact` → `top_handle` → `db.links.find({_id: handle})` → `custom_attributes.provenance_git_commit` → ledger commit → one-line diff → `(ref, sha256)`). The reconstruction script never joins a service bus — mongo-direct only. (Implementation spec §0, §1, §2.4.)

### V. Agent Transparency
The agent is never aware of provenance tracking: no shas, no provenance bookkeeping, no git tokens in its grammar. Provenance is custom-attribute-primary; the agent only writes the v3 grammar `(add-atom &persistent <expr> "<ref>" [(stv s c)])` and copies handles verbatim from receipts (`BRIDGE-PERSIST-OK … top=` / `DAS_RETRIEVE_OK … results=`) into the `HANDLES:` line. (Implementation spec §1, §2.1, §2.7, §8 item 10.)

### VI. Ledger-Only Provenance Anchors
`SOURCE-LEDGER.json` (fresh single-file git repo, one array element per line, leading-comma +1-line-append form pinned, exactly three fields `ref`/`sha256`/`entry_date`); one commit per new entry; dedup on `(ref, sha256)` returns the original commit; the commit hash is the provenance anchor. Source content is NOT archived (D1, owner-accepted). (Implementation spec §2.2, §10.)

## Additional Constraints (Hard Bounds)

- Facade is egress-free: zero outbound HTTP; 16 KiB write-body cap (`app.py:14`); the plugin is the ONLY component that fetches URLs / reads container paths.
- Two disjoint service buses (atomdb vs pattern query); a mis-routed atomdb command crashes the query engine.
- History channel collapses tool results to `$_` — record files + receipts + the query-side docker-log attestation lane remain load-bearing.
- 2048-char cap applies to the expression only; ref ≤ 480 chars, no whitespace.

## Development Workflow

- **Commit discipline:** every commit carries subject prefix `issue-2:` AND trailer `Refs #2`; commits are small and elementary (one logical change each, mapping 1:1 to spec phases/sub-phases; phase tests land with the phase commit); `Closes #2` only when all phases are green + live e2e 3/3 PASS. Push to the `ktfh-claw` fork remote ONLY — never upstream. (Implementation spec §14.)
- **Testing:** write-bridge pytest suite (`deploy/das/write-bridge/tests/`), windowless-room unit suite (`tests/reasoning-windowless-room/unit/`), das-write plugin suite (`deploy/omega/plugins/das-write/tests/`); live probes are one-off scripts excluded from the pytest registry.
- **Phasing:** phases 0-8 in implementation-spec order; each phase states its acceptance criteria and test strategy — the phase gates are the workflow gates.

## Governance

- On any disagreement between SDD artifacts and `docs/issue-2-implementation-spec.md`, the implementation spec is normative (per Balazs, SDD execution note §SDD addendum + this constitution's normative-source rule).
- Amendments to this constitution require documentation, owner approval, and migration notes; implementation decisions D1-D7 are RESOLVED (approved as defaulted, Balazs 2026-10-27 22:37 UTC) and may not be reopened without owner direction.

**Version**: 1.0.0 | **Ratified**: 2026-10-27 | **Last Amended**: 2026-10-27
