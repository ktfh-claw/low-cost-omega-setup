# Low-cost Omega Setup

Documentation for running a continuously operating [Omega](https://github.com/singnet/Omega) agent on private infrastructure with a low-cost LLM route, and for attaching a bounded, read-only [Distributed AtomSpace (DAS)](https://github.com/singnet/das-toolbox) retrieval layer for RAG-style tool use.

The canonical campaign label for the run documented here is **RKGI**; the evaluated task benchmark and artifacts themselves are ARC-AGI-labelled. A separate, self-contained status report is in [`artifacts/status-2026-10-05.md`](artifacts/status-2026-10-05.md).

---

## Document map

| Document | Purpose |
|---|---|
| `README.md` (this file) | High-level overview, provenance, and links. |
| [`artifacts/experiment-report.md`](artifacts/experiment-report.md) | Full experiment report: test matrix, failures, safety controls, retest criteria. |
| [`artifacts/status-2026-10-05.md`](artifacts/status-2026-10-05.md) | Separate status report for the RKGI-ARC campaign conclusion and the final resumed task. |
| [`artifacts/omega-das-integration.md`](artifacts/omega-das-integration.md) | Reproducible notes for the Omega agent + read-only DAS integration lane. |

## Architecture overview

```text
Omega agent on private infrastructure
  ├─ scheduled autonomous wake loop (no inbound message required)
  ├─ ASI:One (asi1) model via PR #358 native tools API
  ├─ arc-read / arc-submit Omega skills (ARC-AGI-labelled)
  └─ optional read-only DAS retrieval adapter
       ├─ bounded, opt-in Python skill (advertised only when enabled)
       ├─ private JSON read proxy on an internal Docker network
       └─ DAS services: MongoDB, Redis, attention broker, query engine
            (internal backend/client networks, no host ports published)
```

A host-side capability proxy separates evaluation state from the agent. It enforces task-scoped authorization and expiry, strict `{outputs, reasoning}` payload validation, rectangular 1–30×30 integer grids, duplicate-candidate rejection, and an atomic three-attempt budget, failing closed when `/tasks/next` and the authorized task disagree.

## Campaign conclusion

The campaign included three earlier verified ARC task solves during the broader run. A final resumed task, `05a7bcf2`, was an **incomplete run**: 0/3 attempts used, no submission, no solve. ASI:One tool calling continued to work without auth, quota, or rate-limit failures, but reasoning/output budget exhaustion and a failed task-to-Python handoff prevented completion. There is no evidence of material native MeTTa execution. See [the status report](artifacts/status-2026-10-05.md) for the distinct historical versus final-run accounting.

## Current conclusions

- Stock Omega scheduled wake works headlessly and can perform autonomous provider calls without a new human message.
- ASI:One (`asi1`) works out of the box with PR #358 native tool calls (`provider=ASIOne model=asi1 finish_reason=tool_calls`).
- Free-router LLM output is variable and not reliable as a continuous solver.
- PR #358 replaces text-command emulation with the native tools API, but does not by itself guarantee ARC reasoning quality; at the reviewed head, skill parameters were typed as strings.
- The bounded read-only DAS retrieval adapter was validated historically on a separate verification image; the live Omega container is **not** currently attached to the DAS client network, so DAS retrieval is not enabled on the running instance.

## Reproducible setup

Requirements: Docker Engine and Docker Compose, or a single host with Python 3.10+ and network access to the provider. The exact versions validated are documented in the per-artifact provenance sections.

1. Build a PR #358 image (see provenance below) or use an upstream release once PR #358 lands.
2. Configure provider auth (ASI:One) and ARC tool credentials through read-only mounted secret files or environment variables; never commit secrets.
3. Configure the optional DAS read-only lane (disabled by default) if retrieval-augmented tool use is desired.
4. Launch the autonomous wake loop.

## Source and image provenance

- Omega upstream: https://github.com/singnet/Omega
- Omega PR #358 (native tools API): https://github.com/singnet/Omega/pull/358
- Omega PR #358 head (fork): `c193ab39857944017e067b426779d66113649313` in `vsbogd/Omega`
- Omega image used for the latest run: `omegaclaw:pr358-c193ab3`, runtime image ID/digest `sha256:f78dbd811c23081aecdf1b5a46fb83d848b6a9c78b651b9218bd973e0dfdb491`
- At the time of this report, PR #358 and [issue #365](https://github.com/singnet/Omega/issues/365) remain open.
- ARC-AGI benchmark: https://github.com/fchollet/ARC-AGI
- ARC-AGI REST API (field report): https://github.com/ktfh-claw/ARC-AGI

## DAS integration provenance

These components are tracked on the project's public forks and have independent provenance from the Omega PR #358 runtime image:

- Omega adapter (read-only DAS retrieval skill) on `ktfh-claw/OmegaClaw-Core`, branch `omega-das-integration`, commit `fee679c3702e76c5c64f1a3113b3904346e1bb5c`.
- Alternative baseline adapter commit `0ba45fd` plus an nginx startup fix (`bd6638a`, equivalent to [PR #365](https://github.com/singnet/Omega/issues/365) nginx discussion).
- DAS deployment lane on `ktfh-claw/das-toolbox`, branches `omega-das-integration` (commit `d9e136d`) and `omega-das-write-integration` (commit `bc9bf10`).

See [`artifacts/omega-das-integration.md`](artifacts/omega-das-integration.md) for the build/test steps, deployment checks, and limitations.

## Related repositories

- Omega Claw Core: https://github.com/ktfh-claw/OmegaClaw-Core
- DAS toolchain: https://github.com/ktfh-claw/das-toolbox

## Bottom line

The infrastructure and autonomous tooling were validated, including one correct autonomous ARC solution and a separately verified read-only DAS retrieval path. Free LLM inference and reasoning quality remain the limiting constraints and are not sufficient to publish as a dependable, continuously operating free-LLM setup.

> This is a field report. It intentionally does not claim a reproducible one-command deployment until PR #358 lands in an official release and free-router output quality improves.
