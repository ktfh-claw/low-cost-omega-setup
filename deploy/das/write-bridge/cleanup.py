"""Canary cleanup procedure for the DAS write bridge.

Deletes the atoms of one MeTTa fact by handle via the atomdb-broker, then
verifies the deletion by read-back (structural ground queries must return no
answers). Handles are deterministic, so the handle list of a previous write
can be re-derived from the same MeTTa expression; if an explicit handle list
is supplied it must match exactly.

Safety: deletion is immediate and un-acked (fire-and-forget, like add_atoms)
and it removes WHATEVER the handles point to. Atoms that already existed
before a canary write (add_atoms upserts) would be deleted too -- run the
canary procedure only with fresh, uniquely named content.
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
    verify: bool = True,
) -> dict[str, Any]:
    """Delete a canary fact's atoms and verify they are gone.

    Returns ``{"deleted": [handles], "absent": bool | None,
    "still_present": [handles]}``. ``absent`` is ``None`` when verification
    was skipped; ``still_present`` only ever contains link handles (nodes
    are checked transitively through the links that reference them).
    """
    fact = parse_fact(metta)
    expected = fact.handles
    if handles is None:
        handles = expected
    else:
        handles = list(handles)
        if sorted(handles) != sorted(expected):
            raise ValueError(
                "handle list does not match the deterministic handles of the metta expression"
            )
    runner.delete_atoms(handles, delete_link_targets=delete_link_targets)
    if not verify:
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
        help="expected atom handle (repeatable); defaults to the deterministic handles of --metta",
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
