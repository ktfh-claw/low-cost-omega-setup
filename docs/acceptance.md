# Consolidated end-to-end acceptance record — omega-das-bridge (Phase 4)

**Status: ACCEPTED 2026-10-20 09:12 UTC** (Phase-4 close-out evidence, iteration 16).
This document consolidates the campaign's live acceptance evidence into one
reproducible record. The Google Doc §16 is the authoritative mirror for
Balázs; this file is the in-repo record. From-scratch reproduction commands:
[`docs/runbook.md`](runbook.md).

## A. End-to-end acceptance loop (write → verify → read → cleanup → zero residue)

**Definition of green** (all phases must pass in one run, on the deployed
services, from the deployment tree md5-verified against repo HEAD):

| Phase | Check | Green means |
|---|---|---|
| PHASE1 | `POST /v1/write {"metta": <canary>, "verify": true}` via the deployed write-bridge | HTTP 200, `verified: true`, `missing: []`, deterministic handles |
| PHASE2 | metta-mode variable query via the deployed read-proxy | HTTP 200, `mode: "metta"`, the fresh fact returned |
| PHASE3 | `cleanup()` with shipped defaults (links-only + absence oracle) | `absent: true` (oracle verdict, in-window) |
| PHASE4 | explicit unique-node deletion | unique canary nodes deleted (`absent: null` by design) |
| PHASE5 | metta re-query | HTTP 200, **0 answers** |
| PHASE6 | mongo ground truth (db `das`) | canary links/nodes 0; shared symbols + E1 canary intact; totals 1864/3710 unchanged |

**Three consecutive green runs** (identical probe shape, run-to-run
comparability):

| Run | UTC | PHASE1 | PHASE2 | PHASE3 oracle | mongo ground truth |
|---|---|---|---|---|---|
| iter7-a1 | 2026-10-20 02:22 | verified true, 4.27 s | metta read 1.29 s | **absent: true, first pass** (checks 1, standby 0.0, 5.31 s) | zero residue, totals unchanged |
| iter8-a1 | 2026-10-20 02:41 | verified true, 4.1 s | metta read 1.27 s | **absent: true, first pass** (checks 1, standby 0.0, 5.18 s) | zero residue, totals unchanged |
| iter16-a1 | 2026-10-20 09:12 | verified true, 4.15 s | metta read 1.30 s | **absent: true, first pass** (checks 1, standby 0.0, 5.4 s) | zero residue, totals unchanged |

iter16-a1 detail (canary `omega-bridge-canary-20261020-iter16`, probe
`deploy/das/write-bridge/tests/iter16_probe.py`, suite 123 passed re-run on
the synced tree immediately before):

- PHASE1: 7 deterministic handles; links `9c42e9db…`, `aa215395…`,
  `46c7b670…`; `verified: true`, `missing: []` (4.15 s).
- PHASE2: `mode: "metta"`, count 1, assignment binds `$_1` → inner link
  handle (1.30 s).
- PHASE3: deleted all 3 links; **absent: true, checks: 1, standby 0.0 s**
  (5.4 s) — the oracle stayed first-pass-correct across all three runs.
- PHASE4: unique nodes `9677d6b5…`, `fbb7253b…` deleted.
- PHASE5: 0 answers (1.37 s).
- Mongo (09:15 UTC): canaryLinks 0, uniqueNodes 0, symbolInheritance 1,
  symbolConcept 1, e1CanaryLink 1, **nodesTotal 1864 / linksTotal 3710
  unchanged** → zero residue.

Unit suite on the pinned upstream client (`e12573cc`): **123 passed**
(re-run 2026-10-20 09:11 UTC on the OVH synced tree before iter16-a1).

## B. Component acceptance (consolidated)

### B1. Read proxy (MeTTa-mode + structural) — live since iteration 2

- MeTTa-mode (`use_metta_as_query_tokens`, correctly-spelled key set
  client-side — upstream python client sends `user_metta_as_query_tokens`,
  typo live-confirmed at `48507929`): variable-form queries complete in
  ~1.3 s; ground metta patterns return 0 answers in this engine build
  (checks stay structural/variable-form — documented).
- Structural variable-form queries: live-green throughout.
- Ground metta/structural patterns never complete on the pinned engine
  (QE answers `Invalid`, hangs to client timeout) — the proxy rejects them
  fast with guidance.

### B2. Write bridge (service + client) — live since iteration 5

- Compose service `omega-das-write-bridge-write-bridge-1` on the internal
  client network only; read-only rootfs, cap_drop ALL, no-new-privileges.
- `add_atoms` is fire-and-forget upstream → **read-back verification is
  mandatory** and on by default (`verified: true` on every canary of the
  campaign, 4.1–5.0 s).
- Handles are deterministic (pinned-client hashing): client-computed ==
  server-stored, live-verified.
- Known upstream defects worked around at the bridge (all live-verified;
  drafts in `docs/contributions/`): QE crash on mis-routed `atomdb`
  commands (invariant 2); python-client parameter typo; nested handle
  vector mis-decode; `abort()` list-vs-dict.

### B3. Cleanup + absence oracle — stable since iteration 7

- Links-only default (shared-DB safety: live-measured 421/791 links target
  the shared `Inheritance`/`Concept` symbols); unique-node deletion is an
  explicit zero-residue step.
