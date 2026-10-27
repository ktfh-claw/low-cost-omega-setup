# das-write bridge v1 (Phase 1: service + client skeleton)

Narrow, security-bounded Python service + client that writes MeTTa facts to
the live DAS atomdb-broker and verifies them by structural read-back. This
is the Phase-1 "das-write skill v1 skeleton" of the omega-das-bridge
campaign: **config-only** — it uses the pinned upstream python client
(singnet/das `e12573cc`, `3rd_party_slots/python_client`) as a library; no
upstream sources are forked or modified.

## What it is

```
POST /v1/write {"metta": "(Inheritance (Concept \"x402\") (Concept \"payment-protocol\"))", "verify": true}
    -> 200 {"handles": ["..."], "verified": true, "missing": [], "top_handle": "<fact top-link handle>"}
```

### Provenance ledger (v4, 2026-10-27)

Provenance is **metadata-only and transparent to the agent**: source content
is never archived; the facade keeps a git **ledger** of
`(ref, sha256)` pairs, and the fact's TOP link carries the provenance as
`custom_attributes` (there is NO companion atom). Two endpoints:

- **`POST /v1/source {"ref", "sha256"}`** — append one entry to
  `SOURCE-LEDGER.json` in the git repo at `WRITE_PROVENANCE_REPO` and
  return `{"commit", "deduped", "entry_date"}`. The ref is an http(s) URL
  or an absolute path (≤480 chars, no whitespace); the sha256 is 64
  lowercase hex (of the source content, computed by the agent-side plugin
  — content never crosses to the facade). **Dedup:** recording a
  `(ref, sha256)` pair already present returns the ORIGINAL entry's commit
  (`deduped: true`, no new commit); the entry identity is `(ref, sha256)`,
  never a line number. Same ref + different content = a new entry.
- **`POST /v1/write {"metta", "verify", "provenance", "tv"}`** — the
  optional `provenance` object carries exactly
  `{"ref", "git_commit", "blob_sha256"}` (the `git_commit` is the ledger
  commit returned by `/v1/source`, cited as `"git:<40hex>"`). A
  **citation gate** runs BEFORE anything reaches DAS: the cited commit
  must exist in the ledger repo, touch only `SOURCE-LEDGER.json`, add
  exactly one entry-shaped line, and that entry's `(ref, sha256)` must
  equal the payload's. Failures return `400` with an actionable,
  retryable message (`not found in the ledger — write the source first
  via the skill, then retry`, `is not a ledger commit (touching only
  SOURCE-LEDGER.json)`, `does not add the cited source entry — re-run the
  skill write, then retry`); a legacy `{url, git_commit}` payload is
  rejected with `provenance must contain ref, git_commit and
  blob_sha256`. Provenance without a configured ledger is `503`. The 200
  response carries `top_handle` (the fact's top-link handle) alongside
  `handles`/`verified`/`missing` — the plugin's write receipt quotes it.

**`SOURCE-LEDGER.json` format** — a single JSON array file, one element
per line, leading-comma pinned form (each append is a pure +1-line diff
and the file stays valid JSON); each element has exactly three fields:

```json
[
{"ref": "https://example.com/source.md", "sha256": "9f2c1d0a…64hex", "entry_date": "2026-10-28T09:00:00Z"}
,{"ref": "/var/lib/sources/other.md", "sha256": "1ab3e57f…64hex", "entry_date": "2026-10-28T09:00:01Z"}
]
```

One commit per new entry; the commit subject (`ledger: <sha12> <ref[:96]>`)
is informational only and never parsed by verification. A fresh repo
starts as `[\n]` with a single `ledger: init` commit (citing it correctly
fails the gate — it adds no entry line).

**Top-link custom_attributes** (best-effort persistence, live-verified
Phase 0): `metta_expression` always; with provenance `provenance_ref`,
`provenance_git_commit`, `provenance_blob_sha256`; with `tv` `stv_strength`,
`stv_confidence`. A dropped attribute surfaces at reconstruction (case
FAIL), not as a write failure. Attributes ride the mongo link document and
are invisible to pattern-engine answers — mongo is THE provenance channel.

- `metta_to_atoms.py` — client-side parse of ONE small parenthesized MeTTa
  fact into the pinned client's `Node`/`Link` atoms (data only, no
  operators/eval). Storage conventions match the live-verified deployment:
  quoted literals keep their quotes as Symbol node names, bare symbols don't;
  every (sub-)expression is a generic `Expression` link; atoms are emitted
  bottom-up, de-duplicated, deterministically. Handles are computed by the
  pinned client's hashing, so client-computed handles == server-stored
  handles (live-verified 2026-10-18).
