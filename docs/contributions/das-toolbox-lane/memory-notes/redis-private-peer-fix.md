# Redis private-peer startup fix evidence

Date: 2026-10-03 UTC

Repository: `/home/claw/.openclaw/workspace/repos/das-toolbox`

Branch: `omega-das-integration`

## Failure and fix

Redis was bound to `0.0.0.0` for the private Docker backend network but started with `--protected-mode yes` and no password. Its loopback health check passed while Redis returned a protected-mode error to the Query Engine's non-loopback container connection.

The deployment now sets `--protected-mode no`. This is intentionally bounded by the existing Compose isolation: Redis has no `ports`, `expose`, or host networking, attaches only to the internal `backend` network, and is not reachable from the separate `client` network. Query Engine is the intended Redis peer. Append-only persistence and the named durable volume remain unchanged.

## Regression coverage

Added `deploy/omega-das-integration/tests/test-compose-policy.py`, which asserts:

- Redis binds for container peers and has protected mode disabled.
- Append-only persistence remains enabled.
- Redis has no published/exposed port or host network and attaches only to `backend`.
- `backend` remains internal and Query Engine remains attached to it.
- The named Redis volume remains mounted at `/data` and declared.

README safety guidance now explains why protected mode is disabled, what network boundary replaces it, and that untrusted containers must not be attached to `backend`.

## Local validation

The following Docker-free checks passed:

- `python3 deploy/omega-das-integration/tests/test-compose-policy.py`
- `deploy/omega-das-integration/tests/test-render-config-permissions.sh`
- `sh -n deploy/omega-das-integration/scripts/*.sh`
- `python3 -m json.tool deploy/omega-das-integration/config/config.json.template`
- `git diff --check`

No Docker command was run. No commit or push was made.
