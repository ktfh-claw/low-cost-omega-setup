#!/bin/sh
set -eu

base_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file=${1:-"$base_dir/.env"}
case "$env_file" in
  /*) ;;
  *) env_file="$(pwd)/$env_file" ;;
esac

if [ ! -f "$env_file" ]; then
  echo "missing environment file: $env_file" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
. "$env_file"
set +a

for name in MONGODB_IMAGE_DIGEST REDIS_IMAGE_DIGEST DAS_IMAGE_DIGEST PYTHON_IMAGE_DIGEST; do
  eval "value=\${$name-}"
  case "$value" in
    sha256:????????????????????????????????????????????????????????????????) ;;
    *) echo "$name must be sha256: followed by exactly 64 characters" >&2; exit 1 ;;
  esac
  hex=${value#sha256:}
  case "$hex" in *[!0-9a-fA-F]*) echo "$name contains non-hex characters" >&2; exit 1;; esac
done

: "${MONGODB_USERNAME:?MONGODB_USERNAME is required}"
: "${MONGODB_PASSWORD:?MONGODB_PASSWORD is required}"
[ "${#MONGODB_PASSWORD}" -ge 20 ] || { echo "MONGODB_PASSWORD must be at least 20 characters" >&2; exit 1; }

"$base_dir/scripts/render-config.sh" "$env_file"
docker compose --env-file "$env_file" -f "$base_dir/compose.yaml" config --quiet
echo "preflight passed"
