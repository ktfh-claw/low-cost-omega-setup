# Operator DAS import runbook

**Purpose:** the only supported procedure for persisting Omega campaign knowledge into the Distributed AtomSpace (DAS) in this setup.
**Tool:** `deploy/omega-das-integration/scripts/campaign_import.py` in [`ktfh-claw/das-toolbox`](https://github.com/ktfh-claw/das-toolbox), branch `omega-das-write-integration`, reviewed at commit `dfccfae75b149f11733b158dee342c00530c4627`.
**Audience:** the human operator. The autonomous Omega agent has no part in this workflow and must never receive a DAS write capability.

This runbook reflects the procedure validated end-to-end in the documented production imports. Immediately before the v0.1.20 uplift, the latest run extracted 336 unique facts (316 old, 20 new, 0 dropped), processed 3,232 atoms, and independently verified all 20 new facts plus provenance through both the datastore and deployed read proxy.

---

## Security model — read before running anything

- The write path is **operator-only by design**. The Omega container holds no database credential and no datastore route; the deployed DAS stack exposes only a bounded read proxy on an internal network, and the import profile is not started by normal `docker compose up`.
- Run an import only on an explicit operator request, and treat every phase below as part of one authorized operation.
- Never widen the capability while running it: do not publish DAS ports to the host, do not add write endpoints to the read proxy, do not attach the Omega container to the DAS backend network, and do not leave operator loader/backup containers running.
- A DAS write claim is only credible with import/loader evidence **plus** the independent verification in Phase 5. Until then the manifest intentionally reads `loaded-unverified`.

## Prerequisites

- DAS stack running and healthy, internal-only (`backend` and `client` networks, no published ports).
- Operator access to the deployment host, including:
  - the Docker volume that holds the live Omega corpus `history.metta` (the campaign memory directory);
  - the live DAS deployment directory containing the operator `.env` file (referenced below as `$DEPLOY_DIR`);
  - a `das-toolbox` checkout providing `campaign_import.py` (referenced below as `$TOOLBOX`).
- The previous import's dry-run manifest, if this is an incremental import (Phase 3).
- Sufficient disk space for the offline MongoDB/Redis backups taken during apply.

Verify the importer you are about to run matches the reviewed code (no local edits):

```bash
sha256sum "$TOOLBOX/deploy/omega-das-integration/scripts/campaign_import.py"
# must equal the SHA recorded for reviewed commit dfccfae; the copy deployed and
# used for both validated runs was 98bfcdb88615f9e02ca63e40dc8b098e1499a90e09c677ca447b327e0443ce59
```

## Phase 1 — Freeze the corpus

The importer requires a quiescent corpus; concurrent agent writes during extraction would make the snapshot inconsistent.

1. Stop the campaign service and confirm the container exited:

   ```bash
   sudo systemctl stop omega-curiosity.service
   docker ps --filter name=omega-curiosity   # expect: no running container
   ```

2. Copy the corpus out of the volume **read-only**, leaving the original untouched:

   ```bash
   mkdir -p "$IMPORT_SRC"
   # The volume root is the Omega memory directory in the container, so the
   # live file /PeTTa/repos/Omega/memory/history.metta appears as /src/history.metta.
   docker run --rm -v <campaign-memory-volume>:/src:ro -v "$IMPORT_SRC":/dst \
     alpine sh -c 'cp /src/history.metta \
       /dst/history-$(date -u +%Y%m%dT%H%M%SZ).metta'
   ```

3. Record the snapshot fingerprint (bytes, lines, SHA-256):

   ```bash
   wc -c -l "$IMPORT_SRC"/history-*.metta
   sha256sum  "$IMPORT_SRC"/history-*.metta
   ```

4. The importer rejects any source whose basename is not exactly `history.metta` (fail-fast, before any mutation). Create a working copy with the required name:

   ```bash
   mkdir -p "$IMPORT_SRC/current-<timestamp>"
   cp "$IMPORT_SRC/history-<timestamp>.metta" \
      "$IMPORT_SRC/current-<timestamp>/history.metta"
   ```

## Phase 2 — Dry run (no side effects)

Dry-run mode touches neither Docker nor persistent files; `--env-file` is rejected in this mode.

```bash
python3 "$TOOLBOX/deploy/omega-das-integration/scripts/campaign_import.py" \
  "<import-id>" "$IMPORT_SRC/current-<timestamp>/history.metta" \
  --dry-run --extract-omega-history
```

- `--extract-omega-history` lexically extracts candidate facts from the timestamped campaign history. Nothing from the corpus is executed.
- Review the printed manifest: commands/entries parsed, malformed counts, accepted unique canonical assertions, skipped categories, and the canonical-output SHA-256.
- `<import-id>` must match `[a-z0-9][a-z0-9-]{2,63}`; it is used later for provenance queries. Use a stable scheme such as `<source>-<date>`.
- Keep the dry-run output as evidence.

Importer input limits (enforced, fail-closed): source ≤ 1 MiB, ≤ 2,000 assertions, plus per-line/entry/token/depth caps. A corpus beyond these limits is refused, not truncated.

## Phase 3 — Delta analysis (incremental imports)

Duplicate facts are safe — the loader's merger upserts them — but an import with no new facts is churn. Before applying, diff this run's extracted facts against the previous import's dry-run manifest:

- `old_unique` — facts already covered by the previous import;
- `new_unique` — facts not previously imported (the actual delta);
- `dropped_from_old` — previously imported facts absent from the current extraction.

Decision rule: delta of 0 → stop, no import needed. `dropped_from_old > 0` → investigate why previously imported facts disappeared before applying. Record all counts as evidence.

Validated example (2026-10-06 run): 316 extracted facts → 311 old, 5 new, 0 dropped.

## Phase 4 — Apply (the only mutating step)

Run from the live deployment directory that holds the operator `.env` (the tool defaults to `./.env`; a checkout without that file fails fast before mutation):

```bash
cd "$DEPLOY_DIR"
python3 "$TOOLBOX/deploy/omega-das-integration/scripts/campaign_import.py" \
  "<import-id>" "$IMPORT_SRC/current-<timestamp>/history.metta" \
  --apply --extract-omega-history --allow-partial-history \
  --env-file "$DEPLOY_DIR/.env"
```

- `--allow-partial-history` explicitly acknowledges malformed history entries; it is only valid together with `--apply --extract-omega-history`. Omit it to fail closed on any malformed entry.
- The importer then, in order: runs preflight; takes **offline MongoDB and Redis volume backups** (tarballs + SHA-256 hashes); writes an auditable manifest; restarts the DAS compose stack; runs the one-shot loader against the canonical file; and reports `load completed but requires read-only verification`.
- Expect loader exit `0` and an atoms-processed count equal to upserted duplicates + new facts + provenance links (e.g. 3,040 for 311 upserts + 5 new + provenance in the 2026-10-06 run).
- The manifest is deliberately left in `loaded-unverified` status. Do not edit it; Phase 5 is what upgrades confidence.

If anything fails here: the tool is fail-fast, and both observed failure modes (wrong source basename; missing `.env`) exit before any mutation. The pre-load backups are the rollback artifact for anything past that point.

## Phase 5 — Independent verification (mandatory)

Two independent checks, both from one-shot containers; keep them off any network the agent uses.

### a) Direct datastore check

One-shot `mongosh` on the backend network only, with a pinned image digest and a mounted script that contains no secrets:

- every new fact must be present in `das.links`;
- provenance links referencing the new source snapshot SHA-256 must exist (e.g. 317 links in the 2026-10-06 run).

### b) Deployed read path check

The same bounded route the Omega adapter uses; one-shot client container on the DAS client network:

```text
POST http://read-proxy:8080/v1/query
{ "tokens": [ ... ], "max_answers": N }
```

- The body may contain only `tokens` and an optional `max_answers`; `max_answers` is capped by the proxy (`PROXY_MAX_ANSWERS`, default 100).
- Use the **nested** token shape. Concepts are stored as `(Concept "...")` expressions; a flat `NODE Symbol "<value>"` child returns 0 answers. A fact query shape that matches:

  ```text
  LINK_TEMPLATE Expression 3
    NODE Symbol Inheritance
    LINK_TEMPLATE Expression 2
      NODE Symbol Concept
      NODE Symbol "<value>"
    VARIABLE B
  ```

- Send only grammatically valid patterns: a malformed token list can leave the single-worker proxy waiting until it times out (historically 502 after 60 s).
- Verify:
  1. each new fact returns exactly 1 answer, and returned handles match the datastore `_id`s from check (a);
  2. the provenance marker `campaign-import:<import-id>` is queryable (bounded answer set);
  3. an old-fact canary from a previous import still resolves to its original handle (data continuity).

## Phase 6 — Resume and posture checks

1. Restart the campaign service and confirm it is healthy:

   ```bash
   sudo systemctl start omega-curiosity.service
   systemctl status omega-curiosity.service   # active, restart counter sane
   ```

2. Confirm the isolation posture is unchanged:
   - campaign container attached only to the default bridge + the DAS client network;
   - DAS `client` and `backend` networks still internal-only, no published data-plane ports;
   - the Omega container still cannot resolve `mongodb` or `redis`;
   - no operator loader/backup containers remain.
3. Retain as evidence: snapshot fingerprint, dry-run manifest, delta analysis, import manifest + loader log, backup hashes, verification outputs, and restart timestamps.

## Run history

| Import | Date (UTC) | Facts loaded | Atoms processed | Note |
|---|---|---:|---:|---|
| `omega-curiosity-20261005-final` | 2026-10-05 | 311 (initial) | 2,981 | Initial campaign import |
| `omega-curiosity-20261006` | 2026-10-06 | 5 (delta) | 3,040 | Earlier 2026-10-06 delta run; superseded by the pre-uplift corpus import evidence |

The subsequent pre-uplift import on 2026-10-06 covered 336 unique facts (316 old and 20 new), processed 3,232 atoms, and had 0 dropped facts. Its exact host-side manifests and verification outputs are retained with the deployment evidence; this public runbook does not assign an import identifier that is absent from the recorded summary.

---
*Last updated: 2026-10-06.*
