"""Iteration-6b probe: post-delete visibility matrix (mechanism evidence).

The iteration-6 validation run showed the absence verdict false-alarming at
EVERY tested window width (30/90/300 s) while the deletion itself always
lands -- and the metta path returns 0 answers seconds after the loop exits.
This probe pins the visibility mechanism with a check matrix run before and
right after a grace-0 link delete, plus cross-node and post-idle re-checks:

- P_OLD: the cleanup loop's exact variable-form template (leading symbol
  bound to the variable named ``unassigned``).
- P_NEW: the SAME links through a DIFFERENT token pattern (leading symbol
  ground, variable in a later position, different variable name) --
  validated BEFORE the delete as a positive control (both patterns must
  match the live fact), because an unproven query form that never completes
  would make a post-delete no-match meaningless.

Interpretation:
- P_OLD matches + P_NEW no-match post-delete  -> staleness keyed by the
  exact query pattern (fixable oracle: verify via an alternate pattern).
- Both match on the original node but a FRESH node (B1) sees no-match
  -> staleness keyed per bus node / join.
- Both match until a query-free idle gap passes (A2)     -> the delete
  apply is starved by sustained query traffic.
- Mongo already shows the links gone while queries still match -> the
  apply is fast and the STALE READ is on the query path.

Roles (ROLE env var), separate one-off containers on the write-bridge image:

- A1: service write+verify -> positive-control matrix -> grace-0 link
  delete -> post-delete matrix.
- B1: fresh bus node, matrix re-check (run immediately after A1).
- A2: post-idle matrix re-check (run after a query-free gap).
- A3: bounded real cleanup (grace 60 s) -> unique-node deletion -> metta
  re-query -> handles for the host-side mongo ground truth.

Run (from deploy/das/write-bridge on the OVH host), per container:

  docker compose -f compose.write-bridge.yaml run --rm --name iter6b-a1 \
      -e DAS_CLIENT_ENDPOINT=iter6b-a1:43999 -e ROLE=A1 \
      -v $PWD:/probe:ro write-bridge /probe/tests/iter6b_probe.py

(--name iter6b-b1 / DAS_CLIENT_ENDPOINT=iter6b-b1:43999 / ROLE=B1, etc.)
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
from metta_to_atoms import ground_template_tokens, parse_fact  # noqa: E402
from write_client import DasWriteRunner, WriteFailure  # noqa: E402

ROLE = os.getenv("ROLE", "A1")
CANARY = '(Inheritance (Concept "omega-bridge-canary-20261020-iter6b") (Concept "write-bridge-test"))'
WRITE_BRIDGE = "http://write-bridge:8080/v1/write"
READ_PROXY = "http://read-proxy:8080/v1/query"

FACT = parse_fact(CANARY)
TOP = FACT.expression                      # (Inheritance <inner1> <inner2>)
INNER1 = TOP.elements[1]                   # (Concept "omega-bridge-canary-20261020-iter6b")
TOP_LINK_HANDLE = FACT.top_handle
UNIQUE_NODE_HANDLES = [
    handle
    for atom, handle in zip(FACT.atoms, FACT.handles)
    if atom.arity() == 0 and ("canary-20261020-iter6b" in atom.name or "write-bridge-test" in atom.name)
]
# The (Concept "canary...") link: the first non-top link (bottom-up order).
INNER1_LINK_HANDLE = next(
    handle for handle, _, _ in FACT.link_queries if handle != TOP_LINK_HANDLE
)
# The quoted canary symbol node.
INNER1_NODE_HANDLE = next(
    handle
    for atom, handle in zip(FACT.atoms, FACT.handles)
    if atom.arity() == 0 and "canary-20261020-iter6b" in atom.name
)

# --- query patterns -------------------------------------------------------
# P_OLD: exactly the cleanup loop's template (leading symbol -> $unassigned).
P_OLD_TOP = next(tokens for handle, tokens, _ in FACT.link_queries if handle == TOP_LINK_HANDLE)
P_OLD_INNER1 = next(
    tokens for handle, tokens, _ in FACT.link_queries if handle == INNER1_LINK_HANDLE
)
# P_NEW: the same links through a DIFFERENT pattern -- leading symbol ground,
# variable in a later position, different variable name.
P_NEW_TOP = (
    ["LINK_TEMPLATE", "Expression", str(len(TOP.elements))]
    + ground_template_tokens(TOP.elements[0])
    + ["VARIABLE", "altvar"]
    + ground_template_tokens(TOP.elements[2])
)
P_NEW_INNER1 = (
    ["LINK_TEMPLATE", "Expression", str(len(INNER1.elements))]
    + ground_template_tokens(INNER1.elements[0])
    + ["VARIABLE", "altvar"]
)
# What the P_NEW variable must bind to when the fact is present: the handle
# the deleted link referenced at the variable position.
P_NEW_TOP_EXPECT_ASSIGNMENT = {"altvar": INNER1_LINK_HANDLE}
P_NEW_INNER1_EXPECT_ASSIGNMENT = {"altvar": INNER1_NODE_HANDLE}


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


def check(runner: DasWriteRunner, label: str, tokens: list[str]) -> dict:
    """One bounded query; report whether the target link still matches.

    ``match`` = some answer carries the canary handle in ``handles`` with the
    expected assignment (P_OLD: leading-symbol handle is not tracked here --
    the canary handle alone pins the deleted link; a stale match necessarily
    returns the same handle because the other positions are fully ground).
    """
    started = time.monotonic()
    try:
        answers = runner.query(tokens, max_answers=1, timeout=30)
    except WriteFailure as exc:
        return {"label": label, "utc": now(), "error": str(exc),
                "elapsed_s": round(time.monotonic() - started, 2)}
    matched = False
    for answer in answers:
        if TOP_LINK_HANDLE in answer["handles"] or INNER1_LINK_HANDLE in answer["handles"]:
            matched = True
            break
    return {
        "label": label,
        "utc": now(),
        "match": matched,
        "answers": len(answers),
        "answer_handles": [a["handles"] for a in answers],
        "assignments": [a["assignments"] for a in answers],
        "elapsed_s": round(time.monotonic() - started, 2),
    }


def matrix(runner: DasWriteRunner, prefix: str) -> None:
    print(prefix + "_OLD_TOP", json.dumps(check(runner, prefix + " old-form top link", P_OLD_TOP)))
    print(prefix + "_NEW_TOP", json.dumps(check(runner, prefix + " new-form top link", P_NEW_TOP)))
    print(prefix + "_OLD_INNER", json.dumps(check(runner, prefix + " old-form inner link", P_OLD_INNER1)))
    print(prefix + "_NEW_INNER", json.dumps(check(runner, prefix + " new-form inner link", P_NEW_INNER1)))


if ROLE == "A1":
    # 1. Write + verify through the deployed service (positive write path).
    status, body = http_post(WRITE_BRIDGE, {"metta": CANARY, "verify": True})
    print("A1_SERVICE_WRITE", json.dumps({"http": status, "utc": now(), "body": body}))
    # 2. Positive control: BOTH patterns must match the live fact (proves the
    #    new form completes on the pinned engine; a later no-match is then
    #    meaningful).
    r = DasWriteRunner()
    matrix(r, "CTRL")
    # 3. Grace-0 links-only delete (single verification pass, expected
    #    absent:false -- the measured false alarm).
    result = cleanup(r, CANARY, verify=True, grace_seconds=0, poll_interval=0)
    print("A1_DELETE_GRACE0", json.dumps({"utc": now(), "result": result}))
    # 4. Post-delete matrix on the SAME node, seconds after the delete.
    matrix(r, "POST")

elif ROLE == "B1":
    r = DasWriteRunner()
    matrix(r, "FRESH")

elif ROLE == "A2":
    r = DasWriteRunner()
    matrix(r, "IDLE")

elif ROLE == "A3":
    r = DasWriteRunner()
    started = time.monotonic()
    result = cleanup(r, CANARY, verify=True, grace_seconds=60, poll_interval=5)
    print("A3_CLEANUP_GRACE60", json.dumps({
        "utc": now(), "elapsed_s": round(time.monotonic() - started, 2), "result": result,
    }))
    result = cleanup(r, CANARY, handles=list(UNIQUE_NODE_HANDLES), verify=False)
    print("A3_UNIQUE_NODES", json.dumps({"utc": now(), "result": result}))
    status, body = http_post(READ_PROXY, {
        "metta": '(Inheritance (Concept "omega-bridge-canary-20261020-iter6b") $_1)',
        "max_answers": 10,
    })
    print("A3_METTA_ABSENT", json.dumps({"http": status, "utc": now(), "body": body}))
    print("A3_HANDLES", json.dumps({
        "links": FACT.link_handles,
        "unique_nodes": UNIQUE_NODE_HANDLES,
        "top_link": TOP_LINK_HANDLE,
    }))

else:
    raise SystemExit(f"unknown ROLE {ROLE!r}")