- `write_client.py` — `DasWriteRunner`: joins the service bus with
  `known_peer = <broker endpoint>`, sends `AtomDBProxy.add_atoms(atoms,
  use_streaming=False)` (the proxy's built-in `COMMAND_SIZE_LIMIT` chunking
  applies), then verifies by ground structural `LINK_TEMPLATE` queries
  through `PatternMatchingQueryProxy` against the query engine. Returns
  `{"written": [handles], "verified": bool|null, "missing": [handles],
  "top_handle": str}`.
- `provenance_store.py` — `LedgerStore`: the git ledger
  (`ensure_repo`/`record`/`verify_commit`), flock-serialized on
  `.ledger.lock`.
- `app.py` — bounded HTTP facade (mirrors `deploy/das/proxy/app.py`): body
  cap 16 KiB on both `/v1/write` and `/v1/source`, metta cap 2048 chars,
  single-expression rule, same hardening.
- `cleanup.py` — canary cleanup: deletes a fact's atoms by handle and
  verifies the deletion by read-back returning no answers.
- `compose.write-bridge.yaml` — one `write-bridge` service on the existing
  `omega-das-integration-client` network (see below for the broker).

## Environment variables

| Variable | Meaning | Example |
|---|---|---|
| `DAS_BROKER_ENDPOINT` | broker endpoint; the atomdb bus joins it **directly** | `atomdb-broker:40007` |
| `DAS_BROKER_PEER_HOST` | broker DNS name used for the atomdb callback-peer rewrite | `atomdb-broker` |
| `DAS_QUERY_ENGINE` | query-engine endpoint (read-back verification bus) | `query-engine:40002` |
| `DAS_CALLBACK_PORT_LOWER/UPPER` | client callback port range | `43300`/`43331` |
| `DAS_CLIENT_ENDPOINT` | this client's bus node id | `write-bridge:43999` |
| `DAS_VERIFY_TIMEOUT_SECONDS` | per-query read-back timeout (default 30) | `30` |
| `DAS_PEER_JOIN_TIMEOUT_SECONDS` | wait for the broker callback peer (default 10) | `10` |
| `WRITE_HTTP_HOST/PORT` | facade bind (default `0.0.0.0:8080`) | `0.0.0.0`/`8080` |
| `WRITE_MAX_METTA_CHARS` | metta size cap (default 2048) | `2048` |
| `WRITE_PROVENANCE_REPO` | host path of the git source ledger repo (unset = provenance endpoints return 503) | `/var/lib/omega-provenance` |

## The three deployment invariants (live-discovered; violating any breaks the lane)

1. **The broker binds `0.0.0.0`** (not a hostname) in multi-network docker —
   hostname binding attaches to one interface and peers on other networks
   get connection refused.
2. **Write clients join the broker DIRECTLY** (`known_peer` = broker DNS
   name), never via the query engine: a mis-routed `atomdb` command crashes
   the query engine (uncaught "Processor is not registered to process
   command: atomdb", upstream defect). This runner enforces the invariant
   structurally: it owns two separate service buses whose routable command
   sets are disjoint singletons — the atom bus can only route `atomdb` to
   the broker, the query bus can only route `pattern_matching_query` to the
   query engine.
3. **The callback-peer rewrite host for atomdb commands is the broker name.**
   The pinned services announce `0.0.0.0:<port>` callback peers, which are
   not routable; the rewrite substitutes the explicit DNS name per command
   (broker for `atomdb`, query-engine for `pattern_matching_query`).

## Fire-and-forget semantics — read-back is mandatory

`AtomDBProxy.add_atoms` returns **locally-computed handles; there is no
server acknowledgement**. The write bridge therefore verifies every write:
each written `Expression` link is queried with a fully ground
`LINK_TEMPLATE` and the answer handles must contain the expected
(deterministic) handle. Notes:

- `verified` is `null` (JSON) when `"verify": false` was requested;
  `verified: false` always means "checked and at least one link is missing".
- `missing` only ever contains **link** handles: nodes are verified
  transitively (every node in a parsed fact is a target of at least one
  written link, and a link template only matches when its target handles
  match).
- The TOP link's `custom_attributes` (`metta_expression`,
  `provenance_*`, `stv_*`) ride the mongo link document (live-verified
  Phase 0) and are invisible to pattern-engine answers; verification uses
  handles/targets only and never reads attributes back.
- Verification uses the structural token form. Variable-bearing MeTTa-form
  queries work through the query engine with
  `use_metta_as_query_tokens=true`, but ground (variable-free) MeTTa
  patterns return 0 answers in this build — ground checks stay structural.
