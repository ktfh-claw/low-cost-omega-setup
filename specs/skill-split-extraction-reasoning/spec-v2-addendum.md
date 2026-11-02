# Spec v2 ADDENDUM — two-phase split as TWO agent requests (directive 2026-11-02 08:25 UTC)

Supersedes the wiring aspects of spec.md R5 (skills/prompt/checkpoint design
in R1-R4 unchanged and remain in force). Origin: Balázs invalidated the first
implementation (single fat prompt + skill references, one request — not the
intended test). This addendum is authoritative for harness behavior.

## A1 — Two separate requests per case (the phase split is PHYSICAL)
Per case, the harness drives TWO agent phases:
- **Phase 1 — EXTRACTION**: install the extraction prompt (paths + question
  context only), restart the agent, let it run the das-extract-knowledge
  procedure (bounded single-pass, das-write persistence, extraction record).
- **Phase boundary signal**: phase 1 is complete when the checkpoint manifest
  for the case exists in the memory volume knowledge-checkpoints/ dir.
  Poll the volume (bounded interval, e.g. 30s) up to the phase timeout
  (default: the case window). On timeout WITHOUT a manifest: grade as-is
  (the E-gate will fail truthfully) — do not invent a boundary.
- **CRITICAL — snapshot phase-1 evidence BEFORE the phase-2 restart**: the
  systemd unit's start.sh `rm -f`s the container on restart, so docker logs
  die with it. Before issuing the phase-2 restart, snapshot the phase-1
  container logs (docker logs since case-start ISO) into the run results dir
  (e.g. results/<run-id>/windows/<case>/phase1-docker.log). The E-gate and
  Q-gate attestation lanes must read from this snapshot for phase-1 evidence.
- **Phase 2 — REASONING**: install the reasoning prompt, restart the agent
  with FRESH/TRIMMED history (same per-case history discipline as before).
  The agent may rely ONLY on: the checkpoint manifest, the DAS KB, and the
  on-disk extraction record (facts-index). It must NOT inherit phase-1
  wake-cycle context — that is the point of the split.

## A2 — Both prompts heavily simplified
- Each phase prompt: benchmark wiring ONLY (case id, question, artifact
  paths, required output format, STOP rule) + minimal pseudocode steps that
  DELEGATE the procedure to the respective skill (das-extract-knowledge /
  das-grounded-reasoning). Target: each prompt well under half the current
  fat template's word count; no duplicated HOW-procedure text that the skill
  descriptions already carry.
- The answer-block format spec and gate-parsing rules stay (they are the
  measured contract), but stated once, tersely.

## A3 — Gates frozen (unchanged from spec.md R5)
- grading.py and all gate/condition definitions remain diff-free vs
  origin/main. The evidence lanes adapt (phase-1 log snapshot) but the
  conditions, codes, and grading logic do not.

## A4 — Comparability
- Same 3 cases, same judge, same exit-code semantics, same report format.
- New run-id prefix (sks2) so the series is cleanly separable from the
  invalidated sks runs in results and the GDoc.

## Acceptance (v2)
1. Harness code demonstrates per-case: two prompts, two restarts, manifest
   poll boundary, phase-1 log snapshot before restart #2.
2. Both phase prompts exist as separate template files, word-count target met.
3. grading.py diff-free; suite green (incl. new unit tests for the two-phase
   orchestration, manifest polling, and snapshot logic).
4. 3-case smoke VALID before the 10-run relaunch.
