# Omega v0.1.20 uplift and validated deployment state

**Validation dates:** 2026-10-06–07 UTC
**Scope:** upstream Omega v0.1.20, open PR #358 native tools API, and the fork's ARC, read-only DAS, and nginx line.

## Upgrade result and provenance

Upstream v0.1.20 is commit `19e94bb336378eebb66e8e689d0d3ff0e1bf5f77`. PR #358 remained open and was not part of that release, so the fork branch was constructed in two merges:

1. `cff9212515a23afb1c423fbbb0d306e9380766cc` merged v0.1.20 with PR #358 head `c193ab39857944017e067b426779d66113649313`.
2. `3b0f2b4b167dbcbc03360f2efcec9671f6ed0f45` merged the fork's guarded ARC, opt-in read-only DAS, and nginx line onto the new layout.

VM testing found five initial defects, fixed in `0d61c8eff59dcfdbac7c358315e08d3c179b7c7a`: structured OpenAI exhausted-budget handling, the OpenRouterFree gateway route, stale OpenRouter prompt guidance, stale pre-tools-API tests, and Docker-dependent global test cleanup.

The subsequent Telegram campaign work produced this additional commit trail on `uplift-v0.1.20-pr358`:

1. `1808b943102c6f225c7be764339eb16d7920f04c` added the config-gated `telegramAutonomousWake` option.
2. `dd4e0a176f72deda72bb5f2b373eb3c93d902808` fixed a three-argument MeTTa `or` whose partial application caused backtracking at iteration 1.
3. `f38217fa6b34a277cd4c0e780d2340af85eb4f67` made the Telegram inference input path total, preventing a non-ground receive value from reaching Janus request construction.

The pushed and deployed source is `ktfh-claw/OmegaClaw-Core`, branch `uplift-v0.1.20-pr358`, at `f38217fa6b34a277cd4c0e780d2340af85eb4f67`.

The live host image was built from a git archive of the exact commit:

| Property | Validated value |
|---|---|
| Image | `omegaclaw:das-f38217f` |
| Image digest | `sha256:d9d157826beb152e0d4f5183ed69ac6acff30b65267a599db68bb6fe625efe2c` |
| Image size | Approximately 2.34 GB |
| Source branch | `ktfh-claw/OmegaClaw-Core:uplift-v0.1.20-pr358` |
| Source commit | `f38217fa6b34a277cd4c0e780d2340af85eb4f67` |

## Deployment configuration changes

OMEGA-468 changed the repository and memory layout. The persistent volume mount and runtime memory setting moved from `/PeTTa/repos/OmegaClaw-Core/memory` to `/PeTTa/repos/Omega/memory`. The existing campaign volume was retained; its `history.metta` was 945,371 bytes at cutover.

The live launcher and environment now use:

- `commchannel=telegram`
- `provider=ASIOne model=asi1-ultra embeddingprovider=Local`
- bare argument `telegramAutonomousWake`, enabling scheduled inference on Telegram while retaining history continuity
- `MEMORY_DIR=/PeTTa/repos/Omega/memory`
- `OMEGA_DAS_ENABLED=1`, with the internal read-proxy origin retained
- Docker networks `bridge` and `omega-das-integration-client`

There is no `asi1-ultra` to `asi1` downgrade patch in this build. The provider default and explicit launch model are both `asi1-ultra`.

`telegramAutonomousWake` defaults to off, preserving upstream Telegram's interactive, message-driven behavior. In campaign mode it is enabled explicitly. Configuration environment lookup is case-sensitive and uses `OMEGA_` plus the exact key, so the environment spelling would be `OMEGA_telegramAutonomousWake`; the conventional-looking `OMEGA_TELEGRAM_AUTONOMOUS_WAKE` does **not** work. The live launcher therefore uses the bare `telegramAutonomousWake` command-line argument, which resolves to boolean true.

### Reproduce the validated build

The deployed image was built from an archive of the exact source commit. A fresh checkout can reconstruct the same source and image configuration, although dependency indexes and tag-selected base/dependency images mean that a later rebuild is not guaranteed to have the same byte-for-byte image digest:

```bash
git clone https://github.com/ktfh-claw/OmegaClaw-Core.git
cd OmegaClaw-Core
git checkout f38217fa6b34a277cd4c0e780d2340af85eb4f67
test "$(git rev-parse HEAD)" = "f38217fa6b34a277cd4c0e780d2340af85eb4f67"
docker build --tag omegaclaw:das-f38217f .
docker image inspect --format '{{.Id}}' omegaclaw:das-f38217f
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

The following minimal launch template applies the evidence-backed deployment settings. The named volume is mounted directly at the post-OMEGA-468 memory directory. Docker creates the container on the default `bridge`; the second network attachment adds only the internal DAS client route. Add host-specific hardening and service supervision separately.

```bash
docker create --rm --name omega-curiosity -t \
  --volume omega-curiosity-memory:/PeTTa/repos/Omega/memory \
  --env-file "$(pwd)/runtime.env" \
  omegaclaw:das-f38217f \
  commchannel=telegram provider=ASIOne model=asi1-ultra embeddingprovider=Local \
  telegramAutonomousWake

