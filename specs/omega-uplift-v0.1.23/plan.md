# Plan — Omega uplift v0.1.23 migration

Sequenced execution of `spec.md`. Owner orchestration stays in the main
session; repo-local implementation on the migration branch.

## Phases

1. **Upstream review (DONE 2026-10-31 ~22:30 UTC)** — workaround
   enumeration with live git verification; disposition table in spec.
2. **Core fork migration (DONE)** — branch `omega-uplift-v0.1.23` @
   577ef63 pushed to ktfh-claw/OmegaClaw-Core; merge conflicts resolved
   (loop.metta union, test file upstream-side); 186 files compile clean.
3. **Image build (RUNNING)** — OVH build of `omegaclaw:v0.1.23-577ef63`
   from verified clone; log `~/omega-build-logs/build-577ef63.log`.
4. **Bridge repo deploy tree** — branch `omega-uplift-v0.1.23` from main
   tip 80c06c7; elementary commits: start.sh image tag, drop websearch
   overlay mount, docs. NO harness edits unless the container interface
   changed (verify first).
5. **Plugin + runtime validation** — throwaway container on the new
   image: das-read/metta-grammar drivers, pin plugin, das-retrieve
   registration, ASI:One 200, TG polling, chroma init observation.
6. **Smoke** — 3-case e2e on the new image with unchanged harness;
   gate-by-gate analysis; fix INVALID causes only.
7. **Campaign (time-gated)** — if implementation done < ~04:19 UTC
   (6h from directive): 10 runs × 3 cases, l1/p2 format; INVALID
   tolerated; stats GDoc + commit provenance; share to
   nem841425bal@gmail.com.

## Task shape

tasks.md tracks the elementary commit units; each commit maps to one
task. Work in dependency order; never batch unrelated changes.
