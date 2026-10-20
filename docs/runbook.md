# From-scratch deployment runbook — omega-das-bridge

Target: an operator with a fresh Linux host can reproduce the entire lane
(DAS stack → atomdb-broker → read proxy → write bridge → bulk/history load →
Omega plugin attachment → verification) from this repo alone. Every command
below is the live-verified form used on the OVH host
(`ubuntu@100.84.81.96:22→9022`, Tailscale `100.84.81.96`); deviations
discovered live are called out inline. The consolidated acceptance evidence
for each step is in [`docs/acceptance.md`](acceptance.md).

**OVH layout note (2026-10-20):** the deployment tree is the repo checkout at
`~/low-cost-omega-setup/` (deployed services carry
`com.docker.compose.project.working_dir` labels pointing into it). The older
flat tree at `~/omega-das-bridge/` is a **stale iterations-≤6 leftover** (pre-
oracle `cleanup.py`, old compose context) — never deploy from it; it is a
cleanup candidate.

## 0. Host prerequisites

- Linux x64, Docker Engine + Compose v2 (`docker compose …`).
- Outbound HTTPS for image pulls + the pinned-client git clone (tests image).
- Firewall: no lane port is published; every service lives on two internal
  docker networks (`omega-das-integration-backend`, `omega-das-integration-
  client`). On the OVH reference host UFW allows SSH (9022) on `tailscale0`
  only; the lane adds no public exposure.
- Clone this repo; all paths below are relative to the repo root.

## 1. DAS datastore + query stack

```bash
cd deploy/das
cp .env.example .env   # then edit; NEVER commit .env (gitignored)
```

`.env` keys (all required; `scripts/preflight.sh` validates format):

| Key | Meaning |
|---|---|
| `MONGODB_IMAGE_DIGEST` | sha256 pin, `mongodb/mongodb-community-server` |
| `REDIS_IMAGE_DIGEST` | sha256 pin, `redis` |
| `DAS_IMAGE_DIGEST` | sha256 pin, `trueagi/das` (QE + attention broker + loader) |
| `PYTHON_IMAGE_DIGEST` | sha256 pin, `python` (proxy/bridge build base, tests image) |
| `MONGODB_USERNAME` / `MONGODB_PASSWORD` | mongo root creds (password ≥ 20 chars) |

Live-verified digests (2026-10-20, OVH):

```
mongodb/mongodb-community-server@sha256:56880b05d07a02ebc8fab9e72ee0de1f0ee45f1631b0a238042732fe1d41ccc9
redis@sha256:62c97f250e61ea79bb3f8bf9a3e40b7b2144f8d8f5d7bd19547923055914aa79
trueagi/das@sha256:1fec9fc8754ab562edaa52e61e1e5f145d91abce32a56d2be64696bdb335a51d
python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
```

Start (preflight renders `generated/config.json` — mongo creds into the DAS
config template, chmod 644 so the container UID can read it — then validates
digest formats and does a `compose config` dry check):

```bash
./scripts/up.sh          # = preflight.sh + docker compose up -d --wait
docker compose -f compose.yaml ps   # mongodb+redis healthy, QE/attention-broker/read-proxy Up
```

Services: `mongodb`, `redis` (backend net), `attention-broker`, `query-engine`
(backend+client), `read-proxy` (client net, bounded facade). Operator-only
one-shots `campaign-loader` + `campaign-backup` run under `--profile operator`.
Rollback: `scripts/rollback.sh`; pre-pull sanity: `scripts/preflight.sh`.

## 2. atomdb-broker (deployed OUT of compose)

The broker is a single `docker run` (inlined in
`deploy/das/write-bridge/compose.write-bridge.yaml` as a header comment —
keep the two copies in sync):

```bash
docker run -d --name omega-das-integration-atomdb-broker \
  --network omega-das-integration-backend --network omega-das-integration-client \
  --restart unless-stopped \
  -v $PWD/../generated/config.json:/etc/das/config.json:ro \
  trueagi/das@sha256:<DAS_IMAGE_DIGEST> \
  busnode --service=atomdb-broker --endpoint=0.0.0.0:40007 \
    --ports-range=47000:47999 --atomdb-type=redismongodb \
    --config=/etc/das/config.json

# THEN attach the client-network alias (a docker run with two --network
# flags keeps only the LAST network's DNS records; live-discovered iter 2):
docker network connect --alias atomdb-broker \
  omega-das-integration-client omega-das-integration-atomdb-broker
```

**Broker invariants (violating any breaks the lane — live-discovered):**

1. Bind `0.0.0.0` (never a hostname) — multi-network docker peers on other
   networks get connection-refused otherwise.
2. Write clients join the broker **directly** (`known_peer` = broker DNS
   name). A mis-routed `atomdb` command **crashes the query engine**
   (uncaught `std::runtime_error`, upstream defect — see
   `docs/contributions/issue-1-qe-crash.md`).
3. The callback-peer rewrite host for `atomdb` commands is the broker DNS
   name (services announce unroutable `0.0.0.0:<port>` callback peers).
4. The broker must resolve as `atomdb-broker` on the client network
   (second-network `--alias` connect, above).

Sanity: `docker exec <any client-net container> getent hosts atomdb-broker`.

## 3. Read proxy (MeTTa-mode + structural)

