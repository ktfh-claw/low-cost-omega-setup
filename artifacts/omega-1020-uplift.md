# Omega v0.1.20 uplift and validated deployment state

**Validation date:** 2026-10-06 UTC
**Scope:** upstream Omega v0.1.20, open PR #358 native tools API, and the fork's ARC, read-only DAS, and nginx line.

## Upgrade result and provenance

Upstream v0.1.20 is commit `19e94bb336378eebb66e8e689d0d3ff0e1bf5f77`. PR #358 remained open and was not part of that release, so the fork branch was constructed in two merges:

1. `cff9212515a23afb1c423fbbb0d306e9380766cc` merged v0.1.20 with PR #358 head `c193ab39857944017e067b426779d66113649313`.
2. `3b0f2b4b167dbcbc03360f2efcec9671f6ed0f45` merged the fork's guarded ARC, opt-in read-only DAS, and nginx line onto the new layout.

VM testing found five defects, fixed in `0d61c8eff59dcfdbac7c358315e08d3c179b7c7a`: structured OpenAI exhausted-budget handling, the OpenRouterFree gateway route, stale OpenRouter prompt guidance, stale pre-tools-API tests, and Docker-dependent global test cleanup. The pushed source is `ktfh-claw/OmegaClaw-Core`, branch `uplift-v0.1.20-pr358`, at that commit.

The live host image was built from a git archive of the exact commit:

| Property | Validated value |
|---|---|
| Image | `omegaclaw:das-0d61c8e` |
| Image digest | `sha256:f29ccb27a7a07b2d29affea327d43105bd89ec1ec399fbf349af75d5c26bd272` |
| Image size | 2.34 GB |
| Source branch | `ktfh-claw/OmegaClaw-Core:uplift-v0.1.20-pr358` |
| Source commit | `0d61c8eff59dcfdbac7c358315e08d3c179b7c7a` |

## Deployment configuration changes

OMEGA-468 changed the repository and memory layout. The persistent volume mount and runtime memory setting moved from `/PeTTa/repos/OmegaClaw-Core/memory` to `/PeTTa/repos/Omega/memory`. The existing campaign volume was retained; its `history.metta` was 945,371 bytes at cutover.

The live launcher and environment now use:

- `commchannel=telegram`
- `provider=ASIOne model=asi1-ultra embeddingprovider=Local`
- `MEMORY_DIR=/PeTTa/repos/Omega/memory`
- `OMEGA_DAS_ENABLED=1`, with the internal read-proxy origin retained
- Docker networks `bridge` and `omega-das-integration-client`

There is no `asi1-ultra` to `asi1` downgrade patch in this build. The provider default and explicit launch model are both `asi1-ultra`.

### Reproduce the validated build

The deployed image was built from an archive of the exact source commit. A fresh checkout can reconstruct the same source and image configuration, although dependency indexes and tag-selected base/dependency images mean that a later rebuild is not guaranteed to have the same byte-for-byte image digest:

```bash
git clone https://github.com/ktfh-claw/OmegaClaw-Core.git
cd OmegaClaw-Core
git checkout 0d61c8eff59dcfdbac7c358315e08d3c179b7c7a
test "$(git rev-parse HEAD)" = "0d61c8eff59dcfdbac7c358315e08d3c179b7c7a"
docker build --tag omegaclaw:das-0d61c8e .
docker image inspect --format '{{.Id}}' omegaclaw:das-0d61c8e
```

The validated live image ID is the digest in the provenance table above. Treat a different ID from a later rebuild as a new artifact that requires validation, not as evidence that the checkout is wrong.

### Reproduce the validated launch shape

Store `runtime.env` with mode `0600`. Use real values only on the deployment host; the placeholders below are not credentials:

```dotenv
ASIONE_API_KEY=<provider-secret>
TG_BOT_TOKEN=<telegram-bot-secret>
OMEGA_AUTH_SECRET=<one-time-owner-auth-secret>
IMPORT_KB_ON_START=0
MEMORY_DIR=/PeTTa/repos/Omega/memory
OMEGA_DAS_ENABLED=1
OMEGA_DAS_PROXY_ORIGIN=http://read-proxy:8080
```

