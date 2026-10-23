#!/usr/bin/env bash
# das-read plugin validation driver runner (iteration 31, alignment lane;
# v3: IMAGE env var so validation matches the live runtime).
# Usage: IMAGE=omegaclaw:das-a44739e tests/run_driver.sh <log-path> [enabled|disabled]
#   (IMAGE defaults to the live agent's current tag; MODE defaults to enabled)
#
# Mounts BOTH plugin dirs (das-write + das-read) plus the updated
# plugins.yaml.overlay (which lists both), so the run validates the
# multi-plugin load path exactly as the live agent will boot it.
# OMEGA_* env keys survive the image env handling (stock config machinery
# reads OMEGA_<key>); the v2 module gates on os.environ directly.
set -u
LOG="$1"; MODE="${2:-enabled}"
IMAGE="${IMAGE:-omegaclaw:das-a44739e}"
cd "$(dirname "$0")/.."   # deploy/omega/plugins/das-read
ENVFLAGS="-e OMEGA_DAS_ENABLED=1 -e OMEGA_DAS_PROXY_ORIGIN=http://read-proxy:8080"
if [ "$MODE" = "disabled" ]; then ENVFLAGS=""; fi
docker rm -f dasread-test 2>/dev/null || true
docker run --rm --name dasread-test \
  --network omega-das-integration-client \
  --entrypoint sh \
  $ENVFLAGS \
  -v "$PWD":/PeTTa/repos/Omega/plugins/das-read:ro \
  -v "$PWD/../das-write":/PeTTa/repos/Omega/plugins/das-write:ro \
  -v "$PWD/../pin":/PeTTa/repos/Omega/plugins/pin:ro \
  -v "$PWD/../../plugins.yaml.overlay":/PeTTa/repos/Omega/config/plugins.yaml:ro \
  -v "$PWD/tests/validate_driver.metta":/PeTTa/validate_driver.metta:ro \
  "$IMAGE" \
  -c "cd /PeTTa && su --group nogroup nobody -s /bin/sh -c \"sh run.sh /PeTTa/validate_driver.metta\"" \
  > "$LOG" 2>&1
echo "EXIT=$?" >> "$LOG"
tail -n 80 "$LOG"
