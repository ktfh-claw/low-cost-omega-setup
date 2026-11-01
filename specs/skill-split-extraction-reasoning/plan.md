# Plan — skill split (see spec.md for requirements)

## Phases
- P0 Recon: read das-read/das-write/pin plugin sources, agent prompt template,
  GATES-REFERENCE.md, grading.py surface (read-only).
- P1 Extraction skill plugin `das-extract-knowledge` (R1) + syntax test.
- P2 Reasoning skill plugin `das-grounded-reasoning` (R2) + syntax test.
- P3 Checkpoint manifest format + path convention + round-trip test (R3).
- P4 Deployment wiring: plugins.yaml.overlay + start.sh mounts (R4).
- P5 Harness wiring: prompt template v-split (delegate to skills), preflight
  assertions for the two new plugins, checkpoint evidence lane hookup (R5).
  NO grading/gate changes. Regression: suite green + grading diff-free.
- P6 (orchestrator) OVH deploy + 3-case smoke → validity check.
- P7 (orchestrator) 10-run campaign, GDoc, cron; outside this worker's scope.

## Decisions to make in P0/P1 (record in plan, keep spec-faithful)
- Exact skill names (working names das-extract-knowledge / das-grounded-reasoning).
- Checkpoint path: propose /PeTTa/repos/Omega/memory/knowledge-checkpoints/<campaign-or-corpus-id>.md (+ JSON sidecar if needed).
- How the reasoning skill references the checkpoint generically (discover
  latest checkpoint by convention, not hardcoded benchmark path).
