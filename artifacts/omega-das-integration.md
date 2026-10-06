# Omega persistence and Distributed AtomSpace (DAS) integration

**Canonical task:** `omega-das-integration`
**Scope:** private, internal-only DAS deployment; bounded read access and separately authorized import/write operations.
**Important:** Omega local MeTTa persistence and DAS persistence are different systems. This document records the interface boundary and the evidence required for each claim.

## Status at the documented deployment snapshot (2026-10-05)

> **Current live state (updated 2026-10-06):** the sections below describe the 2026-10-05 snapshot taken before the DAS-enabled cutover. Since then, `omega-curiosity` was redeployed on the DAS-enabled image `omegaclaw:das-bd6638a`, attached to the internal DAS client network, and performs **bounded DAS reads** through the deployed read proxy. DAS writes remain operator-only via the [import runbook](operator-das-import-runbook.md); the agent still has no write capability. Two operator imports have been executed and independently verified (`omega-curiosity-20261005-final`, `omega-curiosity-20261006`). The snapshot text is retained as the integration-lane record.

- `omega-curiosity` is the Telegram-facing autonomous Omega agent, running `omegaclaw:pr358-c193ab3`.
- Its logs show successful `add-atom &persistent …` operations and campaign-state appends. These are **local Omega/PeTTa persistent-space writes**.
- The live container is on Docker's default `bridge` network only. It has no DAS adapter files, DAS environment variables, or attachment to the DAS client network. Therefore it **does not directly write atoms to DAS**.
- The DAS stack is a separate internal compose deployment. Its services are running, and Redis reported `DBSIZE 8884` during the snapshot inspection. That counter alone does not attribute any record to `omega-curiosity`.
- A bounded DAS read adapter and a separately gated campaign import/write tool were validated on dedicated integration lanes. They are not automatically enabled merely because the DAS services are running.

## Architecture and trust boundary

```text
Telegram → Omega scheduled loop
             │
             ├─ `metta (add-atom &persistent …)`
             │      └─ local PeTTa/Omega persistent space
             │
             └─ bounded DAS read (live since 2026-10-05 cutover)
                    └─ Omega DAS adapter → internal read proxy → query engine

DAS compose deployment (internal networks only)
  client:  read proxy ↔ query engine
  backend: query engine ↔ attention broker ↔ MongoDB / Redis

Operator-only import: validated corpus → campaign_import.py → offline backup → one-shot db_loader → DAS datastore
```

The Omega agent receives no database credential and no direct datastore route. The query-facing proxy exposes only a constrained `POST /v1/query` endpoint. The import profile is not part of normal `docker compose up`.

## What `&persistent` proves, and what it does not

A log line such as:

```text
(metta "(add-atom &persistent (Inheritance …))")
… RETURN: "true"
```

proves that the Omega-side MeTTa call succeeded in its `&persistent` space. It does **not** prove an HTTP call to the DAS proxy, a `db_loader` invocation, a MongoDB change, or a Redis change.

A claim that an atom was persisted to DAS needs all of the following evidence:

1. the operator import invocation and its validated manifest;
2. the loader result (including any `loaded-unverified` state); and
3. a scoped datastore-side before/after check that identifies the imported marker or atom.

Do not use generic service health, Redis `DBSIZE`, or `&persistent` log text as a substitute for these checks.

## Source provenance

| Component | Reference |
|---|---|
| Omega runtime image | `omegaclaw:pr358-c193ab3`, PR #358 fork commit `c193ab39857944017e067b426779d66113649313` |
| Live Omega on-disk source | `7037f4c2ad378c52fc328004fe216d5118b674f0` (`v0.1.11.1-899-gc193ab3`) |
| DAS-capable Omega source | `https://github.com/ktfh-claw/OmegaClaw-Core` at `bd6638a3fd492348da5d32291a163c6dad1a95f0`; adapter baseline `0ba45fd210c8e44699e56e4afe3832e424214226` |
| DAS deployment/read lane | `https://github.com/ktfh-claw/das-toolbox`, branch `omega-das-integration` at `d9e136d0f2a9094e0243364db34cb31c8dc1ed25` |
| DAS operator import/write lane | same repository, branch `omega-das-write-integration` at `bc9bf1002e34a8f7dfbd82f69452dfe75d49c5ea` |

The DAS-capable source/image lineage is distinct from the live PR #358 image; availability of an image tag is not deployment evidence.

## Read path

The opt-in adapter is a narrow Python skill. When explicitly enabled, it sends grammatically valid DAS token patterns to the internal read proxy:

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

Valid structured requests previously returned `200` in about 1–2 seconds. Bare or malformed token lists can make the query engine omit a completion callback; the proxy then times out (historically `502` after 60 seconds). Results are explicitly untrusted retrieval data, not instructions.

## Write/import path

The supported DAS writer is `deploy/omega-das-integration/scripts/campaign_import.py` in `das-toolbox`. It is intentionally **operator-only** and uses a bounded pipeline. The step-by-step operator procedure (freeze → dry run → delta analysis → apply → independent verification → resume) is documented in [`artifacts/operator-das-import-runbook.md`](operator-das-import-runbook.md), including both validated production runs.

1. validate the input campaign corpus strictly;
2. take an offline volume backup;
3. create an auditable manifest;
4. run the one-shot `db_loader`; and
5. report the resulting `loaded-unverified` state until an independent datastore verification is complete.

This design keeps an LLM-controlled agent out of the write path. It protects the isolated deployment posture: both `client` and `backend` networks remain internal, and no DAS data-plane ports are published to the host.

## Operational verification checklist

### Omega local persistence

- Observe a successful `add-atom &persistent …` return in `omega-curiosity` logs.
- Confirm the expected local campaign-state/history change.
- Report this as **local Omega persistence**, never as a DAS write.

### DAS read

- Ensure the test container is attached only to the private DAS client network.
- Set `OMEGA_DAS_ENABLED=1` and an exact proxy origin only in that test deployment.
- Submit a valid structured pattern; confirm normalized JSON and unchanged datastore state.

### DAS import/write

- Stop the campaign if the import procedure requires an offline corpus snapshot.
- Run only the operator profile and `campaign_import.py` after explicit authorization.
- Preserve the manifest, loader output, and a marker-specific datastore verification.
- Re-run network policy tests: internal networks only; no published data-plane ports.

## Limitations

- DAS service health does not demonstrate that the live Omega agent can read or write it.
- `&persistent` is useful durable agent memory but is not a distributed durability guarantee.
- ~~The live `omega-curiosity` image must be rebuilt/redeployed from the DAS-capable source and explicitly network-attached before it can use even the bounded read adapter.~~ Resolved 2026-10-05: the live container now runs the DAS-enabled image on the client network (read-only).
- Enabling automatic LLM-directed writes would be a different security design and is intentionally outside this documented setup.

---
*Last updated: 2026-10-06.*
