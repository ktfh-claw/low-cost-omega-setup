"""Iteration-5 probe: Phase-1 sign-off canary through the DEPLOYED SERVICE.

Unlike iterations 2-4 (scratch containers importing the bridge code directly),
this canary exercises the full deployed surface:

- P1 write + read-back verification goes through the deployed write-bridge
  SERVICE (HTTP POST http://write-bridge:8080/v1/write).
- P2 metta-mode read goes through the deployed read-proxy service.
- P4/P4B cleanup runs in THIS one-off container (unique bus node id, provided
  by the run command) using the bridge code mounted read-only at /probe --
  compose-run one-offs must override DAS_CLIENT_ENDPOINT so they never share
  a node id with the live service.

Expected: P1 verified: true; P2 fresh fact returned; P4 absent: true inside
the widened 90 s grace window (re-widened this iteration: the 30 s window
false-alarmed again on a ~33 s apply); P5 zero answers; host-side mongo then
confirms zero residue.

Run (from deploy/das/write-bridge on the OVH host):

  docker compose -f compose.write-bridge.yaml run --rm --name iter5-probe \
      -e DAS_CLIENT_ENDPOINT=iter5-probe:43999 \
      -v $PWD:/probe:ro \
      write-bridge /probe/tests/iter5_probe.py

The node-id host part MUST be the run container's own --name (docker DNS
resolves container names on user-defined networks): the ServiceBus BINDS its
callback ports on that host, and an unresolvable name fails the bind
(live-discovered this iteration: getaddrinfo("iter5-probe:43300") failure
when the container had no such name).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/probe")

from cleanup import cleanup  # noqa: E402
from metta_to_atoms import parse_fact  # noqa: E402
from write_client import DasWriteRunner, WriteFailure  # noqa: E402

CANARY = '(Inheritance (Concept "omega-bridge-canary-20261020-iter5") (Concept "write-bridge-test"))'
WRITE_BRIDGE = "http://write-bridge:8080/v1/write"
READ_PROXY = "http://read-proxy:8080/v1/query"

FACT = parse_fact(CANARY)
# Unique-to-this-canary quoted-string symbol nodes (shared Symbol nodes are
# NEVER deleted on the live DB).
UNIQUE_NODE_HANDLES = [
    handle
    for atom, handle in zip(FACT.atoms, FACT.handles)
    if atom.arity() == 0 and ("canary-20261020-iter5" in atom.name or "write-bridge-test" in atom.name)
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


# Phase 1: canary write + read-back verification THROUGH THE DEPLOYED SERVICE.
status, body = http_post(WRITE_BRIDGE, {"metta": CANARY, "verify": True})
print("PHASE1_SERVICE_WRITE", json.dumps({"http": status, "body": body}))

# Phase 2: metta-mode read of the fresh fact through the deployed read-proxy.
status, body = http_post(READ_PROXY, {
    "metta": '(Inheritance (Concept "omega-bridge-canary-20261020-iter5") $_1)',
    "max_answers": 10,
})
print("PHASE2_METTA_VAR", json.dumps({"http": status, "body": body}))

# Phase 4: links-only cleanup with the DEFAULT widened 90 s grace window
# (re-widened this iteration after the 30 s window false-alarmed again).
# POLL INTERVAL IS PARAMETRIZABLE for the starvation validation: with poll 1 s
# the loop's own query traffic keeps the broker busy and the delete apply
# kept landing only AFTER the loop exited (runs A+B). Sparse polling
# (ITER5_POLL_INTERVAL=5) leaves the broker idle gaps to apply the delete.
# The runner in THIS container joins the broker with a unique node id
# (DAS_CLIENT_ENDPOINT=iter5-probe:43999).
runner = None
try:
    runner = DasWriteRunner()
    print("PHASE0_BUS_JOIN OK")
except Exception as exc:  # noqa: BLE001
    print("PHASE0_BUS_JOIN_ERROR", json.dumps({"error": repr(exc)}))

if runner is not None:
    try:
        started = time.monotonic()
        result = cleanup(runner, CANARY, verify=True,
                         poll_interval=float(os.getenv("ITER5_POLL_INTERVAL", "1")))
        print("PHASE4_CLEANUP", json.dumps({
            "elapsed_s": round(time.monotonic() - started, 2),
            "result": result,
        }))
    except Exception as exc:  # noqa: BLE001
        print("PHASE4_CLEANUP_GRACE30_ERROR", json.dumps({"error": repr(exc)}))

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
    "metta": '(Inheritance (Concept "omega-bridge-canary-20261020-iter5") $_1)',
    "max_answers": 10,
})
print("PHASE5_METTA_ABSENT", json.dumps({"http": status, "body": body}))

# Phase 6: deterministic handles (for the host-side mongo ground-truth check).
print("PHASE6_HANDLES", json.dumps({
    "links": FACT.link_handles,
    "unique_nodes": UNIQUE_NODE_HANDLES,
    "top_link": FACT.top_handle,
}))
