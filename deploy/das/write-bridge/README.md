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
    -> 200 {"handles": ["..."], "verified": true, "missing": []}
```

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
  `{"written": [handles], "verified": bool|null, "missing": [handles]}`.
- `app.py` — bounded HTTP facade (mirrors `deploy/das/proxy/app.py`): body
  cap 16 KiB, metta cap 2048 chars, single-expression rule, same hardening.
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
- Atoms written via the bus carry **no `custom_attributes.metta_expression`**
  (that's a db_loader feature); verification uses handles/targets only.
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

Use fresh, uniquely named content — `add_atoms` upserts, and cleanup deletes
whatever the handles point to (shared/pre-existing atoms would be removed
too).

```bash
# 0) the DAS stack + broker must be up (broker deployed out of compose, see
#    compose.write-bridge.yaml header for the live-verified docker run)

# 1) write + verify (read-back is on by default)
curl -s http://write-bridge:8080/v1/write -H 'Content-Type: application/json' \
  -d '{"metta": "(Inheritance (Concept \"canary-20261019\") (Concept \"write-bridge-test\"))"}'
# -> {"handles": [...], "verified": true, "missing": []}

# 2) cleanup: delete exactly those atoms and verify they are gone
docker compose -f compose.write-bridge.yaml run --rm write-bridge \
  /app/cleanup.py --metta '(Inheritance (Concept "canary-20261019") (Concept "write-bridge-test"))'
# -> {"deleted": [...], "absent": true, "still_present": []}
```

`cleanup.py` re-derives the deterministic handles from the metta expression;
an explicit `--handle` list (repeatable) must match exactly. The broker-side
deletion follows the C++ client's wire format (chunked handle lists with a
trailing `delete_link_targets` flag; `--delete-link-targets` opts into
recursive target deletion). Deletion is fire-and-forget too — the read-back
absence check is what makes the result credible.

## Deployment

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

## Tests

Unit tests with the upstream client **stubbed** (no network, no docker):
`python -m pytest tests/` from this directory (needs only pytest). The
stubbed atoms mirror the pinned hashing formulas; expected handles/wire
tokens embedded in the tests were computed with the real pinned client.
