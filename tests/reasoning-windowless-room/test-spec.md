# Windowless Room Reasoning Test — Test Specification

## Overview

This specification defines the end-to-end windowless-room reasoning benchmark test. The test exercises the Omega agent's ability to reason about a 3D scene using DAS-persisted background knowledge, and audits the full provenance chain (Git archive + DAS atoms/links).

## Scope

- **In scope:** Test prompts, background knowledge, grading, provenance audit, cleanup
- **Out of scope:** LLM-based grading, LLM interaction for the test itself, subjective assessment

## Test Structure

The test consists of these phases:

1. **Ingest** — the reasoning text (this folder) is provided to Omega as input
2. **Extract** — Omega extracts predicates / meta-reasoning traces from the text
3. **Persist** — extracted predicates are archived into the Git repo AND written to DAS
4. **Query** — a few prompts are sent to Omega exercising its reasoning using the newly written DAS facts
5. **Audit** — the full provenance chain is verified: Git hashes correct, not hallucinated, source link and DAS artifact relation
6. **Cleanup** — flag to clean up test atoms after the test completes
7. **Report** — final JSON report for each test case capturing the full evidence of the reasoning test

## Test Cases

| # | Prompt file | Type | Grading |
|---|---|---|---|
| 1 | `original-prompt.md` | Primary (previously-used example) | Ceiling/lamp answer + reasoning trace |
| 2 | `uncertainty-prompt.md` | Uncertainty (previously-used example) | Recognizes ambiguity, answers ceiling |
| 3 | `unsolvable-unrelated-prompt.md` | Unsolvable (completely unrelated domain) | Reports insufficient information |
| 4 | `true-statement-prompt.md` | True statement (from DAS facts) | Answers true with reasoning trace |
| 5 | `false-statement-prompt.md` | False statement (from DAS facts) | Answers false with reasoning trace |
| 6 | `difficult-prompt.md` | Difficult (multi-step chained) | Answers sloped-ceiling with trace |
| 7 | `easy-prompt.md` | Easy (simple fact lookup) | Answers ceiling (single-hop) |

## Expected Input

- **Input:** `tests/reasoning-windowless-room/background/*.md` — reasoning text already generated and pushed to the repo (commit `ea8245d`)
- **Expected output:** For each test case: (a) answer, (b) DAS query trace, (c) provenance artifacts (Git hash + source link), ( standardized JSON report

## Test Specification: `tests/reasoning-windowless-room/test-spec.md`

## Description

This specification describes the end-to-end windowless-room reasoning benchmark test.

## Purpose

Standardized test for checking the end-to-end reasoning trace of an agent (Omega) with DAS-backed persistent knowledge, including full provenance tracking (Git hashes, source links, DAS artifacts) and a clean-up flag.

## Phases

### 1. Ingest
Input: `tests/reasoning-windowless-room/background/*.md` (reasoning text). The background knowledge files provide the knowledge base for the test.

### 2. Extract
Omega extracts predicates / meta-reasoning traces from the reasoning text.

### test-spec.md Content Schema

Each test case in the spec must have:
- `id` — unique test case identifier
- `prompt_file` — markdown file containing the prompt
- `type` — test case type (primary, uncertainty, unsolvable, true, false, easy, difficult)
- `expected_answer` — the expected answer
- `grading` — grading criteria (PASS/FAIL conditions)

## Background-Knowledge Files

- `background/spatial-knowledge.md`
- `background/lighting.md`
- `background/perspective.md`
- `background/failure-modes.md`
- `background/meta-reanning.md`
- `background/meta-reasoning.md`

## External Links

- Repo: https://github.com/ktfh-claw/low-cost-omega-setup
- Test folder: `tests/reasoning-windowless-room/`

## Contact

Maintained by the assistant (Vector) for Balazs. Questions about the spec belong in `test-spec.md`.
