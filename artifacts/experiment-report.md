# Experiment report

Date range: September 2026

Status: unsuccessful as a reproducible low-cost deployment; partially successful as an integration experiment

## Goal and success criteria

The project aimed to produce a practical guide for deploying Omega on a user's own server and running a genuinely continuous campaign with a free LLM provider.

ARC-AGI was chosen as the example campaign because it requires repeated, stateful work rather than a single chat response. A successful run needed to:

1. preserve a durable campaign objective;
2. wake on a schedule without a new message;
3. retrieve only the currently authorized ARC task;
4. reason over every training pair;
5. submit a validated answer within a bounded attempt budget; and
6. move to later authorized tasks without manual prompting.

A one-off correct response was not sufficient. Reliability across wake cycles and tool-result turns was the actual target.

## Components

### Omega

Experiments covered a custom fork and the official `singularitynet/omega:v0.1.19` image. Communication modes included Telegram and a headless websocket configuration.

### LLM routes

- stock OpenRouter provider with its default model;
- stock OpenRouter provider with `model=openrouter/free`;
- explicitly selected free models, especially `stealth/space-bunny-alpha`;
- direct probes of both textual command behavior and native OpenAI-compatible tool calls.

### ARC service

The experiment extended the public [ARC-AGI repository](https://github.com/ktfh-claw/ARC-AGI) with a FastAPI evaluation service. Its source dataset comes from the [original ARC-AGI repository](https://github.com/fchollet/ARC-AGI).

The service exposes training examples and evaluation test inputs while keeping evaluation outputs server-side. It validates submissions, limits each task to three attempts, persists state in SQLite, and returns correctness/status rather than hidden outputs.

The API implementation was independently validated with 21 tests in its initial report and later 29 tests after deployment-related work, plus Ruff, formatting, strict mypy, dependency, corpus, concurrency, and leak-resistance checks.

### Capability proxy and campaign controller

Omega did not receive the ARC bearer token. A host-side proxy allowed only fixed ARC operations and enforced:

- exact campaign and task authorization;
- authorization expiry;
- strict `{outputs, reasoning}` payload shape;
- rectangular 1–30 by 1–30 grids with integer cells 0–9;
- duplicate-candidate rejection;
- an atomic three-attempt budget; and
- fail-closed behavior when `/tasks/next` and the authorized task disagreed.

These controls prevented malformed model output and plumbing tests from wasting real attempts.

## Test matrix and results

| Experiment | Result | Finding |
|---|---|---|
| Custom Omega + Telegram + custom free-provider adapter | Failed to continue after interactive turn | Telegram-specific inference guard suppressed scheduled background work |
| Stock Omega v0.1.19 + default OpenRouter model | Failed with HTTP 402 | Default `z-ai/glm-5.2` required unavailable credit |
| Stock Omega v0.1.19 + `openrouter/free` | Wake/read partially succeeded; submissions unreliable | Stock wake scheduling works, but routed models emitted inconsistent command formats |
| Stock Omega + explicit `stealth/space-bunny-alpha` | End-to-end path succeeded intermittently | One ARC task solved correctly; later tasks were wrong, malformed, repeated, or truncated |
| Stronger prompt + validator feedback | Partial improvement | Could turn some malformed candidates into valid payloads, but not dependable behavior |
| Numeric runtime overrides | Failed in tested syntax | Example `maxFeedback=12000` produced `Arithmetic: '12000'/0 is not a function` |
| Native tool-call probe outside stock Omega path | Transport succeeded | OpenRouter returned valid native tool calls, but stock Omega v0.1.19 would discard that path |
| Review of upstream PR #358 | Promising, not a complete ARC fix | Replaces text-command emulation with native tools API; reasoning and nested JSON limitations remain |

## Detailed failure analysis

### A. Custom Telegram loop suppressed autonomy

The first custom deployment introduced a condition similar to:

```metta
(if (and (> (get-state &loops) 0)
         (or (!= (commchannel) telegram)
             (or $msgnew (get-state &telegramFollowup))))
    ...perform inference...
    ...wake handling...)
```

It was added to stop unsolicited Telegram replies. After the human message was consumed, neither `$msgnew` nor the follow-up state was true, so a scheduled wake did not admit inference. Logs showed tens of thousands of loop iterations with no new provider call or ARC action.

This became [upstream issue #365](https://github.com/singnet/Omega/issues/365). Later stock testing corrected the initial conclusion: autonomous wakes do work in an unmodified, no-Telegram setup. The original symptom was therefore not clean evidence of a stock Omega defect.

### B. Experimental wake-state changes were fragile

During later modified deployments, two closely related failure modes appeared:

- `nextWakeAt` was not initialized before the inference block that itself depended on waking;
- the loop budget could decrement below zero and a `> 0` guard would never reopen unless wake handling explicitly reset it.

Candidate fixes initialized the wake deadline and reset the loop budget when the timer fired. Some rebuilt runs resumed `arc-read`, but other deployments entered tight no-inference loops or exited, and the resulting state was not stable enough to recommend as a guide. The clean stock test remains the strongest evidence: stock scheduled wake behavior itself worked.

### C. `openrouter/free` is not a stable model

The free router can select different models per request. Observed routes had materially different protocol behavior. Across otherwise similar requests Omega received:

- parser-compatible bare commands;
- prose;
- XML-like or native-tool-call markup;
- null content after reasoning/token exhaustion;
- malformed or truncated JSON; and
- valid reads followed by repeated reads rather than a submit.

This variation made a continuous campaign non-deterministic.

### D. Stock Omega v0.1.19 used a text protocol for tools

Stock Omega rendered available skills into the prompt and expected text such as:

```text
arc-submit 05a7bcf2 {"outputs":[...],"reasoning":"..."}
```

It did not send a native `tools` schema and consumed `message.content`, not `message.tool_calls`. Therefore:

- a native-tool-capable model could return a correct structured call that appeared empty to Omega;
- JSON had to survive generation, embedding in text, and command parsing;
- argument boundaries and parentheses could be ambiguous;
- tool-call identity and the association with a later tool result were weak; and
- model/provider-specific syntax differences leaked into the agent loop.

### E. ARC reasoning remained a separate problem

Transport fixes do not imply task correctness. Explicit `stealth/space-bunny-alpha` testing produced:

- a correct autonomous first-attempt solution for `009d5c81`;
- a structurally valid but incorrect submission for `00dbd492`;
- locally rejected malformed/non-rectangular candidates for `05a7bcf2`; and
- later structurally valid but incorrect output after detailed validator feedback.

This proved the integration while also showing that free-model reasoning quality was insufficiently dependable.

## Upstream references

### Issue #365

[Guidance needed: continuous background campaigns do not resume with Telegram-specific idle guard](https://github.com/singnet/Omega/issues/365)

The issue records the original architecture, custom-loop caveat, stock-runtime follow-up, autonomous wake evidence, malformed free-router output, and maintainer guidance.

A maintainer noted that the custom fork was based on an older upstream commit and that modern Omega can select `model=openrouter/free` without a separate provider. Maintainers also reproduced incorrect tool use and recommended waiting for PR #358 before retesting.

### PR #358

[[OMEGA-427] Use tools API to pass the list of tools to the LLM](https://github.com/singnet/Omega/pull/358)

At the reviewed head, the PR:

- introduced structured request/response and tool-call objects;
- converted Omega skills to OpenAI-compatible `tools` entries;
- used `tool_choice: "required"`;
- marked function definitions strict and disallowed extra properties;
- consumed `message.tool_calls`;
- preserved assistant tool-call and tool-result messages across turns; and
- removed the old textual balancing/recovery path.

Expected improvement: fewer empty native-tool responses, less prose/XML command emulation, better argument boundaries, and preserved call/result identity.

Remaining limitations:

- it cannot improve ARC reasoning by itself;
- models may still return null output, choose the wrong tool, or fail strict-tool support;
- at the reviewed head, skill parameters were typed as strings, leaving the nested ARC body as JSON inside a string; and
- strict proxy-side authorization and validation remain necessary.

## Why this is not presented as a working guide

The campaign occasionally worked and once solved a task correctly, but a guide should be repeatable. The following remained unresolved at the end of the experiment:

1. free-router model identity and behavior were variable;
2. stock v0.1.19 depended on brittle textual tool commands;
3. explicit free models were not consistently available or correct;
4. prompt tightening improved individual turns, not sustained reliability;
5. custom wake-loop modifications introduced regressions; and
6. PR #358 was still open and had not become the stable upstream baseline.

Calling this a successful low-cost setup would therefore be misleading.

## Recommended future retest

After PR #358 or its successor lands in an official release:

1. deploy an unmodified official Omega image;
2. keep the ARC API and capability proxy unchanged;
3. first use a read-only/mock tool to verify native dispatch without consuming attempts;
4. capture evidence that requests contain `tools` and `tool_choice`;
5. verify responses use `message.tool_calls` and Omega dispatches them;
6. verify the next turn contains a matching `role=tool` result;
7. run multiple idle wake cycles with no human messages;
8. test `openrouter/free` and at least one pinned free model separately;
9. permit real `arc-submit` only after structural validation; and
10. require repeated tasks and wake cycles before calling the setup reliable.

## Bottom line

The experiment validated the infrastructure and demonstrated that Omega can wake and use ARC tools autonomously. It did not validate free LLM inference as a dependable engine for a continuous Omega campaign. The main engineering dependency is native tool-call integration; after that, model availability and reasoning quality remain independent constraints.