- Read-back costs one bus round-trip per written link (~1.6 s live);
  keep facts small.

## Upstream bug notes (all live-verified 2026-10-18, re-eval campaign)

- **QE crash on mis-routed atomdb commands** — sending an `atomdb` bus
  command to the query engine raises an uncaught `std::runtime_error` and
  restarts the QE container (also: mesh command-ownership discovery does
  not propagate to late joiners, so clients must join each service
  directly). Worked around by invariant 2.
- **python client parameter typo** — the pinned client sends
  `"user_metta_as_query_tokens"` (base.py `USE_METTA_AS_QUERY_TOKENS`)
  while the C++ server reads `"use_metta_as_query_tokens"`
  (BaseQueryProxy.cc). This bridge sets the correctly spelled key directly
  (and pops the typo'd one), like the read proxy's fix.
- **Answer wire format** — the C++ engine emits nested handle vectors which
  the pinned python client mis-decodes (handle-vector count read as flat
  handle count); this bridge installs the same nested-handle decoder as the
  live-verified read proxy.
- **abort() type bug** — the pinned client's `abort()` passes a dict to an
  API that appends to a list; the bridge issues `to_remote_peer("abort",
  [])` instead (same workaround as the read proxy).

## Canary procedure (write -> verify -> cleanup)

Use fresh, uniquely named content — `add_atoms` upserts. Cleanup defaults
to deleting ONLY the fact's Expression links: Symbol nodes are shared across
facts on a live DB (live-measured 2026-10-20: `Symbol "Inheritance"` is the
target of 421 other links, `Symbol "Concept"` of 791) and deleting them
would orphan every fact reusing the same symbols. For zero residue on a
shared DB, delete the canary's unique nodes afterwards via explicit
`--handle` flags; `--delete-nodes` (all fact handles, nodes included) is for
scratch databases only.

```bash
# 0) the DAS stack + broker must be up (broker deployed out of compose, see
#    compose.write-bridge.yaml header for the live-verified docker run +
#    client-network alias connect)

# 1) write + verify (read-back is on by default)
curl -s http://write-bridge:8080/v1/write -H 'Content-Type: application/json' \
  -d '{"metta": "(Inheritance (Concept \"canary-20261019\") (Concept \"write-bridge-test\"))"}'
# -> {"handles": [...], "verified": true, "missing": []}

# 2) cleanup: delete the fact's LINKS and verify they are gone
docker compose -f compose.write-bridge.yaml run --rm write-bridge \
  /app/cleanup.py --metta '(Inheritance (Concept "canary-20261019") (Concept "write-bridge-test"))'
# -> {"deleted": [...], "absent": true, "still_present": []}

# 3) optional zero-residue: delete the canary's unique NODES explicitly
#    (bare nodes are not covered by the link-walk verification, so the
#    result reports absent: null)
docker compose -f compose.write-bridge.yaml run --rm write-bridge \
  /app/cleanup.py --metta '(...)' \
  --handle <canary-node-handle> --handle <canary-concept-node-handle>
```

`cleanup.py` re-derives the deterministic handles from the metta expression;
an explicit `--handle` list (repeatable) must belong to the fact. The
broker-side deletion follows the C++ client's wire format (chunked handle
lists with a trailing `delete_link_targets` flag; `--delete-link-targets`
opts into recursive target deletion). Deletion is fire-and-forget too — the
read-back absence check is what makes the result credible.

Deletion is also **eventual and loop-coupled** (live-measured iterations
3-7): the server-side apply is starved by sustained verification traffic —
every polling grace window ever shipped (30/90/90-s-poll-5 s/300-s-poll-5 s;
6/16/10/32 attempts) false-alarmed `absent: false` while mongo confirmed
complete deletions seconds after the loop stopped querying; a light-traffic
run saw absence at T+7.8 s. `cleanup.py` therefore does NOT poll: it
verifies absence through the **alternate-pattern oracle** (iteration 7) —
each link admitting a tight alternate form (arity >= 3: leading symbol
ground, variable in the first non-leading position, expected assignment
pinned; live-validated 6b) is checked through that second, differently-
shaped pattern, which the verification traffic has not kept warm; 2-arity
links (no tight alternate — the loose form is schema-ambiguous on a shared
DB) keep the primary variable-form verdict. If a check still matches, the
loop waits **query-free** (the apply needs the query path to idle) and
re-checks, bounded by `--recheck-limit` (default 3) and
`--recheck-wait-seconds` (default 10; total standby capped at 120 s);
bus failures fail fast. The result reports `checks` and `standby_seconds`.
Live-validated iteration 7: the oracle returned `absent: true` on the
FIRST pass (5.3 s, zero standby) where every polled window had
false-alarmed. A persistent `absent: false` after the bounded re-checks
means the delete genuinely did not land — re-run or investigate, do not
ignore.