The validated service launcher is equivalent to the following sanitized command sequence. The named volume is mounted directly at the post-OMEGA-468 memory directory. Docker creates the container on the default `bridge`; the second network attachment adds only the internal DAS client route.

```bash
docker create --rm --name omega-curiosity -t \
  --security-opt no-new-privileges:true --init \
  --tmpfs /tmp:size=256m,mode=1777 \
  --tmpfs /var/tmp:size=64m,mode=1777 \
  --tmpfs /run:size=16m,mode=755 \
  --volume omega-curiosity-memory:/PeTTa/repos/Omega/memory \
  --env-file "$(pwd)/runtime.env" \
  omegaclaw:das-0d61c8e \
  commchannel=telegram provider=ASIOne model=asi1-ultra embeddingprovider=Local

docker network connect omega-das-integration-client omega-curiosity
docker start --attach omega-curiosity
```

The DAS compose deployment must create `omega-das-integration-client` first. Do not attach Omega to the DAS backend network, publish DAS data-plane ports, or add a DAS write credential to `runtime.env`.

## Phase A test evidence

The mandatory offline lane on a disposable Ubuntu 24.04 VM ran against the exact final commit and reported **132 passed, 0 failed, 0 skipped**. A broader lane including import-knowledge shell tests reported **140 passed, 0 failed, 2 environment-gated skips** in 26.68 seconds.

The skips were for an optional multi-gigabyte import-knowledge ML/CUDA dependency and a launcher test requiring Docker plus a configured image. Docker-backed integration tests, live network/API tests, and model-backed embedding tests were not represented as locally run. Python compilation, shell syntax, `git diff --check`, repository cleanliness, and the final secret-pattern scan all passed.

## Live runtime validation

The service started at 21:59:55 UTC. Validation produced the following results:

| Check | Result |
|---|---|
| Service/container | `active`, `NRestarts=0`; container up on `omegaclaw:das-0d61c8e`; inspected digest matched the build |
| Networks | Attached to `bridge` and `omega-das-integration-client` |
| ASI:One | `POST /asione/chat/completions` returned 200; `[LLM_USAGE]` recorded `provider=ASIOne model=asi1-ultra finish_reason=tool_calls` |
| PR #358 tools API | Request included 21 structured tools; response contained structured `LLMToolCall` objects rather than plaintext command parsing |
| DAS read | `das_skills.is_enabled` passed; `das-retrieve` registered and appeared in the tool list |
| ARC | Guarded `arc-read` and `arc-submit` tools registered |
| Telegram | Continuous polling returned 200; a live inbound message was processed and two outbound sends returned 200 |
| Memory | Runtime resolved `./repos/Omega/memory`; workflow memory was created below it; the mounted history remained present |
| Loop | Nine response/usage lines appeared during the first approximately three minutes |

## ASI:One subscription history

Earlier on 2026-10-06, `asi1-ultra` returned an account-side 429 with a zero quota. Activating the subscription resolved that episode: a pre-uplift probe returned HTTP 200, and the uplifted deployment reconfirmed an HTTP 200 plus `[LLM_USAGE] model=asi1-ultra`. This is historical context, not the current state; the deployment did not require a model downgrade.

## Known issues and follow-ups

- Startup warns that one plugin instructions directory does not exist. Other workflow plugins loaded, and this did not block the validated loop.
- Startup warns that OpenClaw integration is enabled without an `openClawURL`. The integration is unused in this deployment.
- The first request after the fresh start had an empty history tail; later episodes populate it.
- The prior relative `omega_state.md` write could fail under the unprivileged runtime. The new system prompt advertises the Omega memory directory, but monitoring still needs to confirm that state updates land there. This remains a follow-up, not a validated fix.

These warnings and follow-ups do not change the all-green Phase C checks above, but the state write path should not be claimed as validated until observed.