- Deletion apply is **eventual and loop-coupled** (iters 3–6 matrix: every
  polled grace window 30/90/300 s false-alarmed while every deletion
  landed; light-traffic absence at T+7.8 s). The oracle (alternate-pattern
  verification + bounded query-free standby) turned this into
  **first-pass-correct verdicts in 3/3 runs**.
- A persistent `absent: false` after the bounded re-checks means the delete
  genuinely did not land — re-run/investigate.

### B4. Thin import wrapper — Phase 2, live-validated iterations 9–10

- Real history (`sha256 f71cfb47…`, 26,556 lines): 8,285 entries, **8,216
  emitted = 99.17% ≥ 99% target**; 69 skipped (50 shell-quirk residuals +
  19 bare-angle, both upstream parser defects — drafts filed); 199 prose.
- Load into scratch mongo via stock `db_loader --skip-redis`: STEP 1/1
  100% (33,231/33,231), exit 0.
- Ground truth: **atom_types = 0** (the `(:`-ascription pollution defect
  was found and removed — 16,455 junk atom_types on the polluted load);
  nodes 25,789 / links 20,752; **exactly one ground `CampaignProvenance`
  link per emitted entry** (8,216), payloads exact.
- Unit suite: 33 passed + 3 skipped (no network).

### B5. Omega plugin `das-write` (`&persistent` hook) — Phase 2, iteration 11

- Config-only plugin validated in a **test container only** (stock image
  `omegaclaw:das-f38217f`, never the live agent):
  - Enabled path (`dasWriteEnabled=1`): plugin loads via the stock loader,
    `(add-atom &persistent <canary>)` → `BRIDGE-PERSIST-OK: verified=7`
    (write-bridge POST 200 + mandatory read-back); hook-written canary
    read back through the deployed read-proxy (1.32 s); oracle cleanup
    first-pass absent; mongo zero residue, totals unchanged.
  - Disabled path: plugin loads, logs bridging disabled, **zero bridge
    statuses and zero write-bridge POSTs** — stock behavior unchanged.
  - Stock fall-through intact (`(* 6 7)` → `42`); single-definition
    invariant; `remove-atom &persistent` → truthful
    `BRIDGE-PERSIST-REMOVE-UNSUPPORTED`.
- Suite: 58 passed locally.
- **Live-agent validation (iteration 22, 2026-10-20 12:01–12:05 UTC,
  explicitly approved restart):** agent restarted with the plugin mounted
  (`dasWriteEnabled=1`); loader logged the enabled line; first two
  autonomous findings persisted live via `&persistent` —
  `BRIDGE-PERSIST-OK: verified=7` (FetchCoder-V2 → FetchAI-product) and
  `verified=8` (released-date Evaluation) — both facade POST 200 with
  read-back; mongo: handles present, `atom_types` 0, canaries + prior
  imports intact, totals 1864/3710 → 1868/3716 (cumulative, zero
  residue). Evidence: `memory/omega-das-bridge/evidence/iter22-live/`.

### B6. Upstream contribution ladder — Phase 3, fork-local drafts only

- 5 issue drafts re-validated against upstream `48507929` (iteration 12).
- Draft branches pushed to the ktfh-claw forks, nothing filed upstream:
  - `ktfh-claw/das` `fix/python-client-metta-typo` @ `067fc8e1` (iter 12)
  - `ktfh-claw/das-metta-parser` `fix/lexer-bare-angle-symbols` @
    `4687c8c` (iter 13; 3 commits, orchestrator-validated incl.
    master-baseline contrast)
- das-toolbox lane archived (full-history bundle, restore-tested) and the
  fork reset to a clean upstream mirror @ `928edfc` (iter 14).
- Docs-guide draft "Writing atoms from external agents" complete
  (iteration 15; every command/API fact re-verified against `48507929`).

## C. From-scratch reproducibility

- [`docs/runbook.md`](runbook.md) covers the full lane (steps 0–7) with the
  live-verified image digests, the four broker invariants, the compose-run
  node-id rule, the canary procedure, and the acceptance loop.
- Deployment tree = repo checkout (`~/low-cost-omega-setup/` on OVH);
  repo↔deployed md5 parity was verified before iter16-a1 (5 core files).
- Ops caveat recorded: the pre-iter-7 flat tree at `~/omega-das-bridge/`
  is a stale leftover — deploy only from the repo checkout.

## Acceptance verdict

The omega-das-bridge (Path B) campaign is functionally complete and
accepted on the deployed OVH services: three consecutive green end-to-end
loops (A), all component lanes live-validated (B1–B5), upstream
contributions drafted fork-locally (B6), and a from-scratch runbook (C).
Outstanding by design: (1) ~~live Omega-agent restart~~ — **executed
2026-10-20 12:01 UTC** under explicit approval, live evidence recorded
(iteration 22; the plugin now runs attached to the live agent);
(2) filing any draft upstream — gated on explicit approval;
(3) the two decision-gated issue drafts (QE-crash robustness, delete-apply
ack) remain drafts.

Evidence: `memory/omega-das-bridge/evidence/iter{2..8,9,10,11,12,13,16}-probe/`
plus `evidence/iter22-live/` (live-agent restart + first live writes);
gateway workspace; per-iteration details in [`docs/status.md`](status.md).
