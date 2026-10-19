> **SUPERSEDED (2026-10-19):** historical deployment README from the pre-bridge read-only + operator-gated-import design. Current design: repo `README.md`, `docs/architecture.md`, `deploy/`. Retained for provenance.

# Omega read-only retrieval experiment

This lane runs MongoDB, Redis, the attention broker, the query engine, and a deliberately narrow HTTP-to-DAS read proxy for an Omega retrieval proof of concept. It does not use the toolbox's host network default and publishes no host ports.

## Safety boundary

- `backend` is an internal network for databases and DAS services.
- `client` is a separate internal network attached only to `query-engine` and `read-proxy`. An Omega client must run as a container explicitly attached to `omega-das-integration-client` and connect to `read-proxy:8080`; it cannot reach MongoDB or Redis through that network.
- The proxy publishes no port. Private Docker-network membership is the accepted trust boundary: there is no application authentication or TLS inside it. Do not attach untrusted containers to `client`.
- The HTTP surface exposes only `POST /v1/query`, which always creates a DAS `PatternMatchingQueryProxy`. Callers cannot select another bus command, set a context, enable count mode, update attention, populate mappings, use the link-template cache, or pass arbitrary DAS parameters. Requests, tokens, answer count, answer fields, and query duration are bounded.
- DAS queries are bidirectional. `read-proxy:42999` is the advertised client identity and per-query gRPC callback listeners use `read-proxy:43000-43031`. The query engine must be able to call the dynamic callback addresses, which is why both services share `client`. The engine listens on all of its private interfaces and consequently advertises dynamic processor peers as `0.0.0.0:42000-42999`; the proxy rewrites only those wildcard callback hosts to the explicit private DNS name `query-engine`, retaining the advertised port. None of these ports is published or reachable from the host.
- All images require `repository@sha256:<digest>` references. Placeholder, absent, malformed, or tag-only values fail preflight/Compose interpolation.
- MongoDB and Redis use explicitly named durable volumes. The normal rollback retains them.
- Redis listens on the private `backend` network with protected mode disabled so its intended non-loopback peer, `query-engine`, can issue commands. Redis has no published host port, is not attached to `client`, and `backend` is internal; network membership is therefore its access boundary. Do not attach untrusted containers to `backend` or publish Redis port 6379. Append-only persistence remains enabled on its durable volume.
- No continuously running loader, mutation agent, host network, privileged mode, Docker socket, or host bind port is included. The proxy runs as UID/GID 65532 with a read-only root filesystem, dropped capabilities, and a small temporary filesystem.
- Two `operator`-profile one-shot services exist for the campaign import procedure below. They are never started by the normal deployment. `campaign-loader` has only the private `backend` network, no published port, a read-only root, and one fixed `db_loader --config=/etc/das/config.json --file=/input/campaign.metta` command. Its generated config and prevalidated input binds are read-only. `campaign-backup` has networking disabled and can only read the MongoDB and Redis volumes while writing their archives. It drops all capabilities except `DAC_OVERRIDE` and `DAC_READ_SEARCH`, which are needed to archive files owned by different database-image UIDs and write the operator-owned bind; the database volume mounts remain read-only. Neither service is an API or available to an LLM through the read proxy.
- The proxy container builds the DAS Python bus client from pinned DAS source commit `e12573cc3a588db699c75b58b1b9e45ebf6d8d4d`. The base Python image is digest-pinned through `PYTHON_IMAGE_DIGEST`; the build requires outbound access to GitHub and Python package indexes.
- The generated configuration is mode `0644` because the `trueagi/das` image runs as `nonroot:nonroot` and Docker bind mounts preserve the host file's numeric ownership and mode. Without host UID mapping, owner/group-only read access cannot reliably grant that container identity access; `0644` is the minimum mode that retains owner-only writes while permitting the image to read the file. On the deployment host, keep `/home/ubuntu` non-traversable by other users (mode `0700`, as provisioned): the parent-directory boundary prevents other host users from reaching a checkout below it, so the file's other-read bit enables the bind-mounted container without broadening host access. Preflight does not alter that boundary.

