# Omega agent + bounded read-only Distributed AtomSpace (DAS) integration

**Canonical task:** `omega-das-integration`
**Status:** read-only retrieval lane validated historically; opt-in and disabled by default. The live Omega container on private infrastructure is **not** currently attached to the DAS client network, so DAS retrieval is not enabled on the running instance. The steps below document what was validated so the lane can be re-deployed and re-tested later.

## What this integration is (and is not)

- **Is:** a narrow, opt-in Python retrieval skill that talks to a **read-only JSON proxy** on a private Docker network; the proxy forwards bounded pattern queries to the DAS query engine.
- **Is not:** an import of `hyperon-das` into Omega's process, a full knowledge import, or an autonomous inference agent. The DAS query engine itself is a multi-service stack, but the agent-only view is a single HTTP `POST /v1/query` endpoint.

**Operational principle:** the agent never writes. MongoDB and Redis state must be identical before and after an adapter call, and no backend network host is reachable from the Omega client container.

## Source provenance (distinct from the PR #358 runtime image)

| Component | Public reference |
|---|---|
| Omega read-only DAS adapter (Python skill) | `https://github.com/ktfh-claw/OmegaClaw-Core`, branch `omega-das-integration` at `fee679c3702e76c5c64f1a3113b3904346e1bb5c` |
| Baseline adapter | same repo, commit `0ba45fd210c8e44699e56e4afe3832e424214226` |
| nginx startup fix (master root, unprivileged workers) | same repo, commit `bd6638a3fd492348da5d32291a163c6dad1a95f0` |
| DAS deployment lane (compose, config, preflight, tests) | `https://github.com/ktfh-claw/das-toolbox`, branch `omega-das-integration` at `d9e136d0f2a9094e0243364db34cb31c8dc1ed25` |
| DAS campaign write/import lane | same repo, branch `omega-das-write-integration` at `bc9bf1002e34a8f7dfbd82f69452dfe75d49c5ea` |
| DAS upstream | `https://github.com/singnet/das-toolbox` |

These commits are the **source of the adapter/deployment work only**. They are separate from the PR #358 build that ships the live container (`c193ab39857944017e067b426779d66113649313` → image `omegaclaw:pr358-c193ab3`).

## Services and topology

DAS is a self-contained multi-service system. The deployment lane runs only the data plane, on two private networks with **no host ports published**:

- `client` network: read proxy, query engine, Omega client/adapter.
- `backend` network: query engine, attention broker, MongoDB, Redis.

| Service | Role |
|---|---|
| MongoDB | AtomDB persistence |
| Redis | Attention Broker state; append-only persistence, protected mode disabled only within `backend` |
| Attention broker | ECAN-based result prioritization |
| Query engine | Pattern-token dispatch and answer assembly; `POST /v1/query` |
| JSON read proxy | Bounded request validation, reverse callback delivery, normalized JSON response (`200 {answers:[],count:0,truncated:false}`) |

### Deployment checks

Before considering the lane usable:

1. `docker compose up -d` — the operator profile must **not** start; if it does, inspect `docker compose ps`.
2. `docker compose` policy tests: every network `internal=true`; every container reports empty `PortBindings`.
3. Preflight: rendered `config/config.json` matches the digest-only `.env` inputs; all image digests resolve at build time.
4. Services: MongoDB/Redis report healthy; query engine and attention broker report their own peers; no listener binds to the host.
5. Read-proxy: `POST /v1/query` with a structurally valid pattern returns `200` within seconds, not a 502/timeout.

## The Omega adapter skill

Placed as a narrow Python module and called from one MeTTa skill, advertised only when explicitly enabled:

- **Default disabled** — `OMEGA_DAS_ENABLED=0` by default; `das-retrieve` is not advertised in `(getSkills)` and no endpoint is resolved, so startup fails closed and existing prompt behavior is preserved.
- **Opt-in** — enable via `OMEGA_DAS_ENABLED=1` and an exact proxy origin, e.g. `OMEGA_DAS_PROXY_ORIGIN=http://das-read-proxy:8080/v1/query`.
- **Result marking** — responses are normalized as untrusted: `DAS_RETRIEVE_OK untrusted=true count=N truncated=false results=[...]`.
- **Immutability** — verified MongoDB and Redis state are unchanged after a call; no write API is exposed.

## Structured query example

Valid pattern queries follow the DAS token grammar. Example:

```json
POST /v1/query
{
  "tokens": [
    "LINK_TEMPLATE", "Expression", "3", "NODE", "Symbol",
    "Similarity", "NODE", "Symbol", "\"human\"",
    "VARIABLE", "Y"
  ],
  "max_answers": 5
}
```

Response: `{"answers": [...], "count": 0, "truncated": false}` (empty when no matching atoms exist; the AtomDB must be seeded separately).

**Invalid inputs:** bare or unstructured tokens (for example a single term with no grammar) are rejected by the query engine but historically failed to send the completion callback, causing the proxy to wait until its timeout returns `502`. Always use grammatically valid patterns and treat timeouts as evidence of a bad query, not engine failure.

## Tests

- **Adapter unit/integration tests** in the Omega adapter repo run without a live DAS cluster when `OMEGA_DAS_LIVE_TEST=0`; live end-to-end checks run only with `OMEGA_DAS_LIVE_TEST=1` against a seeded marker atom, and skip automatically when unset.
- **DAS proxy and client tests** verify bounded request shape, callback delivery, JSON normalization, and network policy.
- **Deployment tests** verify compose policy (internal networks, no published ports) and preflight digest resolution.

## Operator-only write/import lane (separate, gated)

A bounded, operator-only campaign import path exists in the DAS toolbox under `deploy/omega-das-integration/`: `scripts/campaign_import.py` (strict validator, offline volume backup, one-shot `db_loader`, manifest, `loaded-unverified` semantics). It is designed to be a separately authorized lane: the operator profile is never started by normal `up`, and data import requires explicit authorization. It is documented, not assumed to be deployed.

## What was actually deployed vs. design-only

| Item | State |
|---|---|
| DAS data-plane compose + config + preflight | Deployed and validated historically on the verification lane; internal-only, no host ports. |
| JSON read proxy + query engine + attention broker + Mongo/Redis | Validated: valid pattern queries returned `200` in ~1–2 s; callback delivery and normalization confirmed in logs. |
| Adapter tests (no live cluster) | Ran, passed. |
| Adapter on the Omega verification image | Ran a live private-network structured query successfully with `OMEGA_DAS_ENABLED=1`; confirmed read-only invariants. |
| Integration into the **live** `omegaclaw:pr358-c193ab3` container | **Not enabled.** The live container is on the default bridge only and does not have DAS enabled. The current branch/README state should be read as "historically validated, live deployment disabled." |

## Limitations

- The adapter requires a seeded AtomDB to return non-empty results; an empty query is a correct answer, not a defect.
- Query grammar errors can produce a proxy-level timeout rather than an immediate error.
- DAS is a multi-service stack with operational surface (several stateful containers, credential files, rolling digests); pinning digests and running policy tests are mandatory.
- Native MeTTa/NAL inference is a separate concern and not required by this integration path.

---
*Last updated: 2026-10-05.*
