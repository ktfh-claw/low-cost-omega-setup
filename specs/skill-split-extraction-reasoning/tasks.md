# Tasks — skill split

- [ ] T01 P0 recon: plugins (das-read, das-write, pin, metta-grammar), prompt
      template, GATES-REFERENCE, grading surface; record design decisions in
      plan.md
- [ ] T02 P1 extraction skill plugin + registration + syntax test (R1)
- [ ] T03 P2 reasoning skill plugin + registration + syntax test (R2)
- [ ] T04 P3 checkpoint manifest: format, writer (extraction), reader
      (reasoning), round-trip test (R3)
- [ ] T05 P4 deploy wiring: overlay entries + start.sh mounts (R4)
- [ ] T06 P5 harness wiring: prompt template delegates to skills; preflight
      asserts new plugins + checkpoint lane; NO gate/grading changes (R5)
- [ ] T07 P5 regression: harness suite green; grading.py + gate defs
      diff-free vs origin/main (R5)
- [ ] T08 Docs: README/docs update for the two skills + checkpoint contract
- [ ] T09 Commit + push branch; report diff summary + test evidence
- [ ] T10 (orchestrator) OVH deploy + 3-case smoke
- [ ] T11 (orchestrator) 10-run campaign + GDoc + cron
