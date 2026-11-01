# Tasks — Omega uplift v0.1.23 migration

- [x] T01 Upstream review: enumerate workarounds, verify each against
      upstream/main (git show/grep), disposition table → spec.md
- [x] T02 Core fork: branch omega-uplift-v0.1.23 from uplift-v0.1.20-pr358,
      merge upstream/main a6bd778, resolve loop.metta (union) +
      test_llm_budget.py (upstream), compile-check, push @577ef63
- [x] T03 Image builds on OVH: v0.1.23-577ef63 + fix rebuild
      v0.1.23-6376e99 (nested-let restore), build log clean
- [x] T04 Bridge deploy tree: start.sh image tag → v0.1.23-577ef63
- [x] T05 Bridge deploy tree: remove websearch.py overlay mount
      (upstream byte-identical)
- [x] T06 Bridge docs: uplift provenance record (image, commit, deltas,
      dropped overlay) in specs/omega-uplift-v0.1.23/
- [x] T07 Push bridge branch; rsync deploy tree to OVH
- [x] T08 Plugin validation on v0.1.23-6376e99 (04:00Z): das-read +
      metta-grammar drivers GREEN (EXIT=0; DAS_RETRIEVE_OK count=3,
      NAL derivation, metta 2-arg contract, pin present via
      all-4-plugin mount)
- [x] T09 Deploy on 6376e99: standby volume md5 verified (prompt.txt
      a5445796…), live start.sh swapped, restarted 04:01:27Z. Boot survival
      CONFIRMED past iteration-172 crash point (iteration 194 same pid,
      NRestarts unchanged, zero janus errors). Stage C COMPLETE. (First
      swap to 577ef63 22:45Z superseded.)
- [x] T10 Smoke rerun upl-20261101 (04:05–04:51Z): VALID, GATE FAIL 0/3,
      agent-side data — A/Q/P/R_MISSING, retrieve_calls 0, pins original 1
      / unsolvable 0 / false 1 + ADHERENCE_FALSE_COMPLETION; zero harness
      errors, teardown restored. Nested-let fix (6376e99) held through the
      full run; crash-loop defect closed. Analysis:
      memory/omega-uplift-v0.1.23/smoke-analysis.md. (First smoke on 577ef63
      was INVALID — superseded by fix 6376e99 + this rerun.) Root cause of
      the first INVALID: metta→Prolog translation defect in the upstream
      flat-let* gate-open body (duplicate $_ bindings → rename chains
      never unify → unbound var → janus py_call crash). FIXED on core fork
      6376e99 (nested-let restore + upstream semantic ports), bridge
      start.sh → v0.1.23-6376e99 (8f4913f).
- [ ] T11 Campaign: 10 runs × 3 cases, l1/p2 driver format, adherence +
      watchdog + judge. TIME GATE (~04:19 UTC) MISSED — implementation-
      healthy only at 04:51Z. Awaiting Balázs's decision on a late run.
- [ ] T12 GDoc stats report (l1/p2 format) + commit provenance; share to
      nem841425bal@gmail.com; close-out state.md + memory. Blocked on T11
      decision.
