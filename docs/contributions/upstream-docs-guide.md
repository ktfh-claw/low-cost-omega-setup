# Upstream docs draft — "Writing atoms from external agents" guide (ladder item 6)

**Target:** singnet/das · **Type:** docs (new file, e.g. `docs/writing-atoms-from-external-agents.md`) ·
**Status:** DRAFT — filing upstream requires Balázs's explicit go-ahead.
**Relationship to code:** documentation only. The deployment it documents is config-only (no source forks); the example code is the pinned upstream python client's own API.

## Why

The atomdb-broker exists and is documented only as an internal agent of the DAS
service-bus stack. External agents that need to write atoms (bulk-load history,
persist learned knowledge) currently have no documented path: the README shows
the full multi-agent stack but never shows a third-party process joining the
bus and issuing `add_atoms`/`delete_atoms`. Everything below was
live-verified 2026-10-18 → 2026-10-20 on a production-identical docker
deployment (MongoDB + Redis + attention-broker + query-engine + atomdb-broker,
`trueagi/das` image) while integrating an external agent (Omega) with DAS.

## Suggested guide content (this is the draft text, adapted to upstream docs style)

### Deploying the atomdb-broker for external writers

The broker is the only DAS component an external writer needs to reach. In a
compose stack where all services share a `backend` network, deploy one more
`trueagi/das` instance as a service-bus node running the atomdb-broker
(live-verified invocation; adapt the config-file mount to your deployment):

```yaml
atomdb-broker:
  image: trueagi/das:<tag>
  command: ["busnode", "--service=atomdb-broker", "--endpoint=0.0.0.0:40007",
           "--ports-range=47000:47999", "--atomdb-type=redismongodb",
           "--config=/etc/das/config.json"]
  volumes: ["./generated/config.json:/etc/das/config.json:ro"]
  networks: [backend, client]
```

Two properties of the broker matter to external clients (both
live-discovered; see "Deployment invariants" below):

- it binds `0.0.0.0` (the `--endpoint` host must be the wildcard, not a
  hostname), and announces a wildcard host to peers — clients need the
  rewrite described below;
- it must be reachable by DNS name from the client network. With docker's
two-network limitation (`docker run` keeps DNS records only for the last
`--network`), attach the second network explicitly with an alias:

```bash
docker network connect --alias atomdb-broker <client-network> <broker-container>
```

### Joining the bus and writing atoms from Python

An external writer joins the broker's service bus directly with the pinned
python client (`3rd_party_slots/python_client`). Two buses are recommended:
one that can only route `atomdb` (joined to the broker) and one that can only
route `pattern_matching_query` (joined to the query-engine) — see invariant 2.

```python
from hyperon_das.commons.atoms import Link, Node
from hyperon_das.service_bus.service_bus import ServiceBus
from hyperon_das.service_clients import AtomDBProxy

atom_bus = ServiceBus(
    host_id="my-agent:45900",            # this process's bus node id
    known_peer="atomdb-broker:40007",    # the broker's bus endpoint
    commands=["atomdb"],
    port_lower=45900,
    port_upper=45910,
)

proxy = AtomDBProxy()
atom_bus.issue_bus_command(proxy)
# The broker's server-side proxy node attaches ASYNCHRONOUSLY; the
# peer is usable once proxy.proxy_node.peer_id is set.
handles = proxy.add_atoms(list_of_atoms, use_streaming=False)
proxy.graceful_shutdown()
```

Atoms are built with the client's own `Node`/`Link` classes
(`hyperon_das.commons.atoms`); handles are deterministic hashes, so the same
atoms always map to the same handles. `add_atoms` chunkifies at
`COMMAND_SIZE_LIMIT` atoms per bus command (5000 in the python client, 50 in
the C++ client) and returns **client-side-computed handles — not server
acknowledgements** (see the caveat below). The python client currently has no
`delete_atoms`; the C++ client does (chunked handle lists + a trailing
delete-link-targets flag), and both commands share the same fire-and-forget
semantics.

### The three deployment invariants (each one broke a real integration before it was discovered)

