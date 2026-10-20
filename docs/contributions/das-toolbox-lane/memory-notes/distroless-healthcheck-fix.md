# Distroless DAS health-check defect fix evidence

Date: 2026-10-03 UTC

Repository: `/home/claw/.openclaw/workspace/repos/das-toolbox`

Branch: `omega-das-integration`

## Defect and resolution

The deployment assigned `CMD-SHELL` / `kill -0 1` health checks to the `attention-broker` and `query-engine` services. Their `trueagi/das` image is distroless and has no `/bin/sh`, so those probes could never execute and made a listening DAS container permanently unhealthy.

The two DAS health checks were removed. MongoDB and Redis retain their native-client health checks. The query engine now gates the attention broker with `condition: service_started`, the strongest Compose condition justified by repository source because no DAS health RPC or image-provided probe command is defined. This intentionally does not claim that container start proves readiness.

The deployment README now requires post-start verification of:

1. attention-broker and query-engine container state and logs;
2. the private-network listeners at `attention-broker:40001` and `query-engine:40002`, checked from already-approved attached containers; and
3. a representative read-only query with the expected result.

## Static validation performed

No Docker command or external call was run.

- `sh -n deploy/omega-das-integration/scripts/*.sh`: passed.
- `python3 -m json.tool deploy/omega-das-integration/config/config.json.template`: passed.
- PyYAML `safe_load` of `compose.yaml`: passed.
- Static policy assertions for the exact service set, native database checks, absent DAS checks, database `service_healthy` conditions, attention-broker `service_started`, digest-pinned DAS image expression, and absent host networking/port publications: passed.
- `git diff --check`: passed.

## Validation boundary

Runtime startup, listener state, log cleanliness, and query correctness remain unproven because this task explicitly prohibited Docker execution. The documented operator checks are mandatory before the deployment is considered operational. No commit or push was made.
