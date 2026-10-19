#!/bin/sh
set -eu

base_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file=${1:-"$base_dir/.env"}

if [ ! -f "$env_file" ]; then
  echo "missing environment file: $env_file" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$env_file"
set +a
: "${MONGODB_USERNAME:?MONGODB_USERNAME is required}"
: "${MONGODB_PASSWORD:?MONGODB_PASSWORD is required}"

mkdir -p "$base_dir/generated"
MONGODB_USERNAME=$MONGODB_USERNAME MONGODB_PASSWORD=$MONGODB_PASSWORD \
  python3 - "$base_dir/config/config.json.template" "$base_dir/generated/config.json" <<'PY'
import json
import os
import pathlib
import sys

source, destination = map(pathlib.Path, sys.argv[1:])
document = json.loads(source.read_text(encoding="utf-8"))
mongodb = document["atomdb"]["mongodb"]
mongodb["username"] = os.environ["MONGODB_USERNAME"]
mongodb["password"] = os.environ["MONGODB_PASSWORD"]
destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
# The bind-mounted file must be readable by the image's unrelated nonroot UID.
# Keep write access owner-only; the enclosing host home directory is the host
# access boundary (see README.md).
destination.chmod(0o644)
PY
