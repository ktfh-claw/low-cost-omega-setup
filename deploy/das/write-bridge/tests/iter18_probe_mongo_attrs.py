"""Iteration-18 probe: issue-2 Phase-0 live probes (transparent provenance).

Two probes that de-risk the v4 design before any facade/plugin changes
(docs/issue-2-implementation-spec.md section 3, P0a + P0b):

P0a -- v4-shaped provenance attributes (metta_expression, provenance_ref,
       provenance_git_commit, provenance_blob_sha256) attached to the fact's
       TOP link persist through the pinned server's add_atoms, and pattern
       answers through the read-proxy carry handles only (no attributes).
P0b -- attribute-overwrite semantics on re-write: the SAME expression
       (deterministic same handles) written twice with DIFFERENT provenance
       payloads -- does the second add_atoms OVERWRITE, MERGE or APPEND the
       top link's custom_attributes? (VERIFY, do not assume; ground truth is
       the host-side mongo inspection between the two probe runs.)

The probe drives ``DasWriteRunner`` DIRECTLY (``add_atoms``), not the
deployed facade: the facade still speaks v2.1 (git:-prefixed citations +
companion atoms) while the probe simulates the v4 decoration contract (top
link only, no companion atom). Spec section 3 explicitly allows hand-running
the runner in the write-bridge container.

Two modes (single canary lifecycle, mongo inspection happens host-side
between the runs):

  write    (default) write A -> read-proxy query -> re-write B (same
           handles, different provenance) -> read-proxy query -> print
           deterministic handles. NO cleanup (the top-link doc must stay
           inspectable).
  cleanup  cleanup oracle (default link deletion) -> explicit unique-node
           deletion -> metta absent check (iter16 zero-residue pattern).

Run (from the deployment tree deploy/das/write-bridge on the OVH host):

  docker compose -f compose.write-bridge.yaml run --rm --name iter18-a1 \
      -e DAS_CLIENT_ENDPOINT=iter18-a1:43999 \
      -v $PWD:/probe:ro write-bridge /probe/tests/iter18_probe_mongo_attrs.py write

  # host-side mongo ground truth here (tests/iter18_groundtruth.js)

  docker compose -f compose.write-bridge.yaml run --rm --name iter18-a2 \
      -e DAS_CLIENT_ENDPOINT=iter18-a2:43999 \
      -v $PWD:/probe:ro write-bridge /probe/tests/iter18_probe_mongo_attrs.py cleanup
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

CANARY = (
    '(Inheritance (Concept "omega-bridge-canary-20261027-iter18") '
    '(Concept "write-bridge-test-20261027-iter18"))'
)
READ_PROXY = "http://read-proxy:8080/v1/query"

# v4-shaped provenance payloads (probe-simulated; the deployed facade still
# speaks v2.1). Distinct refs/commits/shas so overwrite/merge/append is
# distinguishable in the mongo document.
PROV_A = {
    "ref": "https://example.invalid/iter18-source-a.md",
    "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
}
PROV_B = {
    "ref": "https://example.invalid/iter18-source-b.md",
    "commit": "cccccccccccccccccccccccccccccccccccccccc",
    "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
}

MODE = sys.argv[1] if len(sys.argv) > 1 else "write"

FACT = parse_fact(CANARY)
UNIQUE_NODE_HANDLES = [
    handle
    for atom, handle in zip(FACT.atoms, FACT.handles)
    if atom.arity() == 0 and "iter18" in atom.name
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


def decorate_v4(fact, metta: str, prov: dict) -> None:
    """The v4 decoration contract: custom_attributes on the TOP link only."""
    for atom in fact.atoms:
        if atom.handle == fact.top_handle:
            attributes = atom.custom_attributes
            attributes["metta_expression"] = metta
            attributes["provenance_ref"] = prov["ref"]
            attributes["provenance_git_commit"] = prov["commit"]
            attributes["provenance_blob_sha256"] = prov["sha256"]
            return
    raise RuntimeError("top link atom not found in parsed fact")


def write_with_provenance(runner: DasWriteRunner, prov: dict) -> dict:
    """add_atoms with v4-shaped top-link decoration + structural read-back."""
    fact = parse_fact(CANARY)
    decorate_v4(fact, CANARY, prov)
    handles = runner.add_atoms(fact.atoms)
    missing = runner.verify_handles(fact)
    return {
        "written": len(handles),
        "top_handle": fact.top_handle,
        "verified": not missing,
        "missing": missing,
        "same_handles_as_parsed": sorted(handles) == sorted(FACT.handles),
    }


def read_proxy_query() -> tuple[int, dict]:
    return http_post(READ_PROXY, {
        "metta": '(Inheritance (Concept "omega-bridge-canary-20261027-iter18") $_1)',
        "max_answers": 10,
    })


if MODE == "write":
    print("PROBE_START", json.dumps({"utc": now(), "mode": "write", "canary": CANARY}))
    print("ORACLE_SHAPE", json.dumps({
        "top_link": FACT.top_handle,
        "links": FACT.link_handles,
        "unique_nodes": UNIQUE_NODE_HANDLES,
    }))

    runner = DasWriteRunner()

    # P0a: v4-shaped attrs persist through the pinned server's add_atoms and
    # are structurally verified by read-back (service-path evidence).
    result_a = write_with_provenance(runner, PROV_A)
    print("PHASE1_WRITE_A", json.dumps({"utc": now(), "result": result_a}))

    # P0a: pattern answers carry handles only -- custom_attributes must NOT
    # leak into the answer payload.
    status, body = read_proxy_query()
    print("PHASE2_READ_PROXY", json.dumps({"utc": now(), "http": status, "body": body}))

    # P0b: SAME expression re-written with DIFFERENT provenance (same
    # deterministic handles). Overwrite/merge/append is decided by the
    # host-side mongo inspection between this run and the cleanup run.
    result_b = write_with_provenance(runner, PROV_B)
    print("PHASE3_WRITE_B", json.dumps({"utc": now(), "result": result_b}))

    status, body = read_proxy_query()
    print("PHASE4_READ_PROXY", json.dumps({"utc": now(), "http": status, "body": body}))

    # Deterministic handles for the host-side mongo ground truth. NO cleanup
    # here: the top-link document must remain inspectable.
    print("PHASE5_HANDLES", json.dumps({
        "top_link": FACT.top_handle,
        "links": FACT.link_handles,
        "unique_nodes": UNIQUE_NODE_HANDLES,
        "prov_a": PROV_A,
        "prov_b": PROV_B,
    }))
    print("PROBE_DONE", json.dumps({"utc": now(), "mode": "write"}))
elif MODE == "cleanup":
    print("PROBE_START", json.dumps({"utc": now(), "mode": "cleanup", "canary": CANARY}))
    print("ORACLE_SHAPE", json.dumps({
        "top_link": FACT.top_handle,
        "links": FACT.link_handles,
        "unique_nodes": UNIQUE_NODE_HANDLES,
    }))
    runner = DasWriteRunner()

    # Zero-residue canary lifecycle (iter16 pattern): default cleanup deletes
    # the fact's Expression links only (symbol nodes are shared); explicit
    # unique-node deletion afterwards; metta re-query must return 0 answers.
    started = time.monotonic()
    result = cleanup(runner, CANARY)
    print("PHASE1_CLEANUP_ORACLE", json.dumps({
        "utc": now(),
        "elapsed_s": round(time.monotonic() - started, 2),
        "result": result,
    }))

    result = cleanup(runner, CANARY, handles=list(UNIQUE_NODE_HANDLES), verify=False)
    print("PHASE2_UNIQUE_NODES", json.dumps({"utc": now(), "result": result}))

    status, body = read_proxy_query()
    print("PHASE3_METTA_ABSENT", json.dumps({"utc": now(), "http": status, "body": body}))
    print("PHASE4_HANDLES", json.dumps({
        "top_link": FACT.top_handle,
        "links": FACT.link_handles,
        "unique_nodes": UNIQUE_NODE_HANDLES,
    }))
    print("PROBE_DONE", json.dumps({"utc": now(), "mode": "cleanup"}))
else:
    print(json.dumps({"error": f"unknown mode: {MODE} (expected write|cleanup)"}), file=sys.stderr)
    sys.exit(2)
