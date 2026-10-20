"""Iteration-7 probe: absence-oracle validation (alternate pattern + standby).

The window matrix (iterations 4-6) proved sustained polling false-alarms at
every width while the deletion always lands once the queries stop -- the
apply is starved by verification traffic. Iteration 7 replaced the grace
window with the absence oracle: per-link ALTERNATE-pattern checks (leading
symbol ground, variable in the first non-leading position, expected
assignment pinned -- live-validated 6b) plus BOUNDED QUERY-FREE standby
re-checks. This probe validates it live:

- PHASE1_SERVICE_WRITE: canary write+verify through the deployed service.
- PHASE2_METTA_VAR: fresh fact readable through the deployed read-proxy.
- PHASE3_CLEANUP_ORACLE: cleanup() with the shipped defaults
  (recheck-limit 3 / recheck-wait 10 s) -- the decisive measurement: does
  the in-window verdict now return absent: true (vs. the guaranteed false
  alarm of every polled window)?
- PHASE4_UNIQUE_NODES: explicit unique-node deletion (zero residue).
- PHASE5_METTA_ABSENT: metta re-query must return 0 answers.
- PHASE6_HANDLES: deterministic handles for the host-side mongo check.

Run (from deploy/das/write-bridge on the OVH host):

  docker compose -f compose.write-bridge.yaml run --rm --name iter7-a1 \
      -e DAS_CLIENT_ENDPOINT=iter7-a1:43999 \
      -v $PWD:/probe:ro write-bridge /probe/tests/iter7_probe.py
"""

import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/probe")

from cleanup import cleanup  # noqa: E402
from metta_to_atoms import parse_fact  # noqa: E402
from write_client import DasWriteRunner  # noqa: E402

CANARY = '(Inheritance (Concept "omega-bridge-canary-20261020-iter7") (Concept "write-bridge-test"))'
WRITE_BRIDGE = "http://write-bridge:8080/v1/write"
READ_PROXY = "http://read-proxy:8080/v1/query"

FACT = parse_fact(CANARY)
UNIQUE_NODE_HANDLES = [
    handle
    for atom, handle in zip(FACT.atoms, FACT.handles)
    if atom.arity() == 0 and ("canary-20261020-iter7" in atom.name or "write-bridge-test" in atom.name)
]
ALT_COVERED = [handle for handle, _, _ in FACT.link_absence_queries]


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S.%f")[:-3]


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


print("PROBE_START", json.dumps({"utc": now(), "canary": CANARY}))
print("ORACLE_SHAPE", json.dumps({
    "links": FACT.link_handles,
    "alt_covered_links": ALT_COVERED,
    "alt_queries": [
        {"handle": handle, "tokens": tokens, "expected_assignment": assignment}
        for handle, tokens, assignment in FACT.link_absence_queries
    ],
}))

# PHASE1: write + verify through the deployed service (service-path evidence).
status, body = http_post(WRITE_BRIDGE, {"metta": CANARY, "verify": True})
print("PHASE1_SERVICE_WRITE", json.dumps({"http": status, "utc": now(), "body": body}))

# PHASE2: the fresh fact is readable through the deployed read-proxy.
status, body = http_post(READ_PROXY, {
    "metta": '(Inheritance (Concept "omega-bridge-canary-20261020-iter7") $_1)',
    "max_answers": 10,
})
print("PHASE2_METTA_VAR", json.dumps({"http": status, "utc": now(), "body": body}))

# PHASE3: cleanup with the shipped oracle defaults -- the decisive phase.
runner = DasWriteRunner()
started = time.monotonic()
result = cleanup(runner, CANARY)
print("PHASE3_CLEANUP_ORACLE", json.dumps({
    "utc": now(),
    "elapsed_s": round(time.monotonic() - started, 2),
    "result": result,
}))

# PHASE4: zero-residue unique-node deletion (explicit handles, no verify:
# bare nodes are invisible to pattern queries).
result = cleanup(runner, CANARY, handles=list(UNIQUE_NODE_HANDLES), verify=False)
print("PHASE4_UNIQUE_NODES", json.dumps({"utc": now(), "result": result}))

# PHASE5: the metta path must return 0 answers now.
status, body = http_post(READ_PROXY, {
    "metta": '(Inheritance (Concept "omega-bridge-canary-20261020-iter7") $_1)',
    "max_answers": 10,
})
print("PHASE5_METTA_ABSENT", json.dumps({"http": status, "utc": now(), "body": body}))

# PHASE6: deterministic handles for the host-side mongo ground truth.
print("PHASE6_HANDLES", json.dumps({
    "links": FACT.link_handles,
    "unique_nodes": UNIQUE_NODE_HANDLES,
    "top_link": FACT.top_handle,
}))
print("PROBE_DONE", json.dumps({"utc": now()}))
