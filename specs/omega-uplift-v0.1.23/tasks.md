# Tasks — Omega uplift v0.1.23 migration

- [x] T01 Upstream review: enumerate workarounds, verify each against
      upstream/main (git show/grep), disposition table → spec.md
- [x] T02 Core fork: branch omega-uplift-v0.1.23 from uplift-v0.1.20-pr358,
      merge upstream/main a6bd778, resolve loop.metta (union) +
      test_llm_budget.py (upstream), compile-check, push @577ef63
- [~] T03 Image build omegaclaw:v0.1.23-577ef63 on OVH (running,
      faiss compile stage)
- [ ] T04 Bridge deploy tree: start.sh image tag → v0.1.23-577ef63
- [ ] T05 Bridge deploy tree: remove websearch.py overlay mount
      (upstream byte-identical)
- [ ] T06 Bridge docs: uplift provenance record (image, commit, deltas,
      dropped overlay) in specs/omega-uplift-v0.1.23/
- [ ] T07 Push bridge branch; rsync deploy tree to OVH
- [ ] T08 Plugin validation on new image (throwaway container):
      das-read + metta-grammar drivers, pin plugin, das-retrieve
      registration, ASI:One 200, TG poll, chroma init
- [ ] T09 Deploy: swap omega-curiosity to new image (backup prompt/state
      first), verify standby boots clean
- [ ] T10 Smoke: 3-case e2e (original, unsolvable, false), unchanged
      harness @80c06c7; gate-by-gate analysis; fix INVALID only
- [ ] T11 Campaign (time-gated <04:19 UTC): 10 runs × 3 cases,
      l1/p2 driver format, adherence + watchdog + judge
- [ ] T12 GDoc stats report (l1/p2 format) + commit provenance; share to
      nem841425bal@gmail.com; close-out state.md + memory
