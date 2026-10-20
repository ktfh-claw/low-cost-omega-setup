# das-toolbox campaign lane — retired archive

**Status: RETIRED 2026-10-20 (iteration 14).** This directory is the archival record of the
`omega-das-integration` deployment lane developed in the `ktfh-claw/das-toolbox` fork
(2026-10-03 → 2026-10-14, 14 commits on `master` ahead of `singnet/das-toolbox` @928edfc,
all authored by ktfh-claw, never contributed upstream). The lane is superseded by the Path B
bridge in this repo (`deploy/das/` read-proxy + write-bridge + import-wrapper). It is preserved
here as evidence and for potential future reference; it should not be reused as-is.

## Why retired

- The lane was built for the pre-re-evaluation architecture: operator-gated bulk import
  (`scripts/campaign_import.py`, 1200 lines) and an operator-gated write path
  (`fact-write-proxy`). The 2026-10-19/20 re-evaluation (see Google Doc §1–15 and
  `memory/omega-das-integration-reeval/`) invalidated that architecture: writes go through the
  broker's `AtomDBProxy.add_atoms` fire-and-forget path (no source fork needed), and bulk loads
  go through the thin import wrapper validated in iteration 10 (99.17% yield).
- Phase 3 of the campaign plan calls for retiring superseded fork branches after archiving the
  lane code into this repo.

## Contents

| File | What it is |
|---|---|
| `das-toolbox-lane-master.bundle` | Complete `git bundle` of `ktfh-claw/das-toolbox` `master` @a193af4 — **records a complete history** (includes upstream base 928edfc and all 14 lane commits; self-contained, no other repo needed). Restore: `git clone das-toolbox-lane-master.bundle <dir>`. |
| `worktree-uncommitted-operator-write-lane.patch` | Uncommitted working-tree diff from the `feat/omega-das-direct-write` worktree @dfccfae (+131/−3 over 6 files): the operator-gated `fact-write-proxy` service (bearer-token HTTP write facade with rate limiting + read-back verification, compose secrets wiring, atomdb-broker service entry, preflight token checks, 39-line test extension). Superseded by the Path B write-bridge; preserved because it was never committed anywhere. Applies cleanly at both `dfccfae` and `a193af4` (`git apply`, verified). |
| `memory-notes/` | Three lane development notes (redis-private-peer-fix, distroless-healthcheck-fix, secure-deployment-implementation) — engineering findings from the lane's compose/deployment work. |

## Lane commit record (upstream/master..master, oldest first)

```
37eb787 feat: add isolated Omega DAS deployment lane
7fa46cb fix: support distroless DAS runtime health model
8a86c1c fix: allow nonroot DAS config access
1f4f455 fix: permit DAS Redis private peer access
d234285 feat: add private DAS read proxy
d4ab765 fix: accept relative deployment env files
ccf61ce fix: install generated DAS gRPC stubs
d9e136d fix: rewrite DAS wildcard callback peers
bc9bf10 feat: add bounded Omega DAS campaign import
a6da5c5 fix: decode nested DAS query handles
113f530 fix: enforce DAS answer decode bounds
e1109a7 fix: harden Omega history import isolation
dfccfae fix: reject empty PLN evidence groups
a193af4 feat: extend Omega history extraction
```

Net diff vs upstream @928edfc: 19 files added under `deploy/omega-das-integration/`
(+3,165 lines), no upstream files modified. All lane branches were contained in `master`
(verified: `omega-das-integration` @d9e136d, `omega-das-write-integration` @dfccfae,
`omega-history-extraction-v2` @a193af4, `feat/omega-das-direct-write` @dfccfae are all
ancestors of `master`; the worktree additionally carried the uncommitted patch above).

## Disposition (executed iteration 14)

- Local repo `repos/das-toolbox`: lane branches deleted, worktree removed, checkout reset to
  `upstream/master` @928edfc (fetch-only posture; the local `master` and lane branches are gone).
- Fork `ktfh-claw/das-toolbox`: lane branches deleted server-side via
  [GitHub API](https://api.github.com) (the `git push fork --delete` path was unavailable).
  `master` reset to upstream @928edfc — the fork is now a clean mirror of upstream.
- Nothing was ever filed or pushed to `singnet/das-toolbox` (drafts-only rule held throughout).
