"""Canary cleanup procedure for the DAS write bridge.

Deletes the atoms of one MeTTa fact by handle via the atomdb-broker, then
verifies the deletion by read-back (variable-form link queries must return
no answers). Handles are deterministic, so the handle list of a previous
write can be re-derived from the same MeTTa expression.

Deletion is EVENTUAL and the apply is STARVED BY SUSTAINED QUERY TRAFFIC
(live-measured 2026-10-20, bridge iterations 3-6): ``delete_atoms`` is
fire-and-forget like ``add_atoms`` and the server-side apply is not
instantaneous. Every sustained-poll grace window width ever shipped
(30 s / 6 attempts, 90 s / 16, 90 s-poll-5 s / 10, 300 s / 5 s / 32)
false-alarmed ``absent: false`` while the deletion ALWAYS landed -- mongo
ground truth and fresh metta queries confirmed zero residue seconds after
the loop stopped querying. A light-traffic run (iteration 6b) saw absence
at T+7.8 s on the same node+pattern that had just false-alarmed at T+5 s:
the query path is not intrinsically stale, the apply is variable and
loop-coupled.

The verification therefore does NOT poll:

* per-link ALTERNATE-pattern check (iteration-7 oracle): every link that
  admits a tight alternate form (arity >= 3 -- leading symbol ground,
  variable in the first non-leading position, expected assignment pinned;
  live-validated 6b) is checked through that second, differently-shaped
  pattern, which the cleanup traffic itself has not kept warm;
* BOUNDED STANDBY RE-CHECKS: if the alternate check still matches, the
  process WAITS query-free (the query path needs to idle for the apply to
  land) and then re-checks, up to ``--recheck-limit`` times. A re-check is
  the only retry: sustained polling is the mechanism that starves the
  apply. Bus-level failures fail fast -- a failed query is not evidence of
  eventual deletion.

Safety (live-DB measured 2026-10-20, bridge iteration 3): deletion is
immediate and un-acked (fire-and-forget, like add_atoms) and removes
WHATEVER the handles point to. Symbol nodes are SHARED across facts -- in
the live integration DB, Symbol "Inheritance" is the target of 421 other
links and Symbol "Concept" of 791 -- so deleting them would orphan every
fact that reuses the same symbols. The default therefore deletes ONLY the
fact's Expression links (safe under every condition); node deletion is
opt-in:

* ``delete_nodes=True`` (CLI ``--delete-nodes``) also deletes every node
  of the fact -- only for scratch databases whose content the caller owns;
* an explicit ``handles`` list deletes exactly those handles (each entry
  must belong to the fact), e.g. the canary's unique nodes after a default
  link cleanup -- the zero-residue canary procedure on a shared DB.

Bare-node absence cannot be verified through pattern queries (the read-back
walks the fact's link templates), so explicit node deletion reports
``absent: null`` unless link verification runs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from metta_to_atoms import MettaParseError, parse_fact
from write_client import DasWriteRunner, WriteFailure

# Live-measured apply latency is highly variable (iteration 3: 1-2 s;
# iteration 4: >= 10-13 s; iteration 5: 30-96 s; iteration 6b light-traffic
# run: ~7-8 s) and is starved by sustained verification traffic: every
# polling window false-alarmed while the deletion always landed once the
# queries stopped. The oracle design (alternate pattern + query-free
# standby between checks) needs only a small number of re-checks; each
# re-check costs seconds (one bus round-trip per alt-checked link) and the
# standby wait lets the apply land.
DEFAULT_RECHECK_LIMIT = 3
DEFAULT_RECHECK_WAIT_SECONDS = 10.0
# Maximum total wall-clock the standby path may consume; the loop early-exits
# on a clean absent verdict, so this is the pathological-ceiling bound.
MAX_TOTAL_STANDBY_SECONDS = 120.0


def cleanup(
    runner: DasWriteRunner,
    metta: str,
    handles: list[str] | None = None,
    delete_link_targets: bool = False,
    delete_nodes: bool = False,
    verify: bool = True,
    recheck_limit: int = DEFAULT_RECHECK_LIMIT,
    recheck_wait_seconds: float = DEFAULT_RECHECK_WAIT_SECONDS,
) -> dict[str, Any]:
    """Delete a canary fact's atoms and verify its links are gone.

    Returns ``{"deleted": [handles], "absent": bool | None,
    "still_present": [handles], "checks": int, "standby_seconds": float}``.
    ``absent`` is ``None`` when verification was skipped or cannot cover
    the deleted set; ``still_present`` only ever contains link handles
    (nodes are checked transitively through the links that reference them).
    ``checks`` is the number of read-back verification passes issued
    (0 when verification did not run); ``standby_seconds`` is the total
    query-free wait time consumed between passes.
    """
    fact = parse_fact(metta)
    if handles is None:
        # Default scope: the fact's Expression links ONLY. Symbol nodes are
        # shared across facts (live DB: "Inheritance" targeted by 421 other
        # links, "Concept" by 791) and must never be deleted by accident.
        handles = fact.handles if delete_nodes else fact.link_handles
    else:
        handles = list(handles)
        allowed = set(fact.handles)
        foreign = [handle for handle in handles if handle not in allowed]
        if foreign:
            raise ValueError(
                "handle list contains handles that do not belong to the metta "
                "expression: " + ", ".join(foreign)
            )
    runner.delete_atoms(handles, delete_link_targets=delete_link_targets)
    if not verify:
        return _result(handles, None, [], 0, 0.0)
    if not set(fact.link_handles).issubset(set(handles)):
        # The deleted set does not cover every link of the fact, so the
        # link-walk read-back cannot confirm absence of what was deleted
        # (bare nodes are invisible to pattern queries).
        return _result(handles, None, [], 0, 0.0)
    # Absence oracle: per-link alternate-pattern checks with bounded
    # query-free standby between them. The alternate form is the second,
    # differently-shaped pattern (live-validated iteration 6b); a stale
    # primary match can be contradicted by a pattern the cleanup traffic
    # has not kept warm. Sustained polling is the mechanism that starves
    # the server-side delete apply (live-measured iterations 3-6), so the
    # loop waits query-free and re-checks a bounded number of times.
    checks = 0
    standby_total = 0.0
    rechecks = 0
    while True:
        checks += 1
        try:
            still_present = _check_absence(runner, fact)
        except WriteFailure as exc:
            raise WriteFailure(f"deletion verification failed: {exc}", handles) from exc
        if not still_present:
            return _result(handles, True, [], checks, standby_total)
        if rechecks >= max(recheck_limit, 0):
            return _result(handles, False, still_present, checks, standby_total)
        # Query-free standby: the apply lands when the query path idles.
        wait = max(recheck_wait_seconds, 0.0)
        if standby_total + wait > MAX_TOTAL_STANDBY_SECONDS:
            wait = max(MAX_TOTAL_STANDBY_SECONDS - standby_total, 0.0)
        standby_total += wait
        rechecks += 1
        if wait > 0:
            time.sleep(wait)


def _check_absence(runner: DasWriteRunner, fact: Any) -> list[str]:
    """One verification pass: alternate-pattern checks for the links that
    admit a tight alternate form, primary variable-form checks for the rest
    (2-arity and 1-arity links have no tight alternate -- live-measured 6b:
    the loose form is schema-ambiguous on a shared DB).

    Returns the link handles that still match. Bus-level query failures
    raise (the caller fails fast -- a failed query is not evidence of
    eventual deletion).
    """
    still: list[str] = []
    alt_by_handle = {
        handle: (tokens, assignment) for handle, tokens, assignment in fact.link_absence_queries
    }
    for handle, tokens, assignment in fact.link_queries:
        alt = alt_by_handle.get(handle)
        if alt is not None:
            # Alternate oracle pattern: leading symbol ground, variable in
            # the first non-leading position, expected assignment pinned.
            if runner.match_link(alt[0], handle, alt[1]):
                still.append(handle)
        elif runner.match_link(tokens, handle, assignment):
            still.append(handle)
    return still


def _result(
    handles: list[str],
    absent: bool | None,
    still_present: list[str],
    checks: int,
    standby_seconds: float,
) -> dict[str, Any]:
    return {
        "deleted": handles,
        "absent": absent,
        "still_present": still_present,
        "checks": checks,
        "standby_seconds": round(standby_seconds, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DAS write-bridge canary cleanup")
    parser.add_argument("--metta", required=True, help="the canary MeTTa fact (single expression)")
    parser.add_argument(
        "--handle",
        action="append",
        default=None,
        help="atom handle to delete (repeatable); each must belong to the fact; "
        "defaults to the fact's links only",
    )
    parser.add_argument(
        "--delete-nodes",
        action="store_true",
        help="also delete the fact's nodes (scratch DBs only: symbol nodes are "
        "shared across facts on a live DB)",
    )
    parser.add_argument(
        "--delete-link-targets",
        action="store_true",
        help="also delete link targets recursively (broker-side flag)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the read-back absence verification",
    )
    parser.add_argument(
        "--recheck-limit",
        type=int,
        default=DEFAULT_RECHECK_LIMIT,
        help="bounded number of query-free standby re-checks when the alternate "
        "oracle still matches (default 3; sustained polling starves the "
        "server-side delete apply, so the loop waits instead of polling)",
    )
    parser.add_argument(
        "--recheck-wait-seconds",
        type=float,
        default=DEFAULT_RECHECK_WAIT_SECONDS,
        help="query-free standby seconds between absence re-checks (default 10)",
    )
    args = parser.parse_args(argv)
    try:
        result = cleanup(
            DasWriteRunner(),
            args.metta,
            handles=args.handle,
            delete_link_targets=args.delete_link_targets,
            delete_nodes=args.delete_nodes,
            verify=not args.no_verify,
            recheck_limit=args.recheck_limit,
            recheck_wait_seconds=args.recheck_wait_seconds,
        )
    except (MettaParseError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except WriteFailure as exc:
        failure = {"error": str(exc)}
        if exc.handles:
            failure["handles"] = exc.handles
        print(json.dumps(failure), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
