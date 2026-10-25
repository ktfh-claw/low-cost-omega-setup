#!/usr/bin/env bash
# metta-grammar plugin validation driver runner (2026-10-25).
# Usage: IMAGE=omegaclaw:das-a44739e tests/run_driver.sh <log-path>
#   (IMAGE defaults to the live agent's current tag)
#
# Mounts ALL FOUR plugin dirs (das-write + das-read + pin + metta-grammar)
# plus the updated plugins.yaml.overlay (which lists all four), so the run
# validates the multi-plugin load path exactly as the live agent will boot
# it. DAS plugins stay inert without OMEGA_DAS_* env (gated on os.environ).
set -u
LOG="$1"
IMAGE="${IMAGE:-omegaclaw:das-a44739e}"
cd "$(dirname "$0")/.."   # deploy/omega/plugins/metta-grammar
docker rm -f mettagrammar-test 2>/dev/null || true
docker run --rm --name mettagrammar-test \
  --network omega-das-integration-client \
  --entrypoint sh \
  -v "$PWD":/PeTTa/repos/Omega/plugins/metta-grammar:ro \
  -v "$PWD/../das-read":/PeTTa/repos/Omega/plugins/das-read:ro \
  -v "$PWD/../das-write":/PeTTa/repos/Omega/plugins/das-write:ro \
  -v "$PWD/../pin":/PeTTa/repos/Omega/plugins/pin:ro \
  -v "$PWD/../../plugins.yaml.overlay":/PeTTa/repos/Omega/config/plugins.yaml:ro \
  -v "$PWD/tests/validate_driver.metta":/PeTTa/validate_driver.metta:ro \
  "$IMAGE" \
  -c "cd /PeTTa && su --group nogroup nobody -s /bin/sh -c \"sh run.sh /PeTTa/validate_driver.metta\"" \
  > "$LOG" 2>&1
echo "EXIT=$?" >> "$LOG"
tail -n 60 "$LOG"