1. **The broker binds `0.0.0.0`** — not a hostname. A client that joins a peer
   which later advertises a wildcard host must rewrite the advertised
   `host:port` node id to a routable name, or callbacks are undeliverable. In
   the python client, `DistributedAlgorithmNodeManager.node_joined_network` is
   the interception point: when the joining node id's host is `0.0.0.0`, replace
   it with the known peer's DNS name (keep the port).
2. **Clients join the broker DIRECTLY for `atomdb` commands.** Never point an
   `atomdb` command at the query-engine's bus endpoint: an unregistered-command
   `std::runtime_error` (uncaught) crashes the query-engine process (see the
   issue draft `issue-1-qe-crash.md` in this folder). Keep the command sets of
   separate buses structurally disjoint — one command per bus, one directly
   joined peer per bus.
3. **The callback-peer rewrite host is the broker's DNS name** for atomdb
   commands (and the query-engine's name for pattern queries on the other bus).

### Fire-and-forget caveat — read-back verification is mandatory

`AtomDBProxy.add_atoms` and `delete_atoms` are both fire-and-forget: the broker
processes them asynchronously and neither ever returns a server-side ack. A
guide that stops at "call `add_atoms`" would set integrators up for silent
write loss and phantom deletes. Two behaviors are worth documenting explicitly:

- **Write:** verify by query. Each written link is checked with a
  LINK_TEMPLATE that has exactly one variable (e.g. the leading symbol
  position); the engine completes such variable-form templates and returns the
  bound assignment, which pins the link's content. (A fully-ground template
  never completes on the current engine — it answers an error string and hangs
  until client timeout.)
- **Delete:** the server-side apply latency is variable (measured anywhere
  between ~1 s and ~95 s) and is **starved by sustained query traffic**: a
  polling "is it gone yet?" loop measurably keeps the apply from landing while
  it runs, and the deletion lands seconds after the loop stops. Integrators
  should not poll; verify absence through a *differently-shaped* alternate
  pattern (not the freshly-written one) and otherwise wait query-free before
  re-checking. The proper upstream fix is an apply ack (draft recommendation in
  this folder); until then, treat `delete_atoms` as eventual.

### MeTTa-mode queries (read-back through the query-engine)

The query-engine answers MeTTa-form queries when the client sets
`use_metta_as_query_tokens`. **Known upstream defect:** the server reads
`use_metta_as_query_tokens` (`src/agents/BaseQueryProxy.cc`) while the python
client constant is misspelled `user_metta_as_query_tokens`
(`3rd_party_slots/python_client/hyperon_das/service_clients/base.py`), so
passing the client-side spelling is a silent no-op (issue draft
`issue-2-client-typo.md`; fork-local fix branch
`ktfh-claw/das@fix/python-client-metta-typo`). The guide should document the
correct spelling of the parameter at `set_parameter` level until the typo is
fixed.

### Interop notes discovered while validating this path (optional subsections)

- The C++ engine emits **nested handle vectors** in query answers; the current
  python client decodes the vector count as a flat handle count and misreads
  normal answers. Integrators on the python client may need to decode the
  nested form until the client catches up.
- The das-metta-parser lexer **silently drops `<`/`>` from bare symbols**
  (issue draft 3) and **raw newlines terminate quoted strings** (issue draft 5)
  — relevant to anyone bulk-loading MeTTa history through `db_loader`; the
  caller-side newline-escape fallback carries a real corpus from 98.2% to
  99.17% gate yield.

## Evidence available on filing

Every claim above has live logs in the bridge repo (OVH deployment, production
identical): crash repro for invariant 2; wire-level callback rewrite repro for
invariant 3; the measured 30/90/300-second false-alarm matrix and the
alternate-pattern oracle that replaced polling; the metta-mode end-to-end
read-back; the corpus numbers for the parser notes. The guide text itself is
documentation of upstream behavior — no bridge-specific code is required to
reproduce any of it.

## Disposition

Drafted in the bridge repo per the standing rule: nothing is filed upstream
without Balázs's explicit go-ahead. On approval, this becomes a PR against
`singnet/das` adding the guide (file name and placement to be agreed with
maintainers; `docs/` follows mixed conventions) — ideally after issue drafts
1–5 are filed, so the guide can reference them instead of inlining defect
details.