## Deployment

- Resolve the builder digest first (the same pinned python image the tests
  use), then build + start the service from `deploy/das/`:

```bash
export PYTHON_IMAGE_DIGEST=sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
docker compose -f write-bridge/compose.write-bridge.yaml up -d --build
```

Every compose invocation interpolates `PYTHON_IMAGE_DIGEST` (up/ps/run
alike); either keep it exported or put it in `write-bridge/.env` (compose
auto-loads it from the project directory; see `.env.example`).

- Image: `Dockerfile` reuses the read-proxy's pinned-digest builder pattern
  (python@sha256 digest, grpc codegen from the pinned das proto submodule,
  non-root user 65532). The container is read-only, drops all capabilities,
  sets no-new-privileges and a tmpfs /tmp (compose).
- `compose.write-bridge.yaml` attaches to the external
  `omega-das-integration-client` network of the existing deployment
  (`deploy/das/compose.yaml`). The atomdb-broker itself is deployed out of
  compose (`docker run`, command inlined in the compose header) — starting
  a second broker from compose would clash with the live one.
- No ports are published; the facade is reachable only on the internal
  client network.

### `compose run` one-off containers MUST override the bus node id

`DAS_CLIENT_ENDPOINT` is the service-bus node id, and its host part is what
the ServiceBus BINDS its callback ports on. A `docker compose run` cleanup
container inherits the service's value (`write-bridge:43999`) and would join
the broker with the SAME node id as the live service — corrupting the
broker's peer routing. And an arbitrary unresolvable name fails the callback
bind outright (live-discovered iteration 5: `getaddrinfo` failure). Always
name the one-off container (`--name`) and use that same name as the node-id
host — docker DNS resolves container names on user-defined networks:

```bash
docker compose -f write-bridge/compose.write-bridge.yaml run --rm --name wb-cleanup \
    -e DAS_CLIENT_ENDPOINT=wb-cleanup:43999 write-bridge \
    /app/cleanup.py --metta '(Inheritance (Concept "canary-20261019") (Concept "write-bridge-test"))'
```

## Tests

Unit tests with the upstream client **stubbed** (no network, no docker):
`python -m pytest tests/` from this directory (needs only pytest). The
stubbed atoms mirror the pinned hashing formulas; expected handles/wire
tokens embedded in the tests were computed with the real pinned client.

## Phase-1 acceptance record (signed off 2026-10-20 02:41 UTC)

Phase 1 of the omega-das-bridge campaign (bridge core, config-only, live on
OVH) is complete. Acceptance evidence, all live on the deployed services:

- **Read proxy** — MeTTa-mode (`use_metta_as_query_tokens` config wrapper,
  no source fork) + structural queries, ground and variable forms,
  live-verified iterations 2–8 through `omega-das-integration-read-proxy-1`.
- **Write lane** — `POST /v1/write` with **mandatory read-back verification**
  (variable-form template oracle; deterministic handles) on the deployed
  compose service `omega-das-write-bridge-write-bridge-1` (iterations 5–8):
  `verified: true` on every canary, 4.1–5.0 s end-to-end.
- **Cleanup** — links-only default (shared-DB safety), explicit unique-node
  zero-residue step, and the **absence oracle** (iteration 7): per-link
  alternate-pattern verification + bounded query-free standby re-checks.
  Live matrix: every polled grace window (30/90/300 s) false-alarmed while
  deletions always landed (loop-coupled apply starvation, iters 3–6); the
  oracle returned `absent: true` on the **first pass** in both consecutive
  sign-off runs (iter7-a1 5.31 s, iter8-a1 5.18 s).
- **Mongo ground truth** (db `das`) after every loop: canary links/nodes 0,
  shared symbols + 2026-10-18 E1 canary intact, totals 1864/3710 unchanged.
- **Unit suite** — 123 passed on the pinned upstream client (e12573cc).

Evidence: `memory/omega-das-bridge/evidence/iter{2,3,4,5,6,7,8}-probe/`
(gateway workspace) mirrored in the live Google Doc §16; iteration log in
[`docs/status.md`](../../../docs/status.md).

Residual upstream ask (fork-local draft only, not filed): a delete-apply
ack on the bus would obsolete the oracle's standby/backstop path.
