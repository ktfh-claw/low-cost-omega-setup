# Secure deployment implementation evidence

Date: 2026-10-03 UTC

Repository: `/home/claw/.openclaw/workspace/repos/das-toolbox`

Branch: `omega-das-integration`

## Scope implemented

Added a task-local deployment lane under `deploy/omega-das-integration/` containing:

- `compose.yaml`: MongoDB, Redis, attention broker, and query engine only.
- `config/config.json.template`: container-DNS DAS configuration for the retrieval path.
- `.env.example`: digest-only image inputs and database credential inputs.
- `scripts/render-config.sh`: JSON-safe credential injection into an ignored generated file.
- `scripts/preflight.sh`: fail-closed digest/credential validation and Compose validation.
- `scripts/up.sh`: preflight followed by a health-gated start.
- `scripts/rollback.sh`: label-scoped removal with durable data retained unless `--purge-data` is explicit.
- `README.md`: deployment, private-client access, limitations, and rollback procedure.

No existing source file was modified. No package was installed. No Docker command, image pull, deployment, push, or publication was performed.

## Source derivation

The service set and commands were derived from repository source rather than guessed:

- MongoDB image family/version and `mongod --bind_ip_all --port ...` behavior: `das-cli/src/settings/config.py` and `das-cli/src/common/container_manager/atomdb/mongodb_container_manager.py`.
- Redis image family/version and `redis-server` invocation: `das-cli/src/settings/config.py` and `das-cli/src/common/container_manager/atomdb/redis_container_manager.py`. This lane changes unsafe source defaults by enabling persistence and protected mode.
- Attention broker command: `AttentionBrokerManager._gen_attention_broker_command()` in `das-cli/src/common/container_manager/agents/attention_broker_container_manager.py`.
- Query-engine command and flags: `BusNodeCommandRegistry._gen_default_cmd()` and `cmd_query_engine()` in `das-cli/src/common/bus_node/busnode_command_registry.py`.
- Required dependency set: `das-cli/src/commands/query_agent/query_agent_module.py` and the start guard in `query_agent_cli.py`.
- Configuration shape: packaged/test configuration and `das-cli/tests/integration/fixtures/config/simple.json`.

## Safety properties checked

- No service has `network_mode: host` or a `ports` publication.
- The database/backend network is internal.
- The distinct client network is internal and reaches only the query engine; MongoDB and Redis are backend-only.
- All images use repository plus mandatory digest interpolation; missing/malformed digest values fail closed.
- MongoDB and Redis have explicitly named, task-labeled durable volumes.
- MongoDB and Redis have native-client health checks; no unprovable in-container health check is assigned to either distroless DAS service.
- The query engine waits for MongoDB and Redis to become healthy and for the attention broker container to start, the strongest condition supported without inventing DAS health semantics.
- No loader or write-oriented agent is deployed.
- Rollback uses the exact task label and never invokes a global prune. Data deletion is separately opt-in.

## Local non-Docker validation

All allowed checks passed:

1. `sh -n` over all four shell scripts: passed.
2. `python3 -m json.tool` over `config.json.template`: passed.
3. PyYAML `safe_load` of `compose.yaml`: passed.
4. Python policy assertions for exact service set, absent port/network-mode fields, task labels, health checks, digest references, internal networks, network separation, and explicit volume names: passed.
5. `render-config.sh` with a temporary environment file, followed by parsed JSON assertions for credentials and MongoDB/Redis endpoints: passed.
6. `git diff --check --no-index` for every added text/script asset: passed.

`shellcheck` and `yq` were not installed, so they were not available checks. They were not installed because the task prohibited package installation. `docker compose config` is built into preflight but was not executed because the task explicitly prohibited running Docker.

## Known validation boundary / blocker

Functional startup and retrieval cannot be proven in this task because Docker execution was explicitly prohibited. The `trueagi/das` image is distroless (`/bin/sh` is absent), and the repository provides no source-defined DAS health RPC or image-provided probe command. Shell-based checks were therefore removed instead of presenting container start as health. The README requires post-start log inspection, listener checks from already-approved containers on the private networks, and an end-to-end read-only retrieval before considering the POC operational.

No digest values are committed: operators must resolve and review immutable digests for the intended image releases and supply them locally. This is intentional fail-closed behavior, not an incomplete tag fallback.
