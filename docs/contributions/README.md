# Upstream contributions — ladder and status

**Standing rule (Balázs):** filing issues/PRs against public upstream repos (`singnet/*`) is a PUBLIC action and always requires his explicit go-ahead first. Until then: evidence-backed drafts live here, and executable drafts (branches + PRs) are opened **only in the forked repositories** (`ktfh-claw/*`).

Contribution ladder (order per re-eval report §11):

| # | Defect / contribution | Target repo | Type | Status |
|---|---|---|---|---|
| 1 | Query-engine **crashes** on mis-routed `atomdb` command (uncaught `std::runtime_error("Processor is not registered to process command: atomdb")`); late-joiner command-ownership gap | singnet/das | issue (+robustness PR later) | **DRAFT, re-validated 2026-10-20** — `issue-1-qe-crash.md` |
| 2 | Python client typo `user_metta_as_query_tokens` → silent no-op → MeTTa queries unusable | singnet/das | issue + trivial PR | **DRAFT re-validated + fork branch drafted 2026-10-20** — `fix/python-client-metta-typo` in ktfh-claw/das; `issue-2-client-typo.md` |
| 3 | das-metta-parser lexer silently **drops `<`/`>`** from bare symbols | singnet/das-metta-parser | issue + PR | **DRAFT, re-validated 2026-10-20** (19 bare-angle entries measured in real corpus) — `issue-3-lexer-angle-drop.md` |
| 4 | `syntax_check` prints "Syntax check OK" even on failure | singnet/das-metta-parser | issue + PR | **DRAFT, re-validated 2026-10-20** — `issue-4-syntax-check-ok.md` |
| 5 | Raw newline inside quoted string breaks the token (98.2% raw → 99.17% with shipped escape fallback) | singnet/das-metta-parser | issue + PR | **DRAFT, re-validated 2026-10-20** — `issue-5-newline-in-string.md` |
| 6 | Docs: "Writing atoms from external agents" guide (atomdb-broker deployment, python client example, fire-and-forget caveat, MeTTa-mode guidance) | singnet/das | docs | **PLANNED** (last, after fixes) |
| 7 | PeTTa superpose/collapse history-garbage leak (real defect behind our fork's garbage history entries) | singnet/Omega (upstream line) | issue + PR | **PLANNED** (coordinate with PR#349 memory redesign) |

## Fork-local executable state

- `ktfh-claw/das` — synced to upstream `48507929` (was e12573cc, +66 commits). Zero local delta on master.
- `ktfh-claw/das-metta-parser` — fork created 2026-10-19, pushed at `19022d2`.
- `ktfh-claw/das-toolbox` — **lane retired 2026-10-20 (iteration 14)**: master reset to upstream `928edfc` (forced update verified via `ls-remote`); superseded lane branches deleted server-side. The 14-commit campaign lane (2026-10-03 → 10-14, +3,165 lines under `deploy/omega-das-integration/`) is archived in [`docs/contributions/das-toolbox-lane/`](das-toolbox-lane/README.md) — full-history git bundle (restore-tested), the uncommitted operator-write-lane worktree patch, and the lane memory notes.

## Branch hygiene (forks)

Superseded branches are deleted after their content is preserved in this repo (archive policy: content first, then delete). Tracked:

- das-toolbox: `omega-das-integration`, `omega-das-write-integration`, `omega-history-extraction-v2` — **deleted from fork 2026-10-20 (iteration 14)** after archiving the lane into [`docs/contributions/das-toolbox-lane/`](das-toolbox-lane/README.md); fork master reset to upstream @928edfc.
- low-cost-omega-setup: `docs/omega-das-direct-write` — deleted 2026-10-19 (was ancestor of main, zero-delta).
- Note: upstream-legacy branches in `ktfh-claw/das-toolbox` (`artur-*`, `das-*`, `pbc-*`, `fix/*` — old upstream development branches predating this campaign) are not campaign artifacts and were left untouched.
