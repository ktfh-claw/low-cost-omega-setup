#!/bin/sh
set -eu
base_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file=${1:-"$base_dir/.env"}
"$base_dir/scripts/preflight.sh" "$env_file"
docker compose --env-file "$env_file" -f "$base_dir/compose.yaml" up -d --wait
