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

## Architecture overview

```text
Omega agent (`omega-curiosity`)
  ├─ scheduled autonomous wake loop (no inbound message required)
  ├─ ASI:One (asi1) model via PR #358 native tools API
  ├─ MeTTa: `add-atom &persistent …`
  │    └─ local Omega persistent space + mounted campaign memory files
  └─ optional DAS service (separate compose deployment)
       ├─ private client/backend Docker networks
       ├─ bounded read proxy → query engine → MongoDB/Redis
       └─ separately authorized `campaign_import.py` operator write/import path
```

### Two persistence planes — do not conflate them

1. **Omega local persistence.** The running agent issues MeTTa such as `add-atom &persistent …` and appends campaign state under `./repos/Omega/memory`. The live logs prove this path is active. It is persistence inside Omega/PeTTa, not a network write to the Distributed AtomSpace.
2. **DAS persistence.** The DAS stack persists atom data through its own MongoDB/Redis-backed services. The documented write path is a bounded, operator-authorized import (`campaign_import.py`); it is deliberately not exposed as an autonomous agent tool. A DAS write claim requires import/loader evidence plus a datastore-side before/after check.

The distinction prevents a common false positive: seeing `&persistent` in an Omega log does **not** establish that the atom reached DAS.


## Campaign conclusion

The campaign included three earlier verified ARC task solves during the broader run. A final resumed task, `05a7bcf2`, was an **incomplete run**: 0/3 attempts used, no submission, no solve. ASI:One tool calling continued to work without auth, quota, or rate-limit failures, but reasoning/output budget exhaustion and a failed task-to-Python handoff prevented completion. There is no evidence of material native MeTTa execution. See [the status report](artifacts/status-2026-10-05.md) for the distinct historical versus final-run accounting.

## Current conclusions

- Stock Omega scheduled wake works headlessly and can perform autonomous provider calls without a new human message.
- ASI:One (`asi1`) works out of the box with PR #358 native tool calls (`provider=ASIOne model=asi1 finish_reason=tool_calls`).
- Free-router LLM output is variable and not reliable as a continuous solver.
- PR #358 replaces text-command emulation with the native tools API, but does not by itself guarantee ARC reasoning quality; at the reviewed head, skill parameters were typed as strings.
- The bounded DAS adapter and the separately gated DAS campaign-import path were validated historically on a dedicated integration lane. The live `omega-curiosity` container is on the default `bridge` network only; it has no DAS adapter or DAS environment settings. Its observed `&persistent` operations are local Omega persistence, not direct DAS writes.

## Reproducible setup

Requirements: Docker Engine and Docker Compose, or a single host with Python 3.10+ and network access to the provider. The exact versions validated are documented in the per-artifact provenance sections.

1. Build a PR #358 image (see provenance below) or use an upstream release once PR #358 lands.
2. Configure provider auth (ASI:One) and ARC tool credentials through read-only mounted secret files or environment variables; never commit secrets.
3. Configure the optional DAS read-only lane (disabled by default) if retrieval-augmented tool use is desired.
4. If DAS data must be seeded or imported, run the separately authorized operator import workflow; never grant the autonomous Omega loop a direct DAS write endpoint.
5. Launch the autonomous wake loop.

## Source and image provenance

- Omega upstream: https://github.com/singnet/Omega
- Omega PR #358 (native tools API): https://github.com/singnet/Omega/pull/358
- Omega PR #358 head (fork): `c193ab39857944017e067b426779d66113649313` in `vsbogd/Omega`
- Omega **live deployment version**: v0.1.11.1-899-gc193ab3 (reported in Telegram and confirmed in container)
- Omega **source commit on disk**: `7037f4c2ad378c52fc328004fe216d5118b674f0`
- Omega image used for the latest run: `omegaclaw:pr358-c193ab3`, runtime image ID/digest `sha256:f78dbd811c23081aecdf1b5a46fb83d848b6a9c78b651b9218bd973e0dfdb491`
- Upstream releases available: v0.1.19 (stable), v0.1.20-rc (release candidate); both contain PR #358 changes
- At the time of this report, PR #358 and [issue #365](https://github.com/singnet/Omega/issues/365) remain open.
- ARC-AGI benchmark: https://github.com/fchollet/ARC-AGI
- ARC-AGI REST API (field report): https://github.com/ktfh-claw/ARC-AGI

## Live deployment state (as of 2026-10-05)

| Property | Value |
|---|---|
| Container | `omega-curiosity` |
| Image | `omegaclaw:pr358-c193ab3` |
| Omega version | v0.1.11.1-899-gc193ab3 |
| Base | PR #358 fork (`vsbogd/Omega` at `c193ab3`) |
| Provider | ASIOne / `asi1` |
| Network | Default bridge only |
| Omega local persistence | **Enabled** — recent logs include successful `add-atom &persistent …` operations and campaign-state updates. |
| DAS read integration | **Not enabled on this container** — no DAS networks, no DAS env vars, no adapter in container. |
| DAS writes | **Not a live agent capability.** The supported path is separately authorized operator import; `&persistent` must not be reported as a DAS write. |
| Notes | DAS read/write tooling was validated historically on separate integration lanes (`ktfh-claw/das-toolbox` branches `omega-das-integration` at `d9e136d`, `omega-das-write-integration` at `bc9bf10`; `ktfh-claw/OmegaClaw-Core` at `bd6638a`). The live container is currently on default bridge only. |

## Upgrade path to Omega v0.1.20

A new issue has been created in this repository to track upgrading the base image to Omega v0.1.20 once it is fully released. See `.github/ISSUE_TEMPLATE/upgrade-base-image.md` for the acceptance criteria and current deployment state snapshot.

When v0.1.20 is fully released, the workflow will be:
1. Rebuild the Docker image from `singularitynet/omega:v0.1.20` (or equivalent release tag)
2. Verify PR #358 changes are present
3. Re-validate: autonomous wake loop, ASI:One tool calling, ARC skills
4. Re-validate DAS read-only lane (opt-in) on the new image
5. Update `README.md` provenance section with new image digest and version
6. Switch live deployment after validation

Historical DAS integration provenance is preserved in `artifacts/omega-das-integration.md` and `artifacts/container-build.md` for reference.

## Related repositories

- Omega Claw Core: https://github.com/ktfh-claw/OmegaClaw-Core
- DAS toolchain: https://github.com/ktfh-claw/das-toolbox

## Bottom line

The infrastructure and autonomous tooling were validated, including one correct autonomous ARC solution, active local Omega persistence, a separately verified DAS read path, and a separately gated DAS import path. The live agent does not currently write directly to DAS. Free LLM inference and reasoning quality remain the limiting constraints and are not sufficient to publish as a dependable, continuously operating free-LLM setup.

> This is a field report. It intentionally does not claim a reproducible one-command deployment until PR #358 lands in an official release and free-router output quality improves.
