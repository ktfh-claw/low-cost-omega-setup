# Low-cost Omega Setup

Documentation for running a continuously operating [Omega](https://github.com/singnet/Omega) agent on private infrastructure with a low-cost LLM route, and for separating Omega’s local persistent MeTTa memory from an optional [Distributed AtomSpace (DAS)](https://github.com/singnet/das-toolbox) service. The distinction matters: `add-atom &persistent` records an atom in Omega’s local persistent space; it is not, by itself, proof of a write to DAS.

The canonical campaign label for the run documented here is **RKGI**; the evaluated task benchmark and artifacts themselves are ARC-AGI-labelled. A separate, self-contained status report is in [`artifacts/status-2026-10-05.md`](artifacts/status-2026-10-05.md).

---

## Document map

| Document | Purpose |
|---|---|
| `README.md` (this file) | High-level overview, provenance, and links. |
| [`artifacts/experiment-report.md`](artifacts/experiment-report.md) | Full experiment report: test matrix, failures, safety controls, retest criteria. |
| [`artifacts/status-2026-10-05.md`](artifacts/status-2026-10-05.md) | Separate status report for the RKGI-ARC campaign conclusion and the final resumed task. |
| [`artifacts/omega-das-integration.md`](artifacts/omega-das-integration.md) | Reproducible topology, read path, operator-only DAS import/write lane, and evidence rules for distinguishing it from Omega local persistence. |
| [`artifacts/operator-das-import-runbook.md`](artifacts/operator-das-import-runbook.md) | Step-by-step operator runbook for persisting Omega campaign atoms into DAS: freeze, dry run, delta analysis, apply, independent verification, resume. |
| [`artifacts/omega-1020-uplift.md`](artifacts/omega-1020-uplift.md) | Omega v0.1.20 uplift provenance, test evidence, live runtime validation, and known follow-ups. |

## Architecture overview

```text
Omega agent (`omega-curiosity`)
  ├─ scheduled autonomous wake loop (no inbound message required)
  ├─ ASI:One (`asi1-ultra`) model via PR #358 native tools API
  ├─ MeTTa: `add-atom &persistent …`
  │    └─ local Omega persistent space + mounted campaign memory files
  └─ DAS service (separate internal compose deployment)
       ├─ private client/backend Docker networks
       ├─ bounded read: Omega DAS adapter → internal read proxy → query engine → MongoDB/Redis
       └─ operator-only DAS write: `campaign_import.py` runbook (the agent has no write capability)
```

### Two persistence planes — do not conflate them

1. **Omega local persistence.** The running agent issues MeTTa such as `add-atom &persistent …` and appends campaign state under `./repos/Omega/memory`. The live logs prove this path is active. It is persistence inside Omega/PeTTa, not a network write to the Distributed AtomSpace.
2. **DAS persistence.** The DAS stack persists atom data through its own MongoDB/Redis-backed services. The documented write path is a bounded, operator-authorized import (`campaign_import.py`); it is deliberately not exposed as an autonomous agent tool. A DAS write claim requires import/loader evidence plus a datastore-side before/after check. The full procedure is in the [operator DAS import runbook](artifacts/operator-das-import-runbook.md).

The distinction prevents a common false positive: seeing `&persistent` in an Omega log does **not** establish that the atom reached DAS.


## Campaign conclusion

The campaign included three earlier verified ARC task solves during the broader run. A final resumed task, `05a7bcf2`, was an **incomplete run**: 0/3 attempts used, no submission, no solve. ASI:One tool calling continued to work without auth, quota, or rate-limit failures, but reasoning/output budget exhaustion and a failed task-to-Python handoff prevented completion. There is no evidence of material native MeTTa execution. See [the status report](artifacts/status-2026-10-05.md) for the distinct historical versus final-run accounting.

## Current conclusions

- Stock Omega scheduled wake works headlessly and can perform autonomous provider calls without a new human message.
- ASI:One (`asi1-ultra`) is validated through the live deployment with PR #358 native tool calls (`provider=ASIOne model=asi1-ultra finish_reason=tool_calls`).
- Free-router LLM output is variable and not reliable as a continuous solver.
- PR #358 replaces text-command emulation with the native tools API, but does not by itself guarantee ARC reasoning quality; at the reviewed head, skill parameters were typed as strings.
- The bounded DAS adapter is deployed and validated. Three operator import operations were independently verified in production: the initial 2026-10-05 import, an earlier five-fact delta on 2026-10-06, and the final 20-fact pre-uplift delta on 2026-10-06. The live `omega-curiosity` container runs the DAS-enabled image attached to the internal DAS client network and performs bounded DAS reads; its observed `&persistent` operations remain local Omega persistence, not direct DAS writes.

## Reproducible setup

The validated deployment requires a Linux host with Git and Docker Engine; Docker Compose is also required when deploying the optional DAS stack. The host needs network access to the selected inference provider and communication channel. Exact validated versions and provenance are recorded in the artifacts below.

1. Build the exact v0.1.20 + PR #358 fork commit using the [uplift build procedure](artifacts/omega-1020-uplift.md#reproduce-the-validated-build). Plain upstream v0.1.20 is insufficient because it does not include PR #358.
2. Configure provider auth (ASI:One) and ARC tool credentials through read-only mounted secret files or environment variables; never commit secrets.
3. Configure the optional DAS read-only lane (disabled by default) if retrieval-augmented tool use is desired.
4. If DAS data must be seeded or imported, follow the [operator DAS import runbook](artifacts/operator-das-import-runbook.md); never grant the autonomous Omega loop a direct DAS write endpoint.
5. Launch the autonomous wake loop.

## Source and image provenance

- Omega upstream: https://github.com/singnet/Omega
- Omega PR #358 (native tools API): https://github.com/singnet/Omega/pull/358
- Omega v0.1.20 release: `19e94bb336378eebb66e8e689d0d3ff0e1bf5f77`
- Omega PR #358 head: `c193ab39857944017e067b426779d66113649313` (still open and not included in v0.1.20 at validation time)
- Merged fork branch: `ktfh-claw/OmegaClaw-Core` branch `uplift-v0.1.20-pr358` at `f38217fa6b34a277cd4c0e780d2340af85eb4f67` (v0.1.20 + PR #358 + fork ARC/DAS/nginx line + validation fixes + opt-in Telegram autonomous wakes)
- Live image: `omegaclaw:das-f38217f`, digest `sha256:d9d157826beb152e0d4f5183ed69ac6acff30b65267a599db68bb6fe625efe2c`, size approximately 2.34 GB
- Full construction and validation evidence: [`artifacts/omega-1020-uplift.md`](artifacts/omega-1020-uplift.md)
- ARC-AGI benchmark: https://github.com/fchollet/ARC-AGI
- ARC-AGI REST API (field report): https://github.com/ktfh-claw/ARC-AGI

## Live deployment state (as of 2026-10-07)

| Property | Value |
|---|---|
| Container | `omega-curiosity` |
| Image | `omegaclaw:das-f38217f` (approximately 2.34 GB; `sha256:d9d157826beb152e0d4f5183ed69ac6acff30b65267a599db68bb6fe625efe2c`) |
| Source | `ktfh-claw/OmegaClaw-Core`, branch `uplift-v0.1.20-pr358` at `f38217fa6b34a277cd4c0e780d2340af85eb4f67` |
| Provider | ASIOne / `asi1-ultra` |
| Embedding provider | Local |
| Channel | Telegram |
| Campaign mode | Opt-in autonomous Telegram wakes enabled by the bare `telegramAutonomousWake` launch argument; upstream/default message-driven behavior remains available when omitted. |
| Mission | Research Fetch.ai use cases and existing projects, then continue open-ended decentralized-AI research using arXiv papers and Substack posts; prompt stored in the campaign memory volume. |
| Network | Default bridge + internal DAS client network (`omega-das-integration-client`) |
| Omega local persistence | **Enabled** — campaign volume mounted at `/PeTTa/repos/Omega/memory` after the OMEGA-468 path migration. |
| DAS read integration | **Enabled** — `OMEGA_DAS_ENABLED=1`; the registered `das-retrieve` tool performs bounded reads through the internal read proxy. |
| DAS writes | **Not a live agent capability.** The supported path is the operator import runbook; `&persistent` must not be reported as a DAS write. |
| Notes | DAS tooling provenance: `ktfh-claw/das-toolbox` branches `omega-das-integration` at `d9e136d` and `omega-das-write-integration` at `bc9bf10` (importer reviewed at `dfccfae`). Before uplift, the latest corpus import extracted 336 unique facts (316 previously covered, 20 new, 0 dropped); all 20 new facts and provenance were independently verified through both the datastore and read proxy. |

## Omega v0.1.20 uplift

The live deployment was uplifted on 2026-10-06 and received its final autonomous-wake fixes on 2026-10-07. Because upstream v0.1.20 did not contain the still-open PR #358, the deployed fork merges v0.1.20, PR #358's native tools API, and the fork's guarded ARC, read-only DAS, and nginx changes. It also adds a default-off Telegram autonomous-wake option and runtime-tested fixes for two production regressions found while enabling it. The exact construction, test evidence, deployment configuration, wake-fix journey, and live validation matrix are recorded in [`artifacts/omega-1020-uplift.md`](artifacts/omega-1020-uplift.md).

The DAS integration reference is [`artifacts/omega-das-integration.md`](artifacts/omega-das-integration.md), and the live operator write path is documented in [`artifacts/operator-das-import-runbook.md`](artifacts/operator-das-import-runbook.md). The historical PR #358 container build procedure is preserved in [`artifacts/container-build.md`](artifacts/container-build.md) for reference.

## Related repositories

- Omega Claw Core: https://github.com/ktfh-claw/OmegaClaw-Core
- DAS toolchain: https://github.com/ktfh-claw/das-toolbox

## Bottom line

The infrastructure and autonomous tooling were validated, including one correct autonomous ARC solution, active local Omega persistence, a verified bounded DAS read path, and a separately gated DAS import path executed three times in production. The uplifted live deployment uses ASI:One `asi1-ultra`; the live agent does not write directly to DAS. Historical free-router reasoning limitations still apply to the earlier campaign results.

> This is a field report. It intentionally does not claim a reproducible one-command deployment while PR #358 remains an externally merged fork change rather than part of the validated upstream release.
