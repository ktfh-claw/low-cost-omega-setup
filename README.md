# Low-cost Omega Setup → Omega–DAS Bridge (Path B)

**Canonical task:** `omega-das-bridge`
**Status:** ACTIVE — campaign started 2026-10-19 21:59 UTC (Balázs directive)
**Live progress doc (main reporting interface):** [Omega-DAS Integration Re-evaluation — Full Campaign Report](https://docs.google.com/document/d/1Pw5diOmac40Abc8_D1CG0_b3OrOHntq1BSzOv2H63dM/edit) — updated every iteration
**Live status page in this repo:** [`docs/status.md`](docs/status.md)

This repository is the **bridge repo** for the Omega↔DAS integration: a **standalone, config-only** deployment + automation layer that lets the Omega agent persist campaign knowledge **directly into the Distributed AtomSpace (DAS)**, aligned with the intended Hyperon/OpenCog/SingularityNET architecture (agents write to DAS).

**Agent-image provenance note (truth-corrected 2026-10-20, iteration 31):** the deployed agent image is a **fork build of upstream Omega** — `omegaclaw:das-f38217f` = [`ktfh-claw/OmegaClaw-Core`](https://github.com/ktfh-claw/OmegaClaw-Core) @ `f38217f`, based on upstream `singnet/Omega` v0.1.20 + PR #358. Upstream **publishes no container image** (verified 2026-10-20: no `ghcr.io/singnet/omega`, no `trueagi/omega` manifests; upstream CI builds without pushing), so the image is built from source. The fork deltas are enumerated in [`docs/architecture.md §Agent-image provenance`](docs/architecture.md). **Everything this bridge repo contributes is mounted at runtime** (plugins, overlays, prompts, adapter files) — nothing in the image is bridge-owned except the enumerated pre-campaign agent-infrastructure deltas (ASI:One provider, Telegram autonomous-wake line, ARC lane, the original das-retrieve adapter — now superseded at runtime by the mounted `das-read` plugin/v2 adapter). The DAS plane is 100% stock upstream pinned-digest images.

It supersedes the earlier "operator-gated DAS import" design documented here before 2026-10-19. That model is retired: the write path is becoming agent-direct, with narrow, logged, read-back-verified writes through the upstream `atomdb-broker` service. The old documents are preserved under [`historical/`](historical/) for provenance.

---

## What this repo provides

1. **Deployment automation** — everything needed to stand up the DAS stack + broker + read proxy + bridge components from scratch on a private host (compose files, configs, scripts, runbook).
2. **`das-write` skill** — Omega-facing write skill: MeTTa in → atoms → `AtomDBProxy.add_atoms` via the service bus → mandatory read-back verification → verified handles returned to the agent.
3. **Bounded read path** — read proxy with the MeTTa-query parameter workaround applied (config-level; consumed from upstream once the client typo fix lands upstream).
4. **Thin import wrapper** — bulk/history loads via the stock upstream parser + `db_loader` image, with segmentation, syntax gating, newline-escape fallback, and provenance decoration.
5. **`&persistent` interception hook** — the agent's existing persistence vocabulary becomes durable, verified DAS writes.
6. **Upstream contribution lane** — evidence-backed issue drafts and fork-local PRs for every defect this campaign found in upstream code (see [`docs/contributions/`](docs/contributions/README.md)).

## Document map

| Document | Purpose |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Path B design: components, data flows, interface contracts, topology, security model. |
| [`docs/campaign-plan.md`](docs/campaign-plan.md) | The overall task: directive, phases, deliverables, acceptance criteria, tracking rules. |
| [`docs/status.md`](docs/status.md) | Live status: iteration log with evidence links. Updated every cron iteration. |
| [`docs/contributions/README.md`](docs/contributions/README.md) | Upstream contribution ladder + per-contribution status (issues/PRs on forks). |
| [`docs/runbook.md](docs/runbook.md) | From-scratch deployment runbook (target: any operator can rebuild the whole lane). |
| [`historical/`](historical/) | Pre-bridge campaign documents (superseded operator-gated import lane, uplift provenance, experiment reports). |

## Architecture summary

```text
Omega agent (omega-curiosity, PeTTa/Omega upstream image)
  ├─ read:  das-retrieve skill → read-proxy → query-engine → attention-broker → MongoDB/Redis
  └─ write: das-write skill (this repo) → service bus → atomdb-broker → MongoDB
                └─ mandatory read-back verification via the query path
```

Full design, contracts, and the three live-discovered deployment invariants: [`docs/architecture.md`](docs/architecture.md).

## Security model (short form)

- No DAS ports published to the host; all traffic stays on internal Docker networks.
- Writes are narrow (single skill), logged (handle + content), and revocable (handles → delete).
- Write claims are only credible with broker evidence **plus** independent read-back verification.
- No database credentials inside the agent container; the agent talks to the bus, not the DB.

## Rules of engagement (standing, from the directive)

- All work stays on the `ktfh-claw` forks and this repo's `main` branch; **nothing upstream without explicit approval**.
- New code → pushed to the fork repos, with GitHub links recorded in the live Google Doc.
- Upstream issue/PR content is drafted and, where executable, opened **only in the forked repositories** first.
- Outdated fork branches are archived/deleted as they become superseded (see [`docs/contributions/README.md`](docs/contributions/README.md)).
- The Google Doc is the main reporting interface; `docs/status.md` mirrors it per iteration.
