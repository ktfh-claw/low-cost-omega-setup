#!/usr/bin/env python3
"""Create offline archives of the two DAS datastore volumes."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tarfile


def archive(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise RuntimeError(f"backup source is not a directory: {source}")
    with tarfile.open(destination, "w:gz", format=tarfile.PAX_FORMAT) as output:
        output.add(source, arcname=source.name, recursive=True)
    os.chmod(destination, 0o644)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: backup-volumes.py /backup")
    destination = Path(sys.argv[1])
    if not destination.is_dir():
        raise RuntimeError(f"backup destination is not a directory: {destination}")
    archive(Path("/source/mongodb"), destination / "mongodb.tar.gz")
    archive(Path("/source/redis"), destination / "redis.tar.gz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
