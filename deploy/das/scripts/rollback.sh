#!/bin/sh
set -eu

task_label='io.ktfh-claw.task=omega-das-integration'

# Every target is selected by the task label. No broad project, name, or dangling-resource
# deletion is used. Volumes are durable by default; pass --purge-data explicitly to erase them.
container_ids=$(docker ps -aq --filter "label=$task_label")
if [ -n "$container_ids" ]; then
  docker rm -f $container_ids
fi

network_ids=$(docker network ls -q --filter "label=$task_label")
if [ -n "$network_ids" ]; then
  docker network rm $network_ids
fi

if [ "${1:-}" = "--purge-data" ]; then
  volume_names=$(docker volume ls -q --filter "label=$task_label")
  if [ -n "$volume_names" ]; then
    docker volume rm $volume_names
  fi
elif [ "$#" -gt 0 ]; then
  echo "usage: $0 [--purge-data]" >&2
  exit 2
else
  echo "task containers and networks removed; task-labeled durable volumes retained"
fi