## Deploy

Copy `.env.example` to `.env`, replace every placeholder with a trusted digest/value, then run:

```sh
./scripts/preflight.sh
./scripts/up.sh
```

The Docker-free regression tests are:

```sh
./tests/test-render-config-permissions.sh
python3 ./tests/test-compose-policy.py
python3 ./tests/test-das-client.py
python3 ./tests/test-read-proxy.py
python3 ./tests/test-campaign-import.py
```

The exact DAS service commands come from `das-cli/src/common/container_manager/agents/attention_broker_container_manager.py` and `das-cli/src/common/bus_node/busnode_command_registry.py`. MongoDB and Redis commands follow their corresponding container managers. The proxy callback behavior and parameter names follow the pinned client's `ServiceBus`, `BaseQueryProxy`, and `PatternMatchingQueryProxy` implementations.

The `trueagi/das` image is distroless and has no `/bin/sh`, and the repository source defines no DAS health RPC or image-provided probe command. Consequently, the deployment does not invent an in-container health check for the attention broker or query engine. MongoDB and Redis remain health-gated, while the query engine uses Compose's strongest source-supported condition for the broker, `service_started`. A successful `up.sh` therefore proves only that Compose started the DAS containers; it does not prove DAS readiness or retrieval correctness.

Before treating the POC as operational, perform all of these post-start checks:

1. Inspect `docker compose --env-file .env -f compose.yaml ps` and `docker compose --env-file .env -f compose.yaml logs attention-broker query-engine`; reject crash loops, exited containers, or startup errors.
2. From an already-approved diagnostic or Omega client container attached to `omega-das-integration-client`, verify that `query-engine:40002` accepts a connection. Because the attention broker is backend-only, verify its `attention-broker:40001` listener from an already-approved container attached to `omega-das-integration-backend`. Do not add host port publications for these checks.
3. Run a representative read-only Omega query through the proxy and confirm the expected result. Listener checks alone are not application-level readiness checks.

These checks are deliberately post-start operator validation: the deployment cannot honestly encode them as container health without a source-supported probe or a trusted external health-monitor component.

Attach an already-created Omega client container without exposing a port:

```sh
docker network connect omega-das-integration-client OMEGA_CONTAINER_NAME
```

Do not attach untrusted containers. Network membership is the access boundary.

From that container, issue a tokenized DAS pattern query:

```sh
curl --fail-with-body \
  --header 'Content-Type: application/json' \
  --data '{"tokens":["LINK_TEMPLATE","Expression","2","NODE","Symbol","Concept","VARIABLE","X"],"max_answers":10}' \
  http://read-proxy:8080/v1/query
```

A successful response has the stable shape:

```json
{"answers":[{"assignments":{"X":"..."},"handles":["..."],"importance":0.0,"strength":1.0}],"count":1,"truncated":false}
```

Invalid input returns HTTP 400, oversized bodies return 413, unknown paths return 404, and a timeout or DAS transport failure returns 502 with a short JSON error. Query execution has a fixed 60-second server-side timeout; callers cannot extend or override it. This allows the query engine's built-in 30-second processing window to finish even though the proxy deadline starts before the client's command-dispatch sleep. The proxy intentionally serializes queries because the pinned client uses process-wide singleton and port-pool state. This is a functional integration lane, not a high-throughput public API.

## Operator-only campaign import

`scripts/campaign_import.py` is the only supported write path in this lane. It is deliberately narrower than `das-cli metta load`: it accepts one local regular file whose basename is exactly `history.metta`, validates the complete source before Docker is touched, and passes a newly generated canonical file—not the source—to the loader. Do not invoke `campaign-loader` directly.

