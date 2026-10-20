# Live status — omega-das-bridge campaign

Main reporting interface: [Google Doc — Omega-DAS Integration Re-evaluation Report](https://docs.google.com/document/d/1Pw5diOmac40Abc8_D1CG0_b3OrOHntq1BSzOv2H63dM/edit) (§16+ = execution campaign). This page mirrors it per iteration.

## Current phase: Phase 1 — Bridge core (config-only, live on OVH) — canary loop DONE, sign-off pending

## Iteration log

### Iteration 1 — 2026-10-19 21:59–22:30 UTC — Bootstrap ✅
- **Directive received** (Balázs, Discord voice, 21:59 UTC): execute Path B; this repo = bridge repo; clean it first; sync repos; OVH = dev environment; 30-min cron; Google Doc = main reporting interface; fork-only drafts; single branch.
- **Live state verified:** OVH DAS stack (mongo/redis healthy, attention-broker, query-engine, read-proxy) + atomdb-broker + scratch mongo all Up; Omega agent container stopped+disabled (pause holding, per 08:11 UTC directive).
- **Repo sync (upstream):** `das` e12573cc → 48507929 (+66, fast-forward, pushed to ktfh-claw fork); `das-toolbox` master = upstream (0 behind); `das-metta-parser` fork **created** (ktfh-claw) and pushed @19022d2; `das-proto` present locally.
- **Bridge repo cleanup:** `artifacts/` → `historical/` (provenance preserved); superseded **operator-DAS-import runbook removed** (the outdated operator-gated write lane doc, per directive); stale branch `docs/omega-das-direct-write` **deleted** (verified ancestor of main, zero-delta); stale worktree removed.
- **Campaign docs created:** README (bridge repo charter), `docs/architecture.md` (Path B design), `docs/campaign-plan.md` (phases/acceptance), `docs/contributions/README.md` (ladder + fork status), this status page, runbook stub.
- **Google Doc:** re-opened as live progress doc; §16 "Execution campaign" appended with directive, plan, iteration-1 entry, repo/fork links.
- **Cron:** `omega-das-bridge-30m` activated (30-min isolated agentTurn; disabled at pause points, removed at close-out).
- **GitHub:** bridge repo pushed: https://github.com/ktfh-claw/low-cost-omega-setup (main @ 975518e) — links recorded in the doc.
- **Overlay + deployment set added** (Balázs follow-up 22:06 UTC): full Omega config overlay (`deploy/omega/config-overlay.yaml`, verbatim from the live OVH campaign), `start.sh`, systemd unit, `runtime.env.example` (keys only), plus the DAS side (`deploy/das/`: digest-pinned compose, config template + render scripts, bounded read proxy, ops scripts) → [commit 8f0f666](https://github.com/ktfh-claw/low-cost-omega-setup/commit/8f0f666). Secrets excluded; pre-bridge DAS README preserved in `historical/`.
- **Next (iteration 2):** Phase 1 start — read-proxy MeTTa-mode config wrapper + `das-write` skill v1 skeleton; spawn coder-opencode for the python-client wrapper module.

## Evidence pointers

- Re-eval campaign report + evidence: `memory/omega-das-integration-reeval/` (state.md 22 ticks, final-assessment, coder reviews), `omega-das-reeval-report/report.md`.
- Live experiments E1–E3 (broker write, parser matrix, typo repro): re-eval report §7; state.md ticks 2–3.
- Fork states: das @48507929 (upstream parity), das-toolbox @a193af4 (+14 lane commits, retiring), das-metta-parser @19022d2.

### Iteration 2 — 2026-10-19 23:32–23:57 UTC — Phase 1 core: read-proxy MeTTa-mode + write-bridge v1, live-probed (2 defects found & fixed; unit tests staged) 🔧
- **Recovered from timeout:** the 23:07 iteration died at the 25-min cron limit mid-verification, leaving work uncommitted. This iteration completed it: shipped proxy update verified live (container `omega-das-integration-read-proxy-1` restarted 23:30:55Z, md5 = repo working tree).
- **Read-proxy live-verified (deployed, new code):** MeTTa-mode queries complete: `{"metta": '(...) $var'}` → HTTP 200 `mode:"metta"` ~1.3 s; structural variable queries 200 `mode:"structural"`. Ground metta/structural patterns are rejected fast with guidance (they never complete in the pinned engine — confirmed live: the QE answers an `Invalid` error string and the query hangs until client timeout).
- **Live probe (scratch container on client net, `memory/omega-das-bridge/evidence/iter2-probe/probe_iter2.py`):** exposed two real write-bridge defects:
  1. **Broker DNS alias missing:** the `docker run` broker had NO `atomdb-broker` alias on the client network → `DAS_BROKER_ENDPOINT=atomdb-broker:40007` unresolvable for any new client. **Fixed config-level:** `docker network connect --alias atomdb-broker` (verified: `getent hosts atomdb-broker` → 172.20.0.4).
  2. **Callback-peer rewrite never fired:** `str(BusCommand.ATOMDB)` = `"BusCommand.ATOMDB"`, never `"atomdb"` → add_atoms sent to `0.0.0.0:47002` → connection refused, SILENT write loss (fire-and-forget proven again). **Fixed:** rewrite normalizes str-mixin-enum + `.value` spellings (write_client.py, regression-tested).
  3. **Ground-template verify path was wrong:** fully-ground LINK_TEMPLATE queries never complete (QE answers `Invalid`, hangs → 30 s timeout). **Fixed:** verify by variable-form template (leading symbol → `$unassigned`; expected assignment = leading-symbol handle; live-proven form, re-eval E1). `link_queries` now carry `(handle, tokens, expected_assignment)`.
- **Tests:** full suite updated to the new shapes (variable-form vectors, assignment-bearing scripted answers, enum normalization case); tests/Dockerfile added (pinned-client pytest image, digest-build-arg pattern; first build attempt failed on a docstring-in-Dockerfile error — fixed). Test run + live probe rerun = next iteration's first action.
- **Standing state:** Omega agent STOPPED (verified inactive). Broker alias fix is live on OVH. Canary fact NOT yet written (probe write never landed — by design the canary run only counts with verification green).
- **Next (iteration 3):** rebuild test image → full unit suite → rerun live probe (write→verify→metta-read→cleanup) → record canary handles; then Phase-1 sign-off.

### Iteration 3 — 2026-10-20 00:07–00:35 UTC — Test suite green (109) + FIRST fully verified live canary loop + safe-cleanup redesign ✅
- **Test image built live** (`omega-write-bridge-tests`, pinned `python@sha256:a6e34c…` digest-pinned, client e12573cc compiled in-image). First full run: **3 failed / 105 passed** — the iter-2 23:50 haste left regressions. All three fixed with evidence:
  1. `write_client.py` rewrite dispatch: plain-string `"BusCommand.ATOMDB"` spellings (exactly what `str()` of the pinned str-mixin enum renders) now normalize to `atomdb`; probed the REAL pinned client in-image: `proxy.command` is `BusCommand.ATOMDB` (str-enum, hash/eq = `"atomdb"`), so dict-plain lookup fires live — normalization covers the `str()` spelling too.
  2. Stale test: link_queries are 3-tuples now — test unpacking updated.
  3. Stale test: variable-form compared against the TOP expression's ground template — rewritten per-link (each link vs its own ground template; variable replaces the 3-token leading symbol spec with 2 tokens).
- **Latent iter-2 bug found by the suite:** `ParsedFact.link_handles` still unpacked 2-tuples → crashed on first use. Fixed (3-tuple).
- **Live-DB safety measurement (mongo, db `das`, 1864 nodes / 3710 links):** `Symbol "Inheritance"` targeted by **421** other links, `Symbol "Concept"` by **791** → the old cleanup default (delete ALL fact handles) would have orphaned prior facts. **Cleanup redesigned:** links-only default, `--delete-nodes` opt-in (scratch DBs), explicit `--handle` lists must belong to the fact, `absent: null` when the deleted set can't be link-verified. README canary procedure + compose header (broker client-network alias invariant) updated; test suite 109/109 green on OVH.
- **LIVE PROBE (iter3-probe, deployed read-proxy image):**
  - `PHASE1_WRITE_VERIFY` — **first fully verified live write**: canary `(Inheritance (Concept "omega-bridge-canary-20261020") (Concept "write-bridge-test"))` written + variable-form read-back `verified: true` in 4.5 s.
  - `PHASE2_METTA_VAR` — fresh fact returned by **metta-mode** query through the deployed read-proxy (1.3 s), assignment binds `$_1`/`$B` to `(Concept "…canary…")` handle.
  - `PHASE4_CLEANUP` — deleted 3 links (links-only) + `PHASE4B` 2 unique nodes; `PHASE5` metta re-query 0 answers.
  - **Mongo ground truth:** all 3 canary links = 0, both unique nodes = 0, shared Symbols INTACT, E1 canary INTACT, totals unchanged → **zero residue, nothing else touched.**
  - **New wire reality — deletion is eventual:** read-back ~1 s after delete still matched the links (PHASE4 false `still_present`); 1 s later the same query = 0; mongo confirms gone. → next iteration: bounded retry/grace window in cleanup verification.
- **Standing state:** Omega agent STOPPED (untouched this iteration). DAS stack healthy. Evidence: `memory/omega-das-bridge/evidence/iter3-probe/` (probe + TRANSCRIPT).
- **Next (iteration 4):** cleanup-verify grace window (bounded retry) + test; then Phase-1 sign-off checklist (README runbook + acceptance entry in GDoc) and on to Phase 2 (thin import wrapper).
