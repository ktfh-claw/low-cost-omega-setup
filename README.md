# Low-cost Omega setup

An experiment in running [Omega](https://github.com/singnet/Omega) as a continuously operating agent on privately controlled infrastructure using a free or very low-cost LLM route.

The concrete example campaign was an autonomous solver for the [ARC-AGI benchmark](https://github.com/fchollet/ARC-AGI). We built an [ARC-AGI REST API](https://github.com/ktfh-claw/ARC-AGI) so Omega could repeatedly:

1. wake without a new human message;
2. read an authorized ARC evaluation task;
3. infer and validate the transformation from the training examples;
4. submit a bounded answer through a capability-limited proxy; and
5. continue with later tasks until the campaign was stopped.

This repository is a field report, not a working deployment guide. The low-cost campaign was not reliable enough to publish as a reproducible setup. The useful result is a documented set of integration blockers, partial successes, and upstream dependencies.

## Intended architecture

```text
Omega on owned hardware
  ├─ scheduled autonomous wake loop
  ├─ OpenRouter provider
  │    ├─ openrouter/free router, or
  │    └─ an explicitly selected free model
  ├─ arc-read / arc-submit Omega skills
  └─ host-only capability proxy
         ├─ task-scoped authorization and expiry
         ├─ strict payload validation
         ├─ duplicate prevention and three-attempt limit
         └─ ARC-AGI REST API
```

The REST API was intentionally separated from Omega. Evaluation outputs remained server-side, the API token was never exposed to the agent, and malformed candidates were rejected before consuming an attempt.

## What was tried

### 1. Custom Omega deployment with Telegram

The first deployment used a custom Omega fork, Telegram as the communication channel, a custom OpenRouter-free adapter, local embeddings, persistent memory, and `arc-read` / `arc-submit` integrations.

Interactive tool use worked, but the campaign stopped after the human turn. A Telegram-specific guard intended to suppress unsolicited chat messages also suppressed wake-triggered inference. The container looked healthy and continued incrementing loop iterations while making no provider or ARC calls.

This was reported upstream as [singnet/Omega issue #365](https://github.com/singnet/Omega/issues/365). Subsequent investigation established that the original failure was substantially caused by the old/custom deployment and its loop changes, rather than proving that stock Omega could not wake autonomously.

### 2. Stock Omega v0.1.19 with `openrouter/free`

We redeployed the official `singularitynet/omega:v0.1.19` image without Telegram or core/provider/loop modifications. ARC tools and the durable campaign objective were loaded through Omega's plugin and prompt-extension mechanisms.

The default configured model, `z-ai/glm-5.2`, returned HTTP 402 because no paid OpenRouter credit was available. We therefore used Omega's supported `model=openrouter/free` override.

This test proved that stock Omega can perform scheduled background inference without inbound messages. It repeatedly made wake-driven provider calls and valid autonomous `arc-read` calls.

The blocker moved from scheduling to model/protocol reliability. `openrouter/free` routed requests to different free models, which produced inconsistent outputs:

- valid Omega line commands;
- empty or null content after spending the output budget on reasoning;
- prose or native-tool-call markup that stock Omega could not consume;
- malformed JSON for `arc-submit`; and
- repeated reads instead of acting on the previous tool result.

Strict local validation prevented malformed submissions from consuming ARC attempts.

### 3. Explicit free model

We also tested explicit free models to remove router variability. `stealth/space-bunny-alpha` was the strongest text-protocol candidate observed:

- it produced parser-compatible `arc-read` and `arc-submit` commands;
- Omega autonomously solved ARC task `009d5c81` correctly on the first attempt;
- it submitted a structurally valid but incorrect answer for `00dbd492`; and
- it later produced malformed, truncated, repeated, or incorrect candidates for another task.

This demonstrated the full end-to-end path, but not reliable continuous operation.

### 4. Prompt and feedback tightening

We tried a stricter textual command contract, durable startup objectives, high-recency “next required action” instructions, local candidate validation, and detailed validator feedback. These changes sometimes converted an invalid candidate into a structurally valid submission, but did not make behavior consistently correct or continuous.

### 5. Loop changes and configuration experiments

During diagnosis we tried or evaluated:

- allowing wake-triggered inference independently of a new Telegram message;
- initializing and resetting wake state such as `nextWakeAt` and the loop budget;
- recovering from a loop counter that could fall below zero and permanently fail a `> 0` guard;
- running headless with `commchannel=websocket` and no inbound endpoint; and
- numeric CLI overrides such as `maxFeedback=12000`.

The stock headless wake path worked in observed runs. Some modified/rebuilt loop deployments were fragile or entered tight no-inference loops because wake state was missing or the loop budget was not reset. Numeric command-line tuning also failed in the tested stock invocation with:

```text
Arithmetic: '12000'/0 is not a function
```

We reverted unstable changes rather than presenting them as a solution.

## Root technical limitation

Stock Omega v0.1.19 describes tools in the textual system prompt and asks the model to emit line commands. It consumes `message.content`; it does not send an OpenAI-compatible `tools` schema or consume `message.tool_calls`.

That creates avoidable failure modes: prose instead of commands, XML/tool markup, malformed embedded JSON, truncation, parser ambiguity, and loss of tool-call/result association between turns. A model being advertised as “tool capable” does not help if Omega does not use the native tool-call API.

Upstream [PR #358](https://github.com/singnet/Omega/pull/358), **“Use tools API to pass the list of tools to the LLM,”** is intended to address much of this integration problem. Omega maintainers referenced it directly in issue #365 and requested retesting after it is merged.

At the time of this report, both [issue #365](https://github.com/singnet/Omega/issues/365) and [PR #358](https://github.com/singnet/Omega/pull/358) were open. PR #358 should reduce transport and command-parsing failures, but it cannot guarantee ARC reasoning quality. Its then-current schema also represented every skill parameter as a string, so the nested ARC submission remained JSON encoded inside a string and still required strict downstream validation.

## Outcome

The experiment achieved several important partial results:

- deployed Omega on owned infrastructure;
- built and deployed a leak-resistant ARC-AGI evaluation API;
- proved stock Omega's scheduled wake mechanism can run without inbound messages;
- proved complete autonomous `arc-read` and `arc-submit` plumbing;
- obtained one correct autonomous ARC solution with an explicitly selected free model; and
- isolated native tool-call integration as a major reliability dependency.

It did **not** achieve the original goal of a dependable, continuously operating Omega campaign using only free LLM inference. The combination of variable free-router model behavior, textual tool-command parsing, occasional null/truncated output, model reasoning errors, and fragile experimental loop modifications prevented a repeatable deployment guide.

## Related repositories and upstream work

- Omega upstream: https://github.com/singnet/Omega
- Continuous-campaign discussion and findings: https://github.com/singnet/Omega/issues/365
- Native tools API work: https://github.com/singnet/Omega/pull/358
- ARC-AGI REST API implementation used by this experiment: https://github.com/ktfh-claw/ARC-AGI
- Original ARC-AGI repository and dataset: https://github.com/fchollet/ARC-AGI

## Detailed report

See [`artifacts/experiment-report.md`](artifacts/experiment-report.md) for the test matrix, observed failures, safety controls, and criteria for a future retest.
