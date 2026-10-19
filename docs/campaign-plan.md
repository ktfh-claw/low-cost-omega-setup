# Campaign plan — omega-das-bridge (Path B execution)

**Directive (Balázs, 2026-10-19 21:59 UTC, Discord voice):** execute the Path B plan from the re-evaluation report. Use the OVH node as the live development environment. Use this repo (`low-cost-omega-setup`) as the **bridge repo**. Clean it first (remove the outdated operator-gated DAS-write documentation). Keep all work in a single branch. Update the live Google Doc on every iteration (main reporting interface). Push new code to the forked repos and record GitHub links in the doc. Draft upstream contributions in the forked repositories only. Use the `coder-opencode` agent for development/review tasks. Activate a 30-minute cron; brief Discord updates per iteration.

## Phases

### Phase 0 — Bootstrap (iteration 1)
- [x] Cleanup: `artifacts/` → `historical/`; operator-import runbook removed; stale `docs/omega-das-direct-write` branch deleted (was ancestor of main, zero-delta).
- [x] Repo sync: `das` fork fast-forwarded e12573cc → 48507929 (upstream +66) and pushed; `das-toolbox` already current; `das-metta-parser` fork created (ktfh-claw) and pushed.
- [x] Campaign docs created in this repo: README, architecture, plan, status, contributions.
- [ ] Google Doc re-opened as live progress doc: append "Execution campaign" section with directive, plan, iteration log.
- [ ] 30-minute cron activated.

### Phase 1 — Bridge core (config-only, live on OVH)
- [ ] Read proxy: apply config-level MeTTa-mode (`use_metta_as_query_tokens`) wrapper; verify MeTTa-form + structural queries both work (both ground and variable queries).
- [ ] `das-write` skill v1: MeTTa → atoms → `AtomDBProxy.add_atoms` → read-back verification → verified handles. Live-tested against the running broker; write logged; canary cleanup procedure documented.
- [ ] Write path verification: one canary fact written by the skill, read back through the query path, then removed.

### Phase 2 — Integration
- [ ] Thin import wrapper (segmentation → syntax gate → newline-escape fallback → provenance → db_loader) replacing the operator lane for bulk loads; validated against a copy of real history.metta (expected ≥99%).
- [ ] `&persistent` interception hook in the Omega skill layer; agent persistence vocabulary becomes durable DAS writes (agent container resumes with skill mounted; service stays disabled until Balázs re-activates the Omega campaign — verify the hook in a test container first, do not restart the live agent without approval).

### Phase 3 — Upstream contribution ladder (fork-local drafts)
- [ ] All 5 issue drafts finalized in `docs/contributions/` (re-validated against latest upstream).
- [ ] Draft PRs opened in the **forked repos** where executable: python-client typo fix branch; parser `<>` lexer rule + `syntax_check` OK-print + raw-newline fixes.
- [ ] Fork cleanup: archive/delete superseded branches (`omega-das-integration`, `omega-das-write-integration`, `omega-history-extraction-v2` in das-toolbox — after archiving the campaign-import lane code into this repo).
- [ ] Nothing filed/pushed upstream — needs explicit approval, always.

### Phase 4 — Close-out
- [ ] End-to-end acceptance test documented in the Google Doc + `docs/status.md`.
- [ ] Runbook complete (from-scratch reproduction).
- [ ] Memory files closed out; cron removed or converted to monitor-only.

## Tracking rules

- One iteration = one cron tick. Every iteration: (1) do the work, (2) update `docs/status.md`, (3) append an iteration entry to the Google Doc, (4) push commits, (5) brief Discord update.
- Acceptance for each phase is evidence-based: exact commands, outputs, links.
- The Google Doc is authoritative for Balázs; this repo mirrors it.
