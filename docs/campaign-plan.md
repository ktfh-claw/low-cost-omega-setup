# Campaign plan — omega-das-bridge (Path B execution)

**Directive (Balázs, 2026-10-19 21:59 UTC, Discord voice):** execute the Path B plan from the re-evaluation report. Use the OVH node as the live development environment. Use this repo (`low-cost-omega-setup`) as the **bridge repo**. Clean it first (remove the outdated operator-gated DAS-write documentation). Keep all work in a single branch. Update the live Google Doc on every iteration (main reporting interface). Push new code to the forked repos and record GitHub links in the doc. Draft upstream contributions in the forked repositories only. Use the `coder-opencode` agent for development/review tasks. Activate a 30-minute cron; brief Discord updates per iteration.

## Phases

### Phase 0 — Bootstrap (iteration 1)
- [x] Cleanup: `artifacts/` → `historical/`; operator-import runbook removed; stale `docs/omega-das-direct-write` branch deleted (was ancestor of main, zero-delta).
- [x] Repo sync: `das` fork fast-forwarded e12573cc → 48507929 (upstream +66) and pushed; `das-toolbox` already current; `das-metta-parser` fork created (ktfh-claw) and pushed.
- [x] Campaign docs created in this repo: README, architecture, plan, status, contributions.
- [x] Google Doc re-opened as live progress doc: append "Execution campaign" section with directive, plan, iteration log.
- [x] 30-minute cron activated.

### Phase 1 — Bridge core (config-only, live on OVH) — **SIGNED OFF 2026-10-20 02:41 UTC**
- [x] Read proxy: config-level MeTTa-mode (`use_metta_as_query_tokens`) wrapper applied and live; MeTTa-form + structural queries, ground and variable forms, all verified live (iters 2–8).
- [x] `das-write` skill v1: MeTTa → atoms → `AtomDBProxy.add_atoms` → read-back verification → verified handles; live as compose service `omega-das-write-bridge-write-bridge-1` (iters 5–8); canary cleanup procedure documented (README §Canary procedure).
- [x] Write path verification: canary fact written by the lane, read back through the metta query path, then removed with zero residue — **two consecutive fully green loops (iter7-a1, iter8-a1)**, each with a first-pass-correct oracle absence verdict and mongo ground truth (totals 1864/3710 unchanged).
- [x] Absence oracle (added beyond the original plan, iters 6–7): alternate-pattern verification + bounded standby re-checks; the in-window absence verdict is no longer advisory. Residual upstream ask (fork-local draft): delete-apply ack.

### Phase 2 — Integration — **COMPLETE 2026-10-20 05:55 UTC** (both items live-validated)
- [x] Thin import wrapper (segmentation → syntax gate → newline-escape fallback → provenance → db_loader) replacing the operator lane for bulk loads; validated against a copy of real history.metta — **99.17% yield (8,216/8,285), atom_types 0, exactly one ground CampaignProvenance link per entry** (iters 9–10).
- [x] `&persistent` interception hook in the Omega skill layer (plugin `das-write`, config-only): agent persistence vocabulary becomes durable, verified DAS writes; validated in a test container (enabled path: BRIDGE-PERSIST-OK verified=7 + read-proxy read-back + oracle cleanup + mongo zero-residue; disabled path: zero behavioral change). **Live agent stays STOPPED — restart only with explicit Balázs approval.**

### Phase 3 — Upstream contribution ladder (fork-local drafts)
- [x] All 5 issue drafts finalized in `docs/contributions/` (re-validated against latest upstream — done iter 12, 2026-10-20).
- [x] Draft PRs opened in the **forked repos** where executable: python-client typo fix branch — pushed iter 12 (`fix/python-client-metta-typo` @ 067fc8e1 on ktfh-claw/das); parser `<>` lexer rule + `syntax_check` OK-print + newline doc — pushed iter 13 (`fix/lexer-bare-angle-symbols` @ 4687c8c on ktfh-claw/das-metta-parser, 3 commits, orchestrator-validated).
- [x] Fork cleanup: archive/delete superseded branches — **done 2026-10-20 (iter 14)**: das-toolbox lane archived into `docs/contributions/das-toolbox-lane/` (full-history bundle, restore-tested; uncommitted operator-write-lane patch; memory notes); fork branches `omega-das-integration` / `omega-das-write-integration` / `omega-history-extraction-v2` deleted; fork master reset to upstream @928edfc; local lane branches + worktree removed.
- [ ] Nothing filed/pushed upstream — needs explicit approval, always.

### Phase 4 — Close-out
- [x] End-to-end acceptance test documented — `docs/acceptance.md` (2026-10-20 09:12 UTC): three consecutive green loops (iter7-a1, iter8-a1, iter16-a1), each first-pass oracle verdict + mongo zero residue; mirrored in the Google Doc §16 + `docs/status.md`.
- [x] Runbook complete (from-scratch reproduction) — `docs/runbook.md`: full 8-section runbook (digests, broker invariants, node-id rule, canary procedure, bulk-load lane, gated Omega attachment, acceptance loop).
- [ ] Memory files closed out; cron removed or converted to monitor-only — pending Balázs's decisions (upstream filing, live-agent restart, cron disposition).

## Tracking rules

- One iteration = one cron tick. Every iteration: (1) do the work, (2) update `docs/status.md`, (3) append an iteration entry to the Google Doc, (4) push commits, (5) brief Discord update.
- Acceptance for each phase is evidence-based: exact commands, outputs, links.
- The Google Doc is authoritative for Balázs; this repo mirrors it.
