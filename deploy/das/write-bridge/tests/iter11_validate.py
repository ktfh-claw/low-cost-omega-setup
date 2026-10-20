"""Iteration-11 validation probe: &persistent-hook canary read-back + cleanup.

Follows the iter8-probe harness shape (deployed services, compose run):
- PHASE2_METTA_VAR: the canary fact written by the das-write plugin hook
  (RUN-2, 05:40:52 UTC, through the deployed write-bridge service) must be
  readable through the deployed read-proxy.
- PHASE3_CLEANUP_ORACLE: links-only cleanup with the shipped oracle defaults.
- PHASE4_UNIQUE_NODES: explicit unique-node deletion (zero residue).
- PHASE5_METTA_ABSENT: metta re-query must return 0 answers.
- FACT_HANDLES: deterministic handles for the host-side mongo ground truth.

Run (from deploy/das/write-bridge on the OVH host):

  docker compose -f compose.write-bridge.yaml run --rm --name iter11-validate \
      -e DAS_CLIENT_ENDPOINT=iter11-validate:43999 \
      -v $PWD:/probe:ro write-bridge /probe/tests/iter11_validate.py

(no `python` prefix — the image ENTRYPOINT is already `python`).
"""

import datetime
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/probe")

from cleanup import cleanup  # noqa: E402
from metta_to_atoms import parse_fact  # noqa: E402
from write_client import DasWriteRunner  # noqa: E402

CANARY = '(Inheritance (Concept "omega-das-write-hook-canary-20261020-iter11") (Concept "das-write-hook-test"))'
READ_PROXY = "http://read-proxy:8080/v1/query"

FACT = parse_fact(CANARY)
UNIQUE_NODE_HANDLES = [
    handle
    for atom, handle in zip(FACT.atoms, FACT.handles)
    if atom.arity() == 0 and ("canary-20261020-iter11" in atom.name or "das-write-hook-test" in atom.name)
]


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
print("FACT_HANDLES", json.dumps({
    "links": FACT.link_handles,
    "unique_nodes": UNIQUE_NODE_HANDLES,
    "top_link": FACT.top_handle,
}))

status, body = http_post(READ_PROXY, {
    "metta": '(Inheritance (Concept "omega-das-write-hook-canary-20261020-iter11") $_1)',
    "max_answers": 10,
})
print("PHASE2_METTA_VAR", json.dumps({"http": status, "utc": now(), "body": body}))

runner = DasWriteRunner()
started = time.monotonic()
result = cleanup(runner, CANARY)
print("PHASE3_CLEANUP_ORACLE", json.dumps({
    "utc": now(),
    "elapsed_s": round(time.monotonic() - started, 2),
    "result": result,
}))

result = cleanup(runner, CANARY, handles=list(UNIQUE_NODE_HANDLES), verify=False)
print("PHASE4_UNIQUE_NODES", json.dumps({"utc": now(), "result": result}))

status, body = http_post(READ_PROXY, {
    "metta": '(Inheritance (Concept "omega-das-write-hook-canary-20261020-iter11") $_1)',
    "max_answers": 10,
})
print("PHASE5_METTA_ABSENT", json.dumps({"http": status, "utc": now(), "body": body}))

print("PROBE_DONE", json.dumps({"utc": now()}))