docker network connect omega-das-integration-client omega-curiosity
docker start --attach omega-curiosity
```

The DAS compose deployment must create `omega-das-integration-client` first. Do not attach Omega to the DAS backend network, publish DAS data-plane ports, or add a DAS write credential to `runtime.env`.

## Phase A test evidence

The mandatory offline lane on a disposable Ubuntu 24.04 VM ran against the exact final commit and reported **132 passed, 0 failed, 0 skipped**. A broader lane including import-knowledge shell tests reported **140 passed, 0 failed, 2 environment-gated skips** in 26.68 seconds.

The skips were for an optional multi-gigabyte import-knowledge ML/CUDA dependency and a launcher test requiring Docker plus a configured image. Docker-backed integration tests, live network/API tests, and model-backed embedding tests were not represented as locally run. Python compilation, shell syntax, `git diff --check`, repository cleanliness, and the final secret-pattern scan all passed.

## Initial live runtime validation

The initial `0d61c8e` service started at 21:59:55 UTC on 2026-10-06. This matrix records the Phase C baseline that the later wake-enabled images retained; it is not the current image provenance:

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

## Telegram autonomous-wake feature and production fixes

Upstream v0.1.20 plus PR #358 treats Telegram as interactive: its inference gate admits a new message or a structured-tool follow-up, but not an expired scheduled wake, and history is omitted outside those admitted turns. The fork's default-off `telegramAutonomousWake` option arms a scheduled Telegram turn and includes history so an explicitly configured campaign can continue autonomous research without a new inbound message.

Production monitoring caught two distinct regressions while the feature moved toward acceptance:

1. The first patch used a three-argument MeTTa `or`. PeTTa's `or` is binary, so this reduced to a partial application, repeatedly backtracked into iteration 1, consumed a CPU core, and never inferred. Commit `dd4e0a1` replaced it with a runtime-tested nested-binary gate. The VM reproduced the spin and then demonstrated two clean timed Test-provider wakes.
2. The corrected gate exposed a latent non-ground input path: the real Telegram `receive()` boundary could produce an exception or non-string value, while false/no-message request bindings could remain partial. Both production wakes on `dd4e0a1` crashed before any provider request with `janus:py_call/3: Arguments are not sufficiently instantiated`. Commit `f38217f` catches/normalizes channel results, uses a private ground no-input sentinel and concrete Python boolean comparison, and explicitly sequences request construction. A VM reproduced the fatal signature, then ran glitchy and clean wake probes without instantiation errors or process death; a default-off run made zero provider calls.

After deploying `das-f38217f`, production wake #1 at 02:19:01 UTC on 2026-10-07 reached ASI:One `asi1-ultra`, returned HTTP 200 with `finish_reason=tool_calls`, and did not crash—the exact point where the previous image failed on both attempts. Wake #2 at 02:29:03 was also clean. At the time this document was written, **two of the required three clean production wakes were verified; wake #3 was due at approximately 02:39 UTC and remained pending verification.**

## Current campaign

`omega-curiosity.service` runs the wake-enabled image with its mission in the `omega-curiosity-memory` volume's `prompt.txt`: research actual Fetch.ai use cases and what has already been built, then continue open-ended decentralized-AI research using papers on arXiv and posts on Substack. This is an autonomous research campaign, not the earlier ARC mission.

## ASI:One subscription history

Earlier on 2026-10-06, `asi1-ultra` returned an account-side 429 with a zero quota. Activating the subscription resolved that episode: a pre-uplift probe returned HTTP 200, and the uplifted deployment reconfirmed an HTTP 200 plus `[LLM_USAGE] model=asi1-ultra`. This is historical context, not the current state; the deployment did not require a model downgrade.

## Known issues and follow-ups

- Startup warns that one plugin instructions directory does not exist. Other workflow plugins loaded, and this did not block the validated loop.
- Startup warns that OpenClaw integration is enabled without an `openClawURL`. The integration is unused in this deployment.
- The first request after the fresh start had an empty history tail; later episodes populate it.
- The prior relative `omega_state.md` write could fail under the unprivileged runtime. The new system prompt advertises the Omega memory directory, but monitoring still needs to confirm that state updates land there. This remains a follow-up, not a validated fix.

These warnings and follow-ups do not change the all-green Phase C checks above, but the state write path should not be claimed as validated until observed.