Built and started as part of step 1 (`read-proxy` service). It wraps the
pinned python client with the correctly-spelled `use_metta_as_query_tokens`
parameter (upstream python client sends a typo'd key — the proxy sets the
correct one and pops the typo), the nested-handle-vector decoder, and the
`abort()` list-vs-dict workaround. Bounded: 100 answers, 256 tokens, 60 s
query timeout, no published ports.

Verify from any client-net container:

```bash
# structural, variable form (ground forms never complete — keep a variable):
curl -s http://read-proxy:8080/v1/query -H 'Content-Type: application/json' \
  -d '{"metta": "(Inheritance (Concept \"smoke\") $_1)", "max_answers": 10}'
# -> {"mode": "metta", "answers": [...], "count": N, ...}
```

## 4. Bridge write lane (write-bridge service)

```bash
cd deploy/das/write-bridge
# .env with PYTHON_IMAGE_DIGEST (compose auto-loads it) or export it
docker compose -f compose.write-bridge.yaml up -d --build
docker compose -f compose.write-bridge.yaml ps   # Up, 0 restarts
```

The service binds only the internal client network. Canary procedure
(write → verify → cleanup → zero-residue) is documented in
[`write-bridge/README.md`](../das/write-bridge/README.md) §Canary procedure.
**`compose run` rule (live-discovered iter 5):** one-off containers MUST
override the bus node id — `--name <run-name>` plus
`-e DAS_CLIENT_ENDPOINT=<run-name>:43999` — otherwise the container either
joins the broker with the live service's node id (corrupting peer routing)
or fails the callback bind (`getaddrinfo`).

Unit suite (pinned upstream client `e12573cc` compiled into the tests image;
**123 tests**):

```bash
docker build --build-arg PYTHON_IMAGE_DIGEST=sha256:<digest> \
  -t omega-write-bridge-tests tests/
docker run --rm -e PYTHONPATH=/work -v $PWD:/work:ro \
  omega-write-bridge-tests -q -p no:cacheprovider tests/
# -> 123 passed
```

## 5. Bulk/history load lane (thin import wrapper)

Wrapper: `deploy/das/import-wrapper/` (config-only pre-processor for the
stock upstream `syntax_check` + `db_loader`).

```bash
cd deploy/das/import-wrapper
make test                       # unit tests (gate faked, no docker)
# build the upstream das-metta-parser syntax_check binary, then:
python3 import_wrapper.py --input history.metta --out load.metta \
  --report report.json --campaign omega-das-bridge \
  --source history-v1 --epoch epoch-1
# live-validated on the real 26,556-line history: 8,285 entries,
# 99.17% emitted (>= 99% target), no `(:` forms, one CampaignProvenance
# link per entry
```

Load into a **scratch** mongo first (never the live DB — the wrapper was
validated on per-run scratch mongos with per-run creds, `chmod 600` env
files, root-only). Load with the operator-profile loader service:

```bash
cd ../   # deploy/das (compose.yaml)
CAMPAIGN_IMPORT_FILE=/abs/path/load.metta \
docker compose --env-file .env -f compose.yaml --profile operator \
  run --rm campaign-loader    # db_loader --skip-redis path: STEP 1/1 100%
```

Ground-truth the load in scratch mongo: `atom_types = 0` (any `(:`
pollution shows up here), node/link counts, provenance-link count == emitted
entry count. See `docs/acceptance.md` §C for the validated numbers.

## 6. Omega agent attachment (plugin; GATED)

The `das-write` plugin (`deploy/omega/plugins/das-write/` +
`plugins.yaml.overlay`) turns the Omega skill layer's
`(add-atom &persistent <expr>)` into bridge writes with mandatory read-back.
Enablement is the stock config key `dasWriteEnabled` (exact `"1"`) resolved
through Omega's stock config chain (command line > `OMEGA_<KEY>` env >
config.yaml) — the stock image entrypoint scrubs the agent env to an
allowlist, so raw `os.environ` gates do NOT work live.

- Validated in a **one-off test container only** (enabled: BRIDGE-PERSIST-OK
  + oracle cleanup + mongo zero-residue; disabled: zero behavioral change).
- **The live Omega agent stays STOPPED unless Balázs explicitly approves a
  restart.** When approved: container on the client network only (no DB
  creds), plugin + overlay bind-mounted `:ro` over the stock config.

## 7. Verification & acceptance

Full procedure + evidence: [`docs/acceptance.md`](acceptance.md). Minimal
from-scratch acceptance loop (the `iter16_probe.py` shape, runnable from
`deploy/das/write-bridge` against the deployed services):

```bash
docker compose -f compose.write-bridge.yaml run --rm --name <run-name> \
  -e DAS_CLIENT_ENDPOINT=<run-name>:43999 -v $PWD:/probe:ro \
  write-bridge /probe/tests/iter16_probe.py
```

Expected (live 2026-10-20): PHASE1 `verified: true` (~4 s), PHASE2 metta
read (~1.3 s), PHASE3 oracle `absent: true` first pass, PHASE4 unique nodes
deleted, PHASE5 0 answers. Then the mongo ground truth (db `das`): canary
links/nodes 0, shared symbols intact, totals unchanged → zero residue.

Backups: `docker compose --env-file .env -f compose.yaml --profile operator
run --rm campaign-backup` (volume dump to `CAMPAIGN_BACKUP_DIR`).
