# Path B architecture — agent-direct Omega↔DAS persistence (config-only)

**Canonical task:** `omega-das-bridge`
**Design source:** Omega-DAS Integration Re-evaluation report (2026-10-19), §10 — validated against the live OVH deployment during the re-evaluation campaign (all components individually live-verified; see the report's §7 experiments E1–E3 and evidence index).

## 1. Objective

Let the running Omega agent (`omega-curiosity`) persist campaign knowledge into DAS **directly** — matching the intended Hyperon/OpenCog/SingularityNET architecture in which agents are first-class DAS writers. Everything this bridge repo contributes is a **runtime-mounted artifact** (plugins, config overlays, prompts, adapter files); the DAS plane is stock upstream pinned-digest images. One correction (2026-10-20, iteration 31 — truth-fixed after a provenance audit): the agent image is a **fork build**, not a stock upstream image — see §Agent-image provenance below.

| Upstream component | Role in the bridge | Source of truth |
|---|---|---|
| DAS server stack (MongoDB, Redis, attention-broker, query-engine) | datastore + query plane | `singnet/das` (server) via `das-toolbox`/compose images |
| `atomdb-broker` | the **only** runtime write API (`das-cli atomdb-broker start`) | `singnet/das` |
| python client `AtomDBProxy.add_atoms` | write client library | `singnet/das` `3rd_party_slots/python_client` |
| `das-metta-parser` (`syntax_check` + `db_loader`) | bulk/history load lane | `singnet/das-metta-parser` |
| read proxy (bounded facade) | read plane for the agent (our component, config-only) | local build, stock query-engine behind it |
| Omega/PeTTa (fork image, see provenance note) | the agent; bridge artifacts mounted in | [`ktfh-claw/OmegaClaw-Core`](https://github.com/ktfh-claw/OmegaClaw-Core) @ `f38217f` = upstream `singnet/Omega` v0.1.20 + PR #358 + enumerated fork deltas; built as image `omegaclaw:das-f38217f` (upstream publishes no image) |

## 2. Data flows

### Write path (new)

```text
Agent turn (skill: das-write)
  1. MeTTa expression(s) to persist  →  parse to Node/Link atom tuples
  2. AtomDBProxy.add_atoms(atoms) over the service bus → atomdb-broker → MongoDB
  3. Read-back verification: query the stored handles via the read path
     (query-engine → read-proxy) — handles + targets must match
  4. Return verified handles to the agent; log write (timestamp, content, handles)
```

Non-negotiables (live-discovered, re-eval campaign E1):
- `add_atoms` is **fire-and-forget**: the returned handles are client-side constructions, not acknowledgements. Read-back verification is mandatory, never optional.
- Atoms written via the bus carry **no `metta_expression`** field — verification must use handles/targets, not expression text.
- The broker **must** be reachable by its network name from the client container (see §5 gotchas).

### Read path (fixed 2026-10-20: adapter v2 + das-read plugin)

```text
das-retrieve skill → (plugin-mounted das_skills v2 adapter) → read-proxy → query-engine → attention-broker → MongoDB/Redis
```

- **Working shape:** MeTTa-mode patterns `{"metta": "(Inheritance (Concept \"x402\") $X)", "max_answers": 10}` (mandatory `$variable`; ground patterns never complete on the pinned engine); `{"query": ...}` lenient alias; structural `LINK_TEMPLATE` tokens still accepted. The v1 adapter's gates (exact-key request schema forbidding metta mode; response schema rejecting the proxy's `mode` key) made the read path unreachable end-to-end — root-caused + fixed 2026-10-20 iteration 29, live-verified.
- **Config-only binding:** the `das-read` plugin (mounted `:ro`) rebinds the `das-retrieve` clause to the mounted v2 module — same remove-then-add single-definition invariant as `das-write`. The `src/das_skills.py` `:ro` file overlay in `start.sh` is a redundant fallback with identical bytes.
- **Workaround applied at config level:** the stock python client sends a typo'd parameter (`user_metta_as_query_tokens`) — the bridge's client wrapper sends the correct spelling until the upstream fix lands (see [contributions](contributions/README.md) #2).

### Agent-image provenance (truth note, 2026-10-20)

- Upstream `singnet/Omega` **publishes no container image** (verified: no `ghcr.io/singnet/omega`, no `trueagi/omega` manifests; CI builds without pushing) — any deployment builds from source.
- The deployed image is the **ktfh-claw/OmegaClaw-Core fork build** (`omegaclaw:das-f38217f`, upstream v0.1.20 + PR #358). Fork deltas (all pre-campaign agent infrastructure, enumerated for honesty):
  - `providers/asione.py` — ASI:One LLM provider (upstream has no ASI:One provider)
  - Telegram autonomous-wake line (`1808b94`/`dd4e0a1`/`f38217f`) — wake gating absent upstream
  - ARC lane + nginx proxy key isolation + OpenRouter-free provider (pre-bridge campaign work)
  - the original `das-retrieve` skill clause + v1 adapter (`src/das_skills.py`, Oct-3) — **now superseded at runtime by the mounted das-read plugin / v2 adapter**
- Bridge-owned artifacts are **all runtime mounts** (`:ro`): das-write plugin, das-read plugin, plugins.yaml overlay, config overlay, boot prompts, adapter files. Nothing in the running image is bridge-owned except the enumerated deltas above.
- Consequence for validity: every bridge acceptance result (write lane ×3 green loops, wrapper 99.17%, live agent writes, read-path fix 20/20) is genuine — the bridge components are mounts over an image whose deltas are enumerated; the DAS plane is 100% upstream.

### Bulk/history lane (wrapper)

```text
history.metta (Omega memory volume)
  → segmentation into structural entries
  → per-entry syntax_check gate (upstream parser image)
  → newline-escape fallback; skip documented shell-quirk entries (~0.7%)
  → provenance decoration (Campaign/Source/Epoch atoms — ours, not upstream schema)
  → db_loader (stock image) → MongoDB
```

This replaces the retired `campaign_import.py` operator lane for bulk loads; provenance atoms are added by the wrapper, not by mutating upstream code.

## 3. Interface contracts

- **Skill I/O (`das-write`):** input = MeTTa expression(s) + optional provenance metadata; output = verified handle list or explicit failure with stage. The skill never returns success without read-back.
- **Handles:** Mongo document `_id`/`handle` values as produced upstream (MD5-based, deterministic).
- **Provenance schema (bridge-owned):** atoms linking each persisted fact to campaign id, source, and store epoch — implemented as regular atoms via the same write path; documented in `skills/das-write/`.
- **`&persistent` hook (implemented, iteration 11):** the `das-write` Omega plugin rebinds the `metta` skill clause — the stock clause is removed and a bridged clause installed (single-definition invariant: a second clause would double-evaluate). `add-atom &persistent <balanced-expression>` routes to the write-bridge `/v1/write` endpoint with mandatory read-back verification; `remove-atom &persistent` returns a truthful not-supported status (v1 does not bridge deletion); when the stock config key `dasWriteEnabled != 1` nothing changes (stock clause stays in place, the Python module double-gates on every call). Config keys (not raw env vars — the stock image entrypoint scrubs the agent environment to an allowlist) resolve through Omega's stock config machinery: command line > `OMEGA_<key>` env > config.yaml. Plugin + overlay under `deploy/omega/plugins/das-write/`.

## 4. Deployment topology (validated host: OVH `omega-experimental`)

- Internal-only Docker networks: `client` (read-proxy ↔ query-engine), `backend` (QE ↔ attention-broker ↔ Mongo/Redis), plus the broker's bus network.
- The agent container attaches **only** to the DAS client network + broker bus; it holds no DB credentials.
- Compose files + scripts in this repo reproduce the lane from scratch (see `docs/runbook.md`).

## 5. Deployment invariants (live-discovered — violating any of these breaks the lane)

1. **Broker binds `0.0.0.0`** (not a hostname) in multi-network docker deployments.
2. **Clients join the broker directly** (peer-id = broker DNS name). Never route `atomdb` commands via the query-engine — an unregistered-command crash takes the QE container down (upstream defect #1 in [contributions](contributions/README.md)).
3. **Client callback-peer rewrite host = broker name** for atomdb commands.

## 6. Security model

- **No published ports** for any DAS service on the host; access only via internal networks. UFW on the host denies all DAS-related ingress.
- **Narrow write surface:** exactly one skill (`das-write`) can write; all other agent code retains read-only access.
- **Auditability:** every write logged locally (content + handles + timestamp) → revocable by handle; write claims credible only with broker + read-back evidence.
- **Credential isolation:** agent container has no Mongo/Redis credentials; it cannot bypass the bus.
- **Revocation:** handles are stable → targeted deletion is a documented operator action.

## 7. Explicitly rejected alternatives (from the re-eval)

- **Path A** (port Omega to hyperon-experimental + DAS space): upstream write stubs are `todo!()`; interpreter port is XL effort. Rejected.
- **Path C** (PeTTa mork-backed `&persistent`): mork_ffi not built; source-DBMS write-back unimplemented upstream. Held.
- **Link-creation/evolution agents:** not a general write surface; optional later add-on.
