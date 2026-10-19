# From-scratch deployment runbook — omega-das-bridge

**Status: stub (Phase 4 deliverable).** Target: an operator with a fresh Linux host can reproduce the entire lane (DAS stack + broker + read proxy + bridge skills + Omega agent attachment) from this repo alone. Sections below are filled in as each component's automation lands; until then the authoritative component state is the [re-evaluation report](https://docs.google.com/document/d/1Pw5diOmac40Abc8_D1CG0_b3OrOHntq1BSzOv2H63dM/edit) and the validated OVH deployment.

Planned sections:
1. Host prerequisites (Linux, Docker Engine + Compose, UFW posture).
2. DAS datastore + query stack (compose; internal networks; no published ports).
3. atomdb-broker deployment (bind 0.0.0.0; the three live-discovered invariants from `docs/architecture.md` §5).
4. Read proxy (bounded facade; MeTTa-mode wrapper).
5. Bridge write lane (das-write skill mount; logging; canary procedure).
6. Bulk/history load lane (wrapper + stock parser/db_loader images).
7. Omega agent attachment (client network only; no DB credentials; service enable/stop).
8. Verification (read-back checks, canary write/remove, backup/restore).
