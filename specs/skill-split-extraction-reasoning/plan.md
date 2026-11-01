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

## P0 Design Decisions (recon 2026-11-01)

### Skill architecture (both skills)

- **Pattern**: das-read-derived `remove-skill` + `add-skill` re-registration
  with full WHY/WHEN/HOW descriptions, mounted as plugin dirs
  (`deploy/omega/plugins/<name>/`), registered in `plugins.yaml.overlay`,
  bind-mounted in `start.sh` (R4).
- **New-skill caveat**: unlike das-read (rebinding an EXISTING skill), both
  skills are NEW — there is no stock registration to remove, so the plugins
  follow the metta-grammar precedent of `remove-skill` (defensive, clears
  any prior mount's registration) then `add-skill`.
- **Handler clauses**: both skills bind MeTTa handler clauses so they are
  invocable without error:
  - `das-extract-knowledge`: takes a JSON body
    `{"action": "checkpoint" | "describe", ...}` — the "checkpoint" action
    is the phase-boundary manifest writer (R3): appends the extracted
    predicates + receipts/handles + sources + timestamp to the checkpoint
    file in the Omega memory volume; returns a `CHECKPOINT-APPENDED`
    receipt. The "describe" action returns the procedure text (LLM
    consultation).
  - `das-grounded-reasoning`: takes a JSON body
    `{"action": "describe" | "read_checkpoint", ...}` — the checkpoint
    reader returns the latest checkpoint manifest (predicates verbatim)
    as the reasoning entry point (R3).
- **Description is the deliverable** (R1/R2): the procedure text the LLM
  sees in its tool list. Both descriptions are generic — zero benchmark /
  campaign / windowless-room vocabulary — and reference the DAS read/write
  tool grammar (`das-retrieve` shapes/direction/quoting/absence,
  `add-atom &persistent` + `BRIDGE-PERSIST-OK` receipts, handle pairing,
  untrusted-answers policy) exactly as the harness prompt template does
  (the only vocabulary that survives the split).
- **No changes to grading.py / gate logic / condition codes** (R5): both
  skills are wiring-only; the harness prompt template delegates the
  per-case procedure to the two skills, the preflight asserts the new
  mounts. The E/Q/R/P/H gate conditions and their definitions are frozen
  (diff-free vs origin/main).

### Checkpoint manifest (R3 — the phase boundary)

- **Path convention**: `/PeTTa/repos/Omega/memory/knowledge-checkpoints/`
  (inside the Omega memory volume; host path:
  `<memory-volume>/knowledge-checkpoints/`). One manifest per corpus,
  append-only across runs (extraction appends; reasoning reads).
- **Format**: a single markdown file per corpus
  (`knowledge-checkpoints/<corpus-or-campaign-id>.md`) with structured
  sections; the `expr` lines reuse the extraction-record grammar
  (`expr <expression> top=<handle>`) so the reasoning skill can quote
  predicates verbatim. No JSON sidecar (the round-trip test exercises the
  markdown grammar directly; a JSON sidecar would be a second format to
  keep in sync).
- **Discovery convention (reasoning side)**: the reasoning skill reads the
  LATEST checkpoint manifest in `knowledge-checkpoints/` (mtime-desc), not
  a hardcoded path — this is the generic entry point; the harness prompt
  template references the same convention.
- **Time-separated execution**: the manifest is a plain file in the memory
  volume; extraction and reasoning may run days/weeks apart with no
  shared process state (no DAS query state, no session, no wake-cycle
  assumption).

### Harness wiring (R5)

- Prompt template: the TASK LIST is restructured as
  extraction-phase-block → checkpoint → reasoning-phase-block, each phase
  delegating its procedure to the corresponding skill (the skills carry
  the WHY/WHEN/HOW; the template keeps the benchmark's artifact paths and
  gate contract).
- Preflight: asserts both plugins are mounted (container file exists) and
  their skill descriptions carry the required contract markers.

### Test strategy (R6)

- Plugin syntax/registration tests: static .metta structure tests
  (das-read precedent) + live container driver probes
  (`validate_driver.metta` + `run_driver.sh` per plugin).
- Checkpoint round-trip test: write a checkpoint manifest via the
  extraction skill's checkpoint writer, read it back via the reasoning
  skill's reader, assert the predicates round-trip verbatim (expressions
  character-for-character).
- Regression: grading.py + gate/condition definitions diff-free vs
  origin/main (byte-identical), asserted by a unit test that shells out
  to git diff.
