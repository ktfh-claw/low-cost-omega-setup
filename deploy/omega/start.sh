#!/usr/bin/env bash
set -euo pipefail

container=omega-curiosity
image=omegaclaw:das-f38217f

cleanup() {
  /usr/bin/docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

/usr/bin/docker create --rm --name "$container" -t \
  --security-opt no-new-privileges:true --init \
  --tmpfs /tmp:size=256m,mode=1777 \
  --tmpfs /var/tmp:size=64m,mode=1777 \
  --tmpfs /run:size=16m,mode=755 \
  --volume omega-curiosity-memory:/PeTTa/repos/Omega/memory \
  --volume /home/ubuntu/low-cost-omega-setup/deploy/omega/plugins/das-write:/PeTTa/repos/Omega/plugins/das-write:ro \
  --volume /home/ubuntu/low-cost-omega-setup/deploy/omega/plugins.yaml.overlay:/PeTTa/repos/Omega/config/plugins.yaml:ro \
  --volume /home/ubuntu/low-cost-omega-setup/deploy/omega/das-read/das_skills.py:/PeTTa/repos/Omega/src/das_skills.py:ro \
  --volume /home/ubuntu/omega-curiosity/config-overlay.yaml:/PeTTa/repos/Omega/config/config.yaml:ro \
  --env-file /home/ubuntu/omega-curiosity/runtime.env \
  "$image" \
  commchannel=telegram provider=ASIOne model=asi1-ultra embeddingprovider=Local telegramAutonomousWake \
  dasWriteEnabled=1 dasWriteOrigin=http://write-bridge:8080 \
  >/dev/null

# The default bridge supplies outbound Telegram/ASI:One connectivity. The
# internal client network supplies only bounded DAS read-proxy access.
/usr/bin/docker network connect omega-das-integration-client "$container"

set +e
/usr/bin/docker start --attach "$container"
status=$?
set -e
case "$status" in
  0|137|143) exit 0 ;;
  *) exit "$status" ;;
esac
