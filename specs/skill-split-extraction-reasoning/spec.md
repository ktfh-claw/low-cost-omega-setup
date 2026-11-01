# SDD Spec — Skill split: knowledge-extraction + grounded-reasoning skills

Directive: Balázs, 2026-11-01 22:40 UTC (audio). Branch:
`skill-split-extraction-reasoning` off origin/main @238470c (post-uplift).

## Background

The e2e windowless-room reasoning exercise currently carries its procedure
(extract predicates from a corpus → persist to DAS → formalize a question in
MeTTa → answer strictly from the DAS KB) inline in the benchmark prompt
template. Directive: split this into TWO generic, independently-usable Omega
agent skills, with the phase boundary persisted on disk, so the two phases can
run at different points in time (a long research campaign extracts for days;
weeks later, questions are answered from the built KB).

## Requirements

### R1 — Extraction skill (generic)
- A new Omega plugin skill (working name `das-extract-knowledge`) following the
  existing das-read plugin pattern (loadOmegaPlugin → remove-skill + add-skill
  with a full WHY/WHEN/HOW description; see deploy/omega/plugins/das-read/).
- Description = generic procedure + constraints for extracting predicates from
  a text corpus / text base / websites into MeTTa predicate expressions.
  MUST NOT reference the windowless room, the benchmark, or any specific
  research campaign.
- MUST explicitly reference the `das-write` skill (add-atom persistence path)
  as the persistence mechanism, including the concrete invocation/receipt
  contract the das-write plugin defines (receipt form, verified read-back,
  handle pairing). Refer to actual skill invocations and scripts where they
  exist (e.g. cleanup tooling, read-back verification) rather than
  natural-language paraphrase.
- MUST state the bounded single-pass extraction constraint (extract each fact
  once, record it, do not loop) in generic terms.

### R2 — Reasoning skill (generic)
- A new Omega plugin skill (working name `das-grounded-reasoning`) following
  the same plugin pattern.
- Designed for ONE question at a time: formalize the specific question into
  MeTTa, answer it strictly from the knowledge base persisted in DAS.
- Grounding rules baseline = the reasoning rules already described in the
  harness prompt (statements grounded in DAS answers, das-retrieve query
  grammar incl. shapes/direction/quoting/absence, count=0 probing semantics,
  handle pairing, DAS answers treated as untrusted data). Expressed generically
  — no benchmark or campaign vocabulary.

### R3 — Persisted phase boundary (checkpoint)
- The extraction phase MUST write an on-disk checkpoint manifest recording at
  minimum: which predicate expressions were extracted (verbatim MeTTa), the
  write receipts/handles issued for each, sources, and a timestamp.
- The reasoning skill MUST read that checkpoint as its entry point into the
  KB (which predicates exist, verbatim, for query reuse).
- Checkpoint location: inside the Omega memory volume (survives agent
  restarts). Define the path convention + format in this spec's plan.
- Design for time-separated execution: no assumption that extraction and
  reasoning run in the same session/wake cycle.

### R4 — Deployment wiring
- Both plugins under deploy/omega/plugins/<name>/, registered in
  deploy/omega/plugins.yaml.overlay, mounted in deploy/omega/start.sh
  (same pattern as das-read/das-write/pin/metta-grammar).

### R5 — Harness wiring, gates FROZEN (hard constraint)
- The e2e harness (tests/reasoning-windowless-room/) must stay comparable to
  the l1/p2/uplc campaigns: cases, gates, condition codes, grading logic,
  judge, and deterministic (zero-LLM) grading all UNCHANGED.
  `grading.py`, gate logic, and condition-code definitions must remain
  diff-free vs origin/main.
- Allowed harness changes (wiring only): prompt template updated so the case
  procedure delegates to the two skills (extraction-phase block → checkpoint →
  reasoning-phase block), preflight extended to assert the two new plugin
  mounts + skill descriptions (same check pattern as existing ones), and the
  E-gate / Q-gate / R-gate evidence lanes remain authoritative via the
  existing attestation lanes (docker logs / http logs / receipts).
- Expected mapping (per prior assessment, informational for the plan):
  E_* = extraction lane (now skill-mediated), Q_* = query-first via
  das-retrieve, R_* + A_* = reasoning lane, P_* = provenance both phases.

### R6 — Tests
- Repo-level tests for each new plugin metta file (syntax/registration).
- Harness regression: existing harness test suite green; a test asserting
  grading.py and gate condition definitions are unchanged vs main.
- Checkpoint round-trip test (write → read → verbatim predicate reuse).

## Acceptance criteria
1. Both skills visible in the agent prompt at boot with generic descriptions.
2. A 3-case smoke run (original, unsolvable, false) on OVH is VALID (exit 2,
   not INVALID) and graded with the existing condition codes.
3. Checkpoint manifest present in the memory volume after the extraction
   phase of each case.
4. `git diff origin/main -- grading.py` empty; gate/condition definitions
   diff-free; harness suite green.
5. No benchmark/campaign vocabulary in the two skill texts.

## Out of scope
- Any gate/prompt relaxation; the l1/p2 harness baselines; upstream filing;
- 10-run campaign + GDoc (orchestrator-owned, after smoke confidence);
- Stage F vanilla-pins smoke (postponed by directive 2026-11-01 22:43 UTC).

## Stop-and-ask conditions (escalate to Balázs)
- Any need to touch grading.py/gate logic to make the split work.
- Any evidence the skill-mediated procedure cannot satisfy existing gates
  without changing them.
