"""Iteration-6 probe: validate the re-tuned cleanup DEFAULTS (300 s / 5 s).

Same deployed-surface canary as iteration 5 (write + verify through the
live write-bridge service, metta read through the deployed read-proxy), but
the cleanup loop now runs with the SHIPPED DEFAULTS — no poll override — to
prove the widened window resolves `absent: true` in-window on the live
apply latency (~90-96 s worst measured, iteration 5 runs C/D).

Expected: P1 verified: true; P2 fresh fact returned; P4 absent: true
INSIDE the default 300 s window (first true in-window verdict); P5 zero
answers; host-side mongo then confirms zero residue.

Run (from deploy/das/write-bridge on the OVH host, after tree sync):

  docker compose -f compose.write-bridge.yaml run --rm --name iter6-probe \
      -e DAS_CLIENT_ENDPOINT=iter6-probe:43999 \
      -v $PWD:/probe:ro \
      write-bridge /probe/tests/iter6_probe.py

Ops rules (live-discovered iteration 5): the node-id host part MUST be the
run container's own --name (ServiceBus binds its callback ports on that
host; docker DNS resolves container names on user-defined networks), and a
one-off MUST override DAS_CLIENT_ENDPOINT so it never shares a node id with
the live service.
"""

import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/probe")

import cleanup as cleanup_module  # noqa: E402
from cleanup import cleanup  # noqa: E402
from metta_to_atoms import parse_fact  # noqa: E402
from write_client import DasWriteRunner  # noqa: E402

CANARY = '(Inheritance (Concept "omega-bridge-canary-20261020-iter6") (Concept "write-bridge-test"))'
WRITE_BRIDGE = "http://write-bridge:8080/v1/write"
READ_PROXY = "http://read-proxy:8080/v1/query"

FACT = parse_fact(CANARY)
# Unique-to-this-canary quoted-string symbol nodes (shared Symbol nodes are
# NEVER deleted on the live DB).
UNIQUE_NODE_HANDLES = [
    handle
    for atom, handle in zip(FACT.atoms, FACT.handles)
    if atom.arity() == 0 and ("canary-20261020-iter6" in atom.name or "write-bridge-test" in atom.name)
]


def http_post(url: str, payload: dict, timeout: float = 70.0) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
            return response.status, {"elapsed_s": round(time.monotonic() - started, 2), **body}
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")[:500]
        return error.code, {"elapsed_s": round(time.monotonic() - started, 2), "error": body}


# Defaults under validation (fail fast if the tree is not the retuned one).
assert cleanup_module.DEFAULT_VERIFY_GRACE_SECONDS == 300.0, "expected the iteration-6 default grace"
assert cleanup_module.DEFAULT_VERIFY_POLL_INTERVAL == 5.0, "expected the iteration-6 default poll"

# Phase 1: canary write + read-back verification THROUGH THE DEPLOYED SERVICE.
status, body = http_post(WRITE_BRIDGE, {"metta": CANARY, "verify": True})
print("PHASE1_SERVICE_WRITE", json.dumps({"http": status, "body": body}))

# Phase 2: metta-mode read of the fresh fact through the deployed read-proxy.
status, body = http_post(READ_PROXY, {
    "metta": '(Inheritance (Concept "omega-bridge-canary-20261020-iter6") $_1)',
    "max_answers": 10,
})
print("PHASE2_METTA_VAR", json.dumps({"http": status, "body": body}))

# Phase 4: links-only cleanup with the SHIPPED DEFAULTS (300 s grace / 5 s
# poll, re-tuned this iteration after 30/90 s windows both false-alarmed on
# ~33-96 s applies). No poll override: the defaults themselves are what this
# probe validates. The runner in THIS container joins the broker with a
# unique node id (DAS_CLIENT_ENDPOINT=iter6-probe:43999).
runner = None
try:
    runner = DasWriteRunner()
    print("PHASE0_BUS_JOIN OK")
except Exception as exc:  # noqa: BLE001
    print("PHASE0_BUS_JOIN_ERROR", json.dumps({"error": repr(exc)}))

if runner is not None:
    try:
        started = time.monotonic()
        result = cleanup(runner, CANARY, verify=True)
        print("PHASE4_CLEANUP_DEFAULTS", json.dumps({
            "elapsed_s": round(time.monotonic() - started, 2),
            "result": result,
        }))
    except Exception as exc:  # noqa: BLE001
        print("PHASE4_CLEANUP_ERROR", json.dumps({"error": repr(exc)}))

    # Phase 4B: zero-residue -- delete the canary's UNIQUE nodes by explicit
    # handle (fire-and-forget; host-side mongo verifies afterwards).
    try:
        started = time.monotonic()
        result = cleanup(runner, CANARY, handles=list(UNIQUE_NODE_HANDLES), verify=False)
        print("PHASE4B_UNIQUE_NODES", json.dumps({
            "elapsed_s": round(time.monotonic() - started, 2),
            "result": result,
        }))
    except Exception as exc:  # noqa: BLE001
        print("PHASE4B_UNIQUE_NODES_ERROR", json.dumps({"error": repr(exc)}))

# Phase 5: post-cleanup metta-mode re-query (expect 0 answers).
status, body = http_post(READ_PROXY, {
    "metta": '(Inheritance (Concept "omega-bridge-canary-20261020-iter6") $_1)',
    "max_answers": 10,
})
print("PHASE5_METTA_ABSENT", json.dumps({"http": status, "body": body}))

# Phase 6: deterministic handles (for the host-side mongo ground-truth check).
print("PHASE6_HANDLES", json.dumps({
    "links": FACT.link_handles,
    "unique_nodes": UNIQUE_NODE_HANDLES,
    "top_link": FACT.top_handle,
}))