The default strict mode expects UTF-8, newline-terminated input of at most 1 MiB and 2,000 lines, with exactly one assertion per nonblank line. Comments, blank lines, surrounding whitespace, duplicate facts, variables, raw atoms, untyped values, unknown relations, excess nesting, and malformed or oversized values reject the whole batch. The exact accepted schema is:

```text
(Inheritance (Concept "value") (Concept "value"))
(Similarity (Concept "value") (Concept "value"))
(Member (Concept "value") (Concept "value"))
(Evaluation (Predicate "value") (Concept "value"))
(Implication (Predicate "value") (Predicate "value"))
(TemporalPrecedence (Event "value") (Event "value"))
(CausalImplication (Event "value") (Event "value"))
```

This is an assertion importer, not a MeTTa evaluator. Raw wrappers and operators and effectful terms including `shell`, `remember`, `pin`, `websearch`, `query`, `metta`, imports, loads, evaluation, execution, mutation, matching, random operations, and variables are rejected even inside values. The generated file contains only the schema above, fixed type declarations, and `CampaignImport`, `CampaignSource`, `CampaignFact`, `CampaignLine`, and `CampaignProvenance` constructs. Its manifest records the source SHA-256, byte and assertion counts, every source line number and line hash, every normalized assertion and hash, the generated-file hash, relation counts, limits, backup hashes, status, and the required read-only verification plan. It does not preserve raw source text.

### Omega campaign-history extraction

The explicit `--extract-omega-history` mode handles the timestamp-wrapped Omega Curiosity history format without weakening the default strict importer. It is a bounded lexical parser, not a MeTTa runtime: it never invokes, evaluates, expands, interpolates, imports, or resolves any source term. It recognizes only a well-formed `("YYYY-MM-DD HH:MM:SS" ((command ...) ...))` record and only inspects an exact, case-sensitive `(metta "payload")` command. Arguments of `shell`, `websearch`, `send`, `remember`, `pin`, `query`, and every other command are ignored and are not retained. A timestamp-looking form inside a quoted tool argument remains string data and cannot become a record.

Each quoted `metta` payload is parsed again as inert S-expression text. An already canonical typed assertion must pass the same validator used by strict mode. In addition, the extractor accepts only a ground three-item PLN `(Inheritance LEFT RIGHT)` candidate where each operand is either one non-variable symbol, an exact `(Concept SYMBOL)` term, or an exact one-symbol `(IntSet SYMBOL)` / `(ExtSet SYMBOL)` term. These become canonical quoted `Concept` values; set terms are represented losslessly as `IntSet:SYMBOL` or `ExtSet:SYMBOL`.

Candidate assertions are accepted from only three closed, payload-root productions: a supported assertion itself; an exact `(|~ (ASSERTION (stv STRENGTH CONFIDENCE)) ...)` evidence form; or an exact `(add-atom &persistent ASSERTION)` / `(add-atom &persistent ASSERTION (stv STRENGTH CONFIDENCE))` form. Truth-value numbers must be ordinary decimal values from zero through one. The `add-atom` wrapper and optional truth value are treated only as inert evidence of explicit persistence intent: neither is emitted, executed, or retained as a semantic assertion, and only `ASSERTION` is passed through the canonical validator. Other spaces, capitalization variants, malformed or additional arguments, nested wrappers, malformed truth values, and assertions under `quote`, `match`, `progn`, `Implication`, or another operator cannot create facts. The extractor does not import wrappers, truth values, implications over propositions, queries, variables, derived output, error feedback, free-form findings, or prose, and does not infer a semantic relation from natural language. Duplicate canonical facts are skipped after the first provenance-bearing occurrence.

History mode remains capped at 1 MiB, 10,000 physical lines, 5,000 entries, 128 KiB per entry, 4,096 tokens and nesting depth 32 per parsed expression, 65,536 characters per history string, and 2,000 emitted facts. Timestamps are validated as real calendar dates and times, not only by shape. An unterminated record is skipped; recovery occurs only at a new timestamp record boundary encountered outside a quoted string. The run fails before Docker if decoding, global bounds, or source invariants fail, or if no safe facts are found.

