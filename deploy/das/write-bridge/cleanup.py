"""Canary cleanup procedure for the DAS write bridge.

Deletes the atoms of one MeTTa fact by handle via the atomdb-broker, then
verifies the deletion by read-back (variable-form link queries must return
no answers). Handles are deterministic, so the handle list of a previous
write can be re-derived from the same MeTTa expression.

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
from typing import Any

from metta_to_atoms import MettaParseError, parse_fact
from write_client import DasWriteRunner, WriteFailure


def cleanup(
    runner: DasWriteRunner,
    metta: str,
    handles: list[str] | None = None,
    delete_link_targets: bool = False,
    delete_nodes: bool = False,
    verify: bool = True,
) -> dict[str, Any]:
    """Delete a canary fact's atoms and verify its links are gone.

    Returns ``{"deleted": [handles], "absent": bool | None,
    "still_present": [handles]}``. ``absent`` is ``None`` when verification
    was skipped; ``still_present`` only ever contains link handles (nodes
    are checked transitively through the links that reference them).
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
        return {"deleted": handles, "absent": None, "still_present": []}
    if not set(fact.link_handles).issubset(set(handles)):
        # The deleted set does not cover every link of the fact, so the
        # link-walk read-back cannot confirm absence of what was deleted
        # (bare nodes are invisible to pattern queries).
        return {"deleted": handles, "absent": None, "still_present": []}
    try:
        still_present = runner.verify_handles(fact)
    except WriteFailure as exc:
        raise WriteFailure(f"deletion verification failed: {exc}", handles) from exc
    return {"deleted": handles, "absent": not still_present, "still_present": still_present}


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
    args = parser.parse_args(argv)
    try:
        result = cleanup(
            DasWriteRunner(),
            args.metta,
            handles=args.handle,
            delete_link_targets=args.delete_link_targets,
            delete_nodes=args.delete_nodes,
            verify=not args.no_verify,
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