The history manifest records the full source SHA-256, accepted fact count, entry/record/command counts, parsed and skipped payload counts, accepted and skipped candidate counts grouped by stable reason, relation counts, and an explicit `parse_incompleteness` total and reason breakdown for malformed, oversized, or unparseable records/payloads. Every accepted fact includes hashes of its full source entry, quoted payload, candidate expression, and canonical assertion plus its source line range. Raw tool arguments and raw source text are not copied into the manifest.

Run a Docker-free dry run first. It writes no import state and contacts no backend:

```sh
python3 ./scripts/campaign_import.py --dry-run campaign-2026-001 /absolute/path/to/history.metta
```

For an Omega Curiosity history, opt in explicitly and inspect all extraction counts and reasons:

```sh
python3 ./scripts/campaign_import.py \
  --dry-run \
  --extract-omega-history \
  omega-curiosity-2026 \
  /absolute/path/to/history.metta
```

Review the normalized preview, source hash, fact mapping, and counts. Then schedule a maintenance window and apply using a new lowercase import ID:

```sh
python3 ./scripts/campaign_import.py \
  --apply \
  --extract-omega-history \
  --env-file /absolute/path/to/deploy/omega-das-integration/.env \
  omega-curiosity-2026 \
  /absolute/path/to/history.metta
```

Apply refuses a history whose `parse_incompleteness.count` is nonzero. If inspection confirms that knowingly importing only the safely parsed subset is acceptable, acknowledge that explicitly by adding `--allow-partial-history` to the apply command. The flag is valid only with `--apply --extract-omega-history`; dry-run remains available without it and should be used to review the exact skipped counts first.

Apply requires the normal five services to be running. It runs preflight, stops `read-proxy` and `query-engine` before stopping or backing up either datastore, makes offline archives of both named volumes whether they are empty or populated, restarts only the datastores, and executes the fixed one-shot loader while both query services remain unavailable. On either success or failure it restores MongoDB, Redis, the attention broker, query engine, and read proxy before returning. Thus partially imported state is not queryable during the maintenance window. A nonzero loader exit, timeout, or an observable terminal marker at the start of a loader output line fails the import. The resulting status is `loaded-unverified`, never `verified`: the operator must complete the manifest's checks from an already-approved container on `omega-das-integration-client` and retain the evidence separately.

State is stored under ignored `state/campaign-imports/IMPORT_ID/`. Any existing directory reserves the ID permanently, including a failed or possibly partially applied run; never delete it merely to retry. Choose a new ID after diagnosing a failure. Each state directory contains the canonical loader input and `manifest.json`; after their respective stages succeed it also contains `backup/mongodb.tar.gz`, `backup/redis.tar.gz`, and mode-`0600` `loader-output.log`. Move copies to access-controlled durable storage before claiming the import is recoverable. Archives and loader output may contain sensitive deployment data and must be treated accordingly.

There is intentionally no automated restore: restoration destroys current state and must be a separately reviewed operator action. To plan one, stop the query engine and datastores, verify both archive hashes against the manifest, inspect archive paths for traversal before extraction, preserve another snapshot of the current volumes, restore both matching archives as one set, restart the normal services, and rerun the read-only verification plan. Do not use global prune, add a host port, attach the loader to `client`, expose this procedure as an HTTP endpoint, or write directly to the AtomDB bus.

## Rollback

```sh
./scripts/rollback.sh
```

Rollback selects only resources bearing `io.ktfh-claw.task=omega-das-integration`. It removes task containers and task networks while retaining MongoDB and Redis volumes. After separately backing up or confirming the data is disposable, erase only the task-labeled volumes with:

```sh
./scripts/rollback.sh --purge-data
```

The scripts never use global prune operations.
