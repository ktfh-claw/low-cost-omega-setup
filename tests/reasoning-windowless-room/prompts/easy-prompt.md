# Easy Prompt — Simple Fact Lookup

## The Prompt

"What surface is directly above you when you are inside a room?"

## Purpose

Tests whether the agent can answer a **simple fact lookup** from the persisted DAS facts. This is the easiest test case — a single-fact retrieval with no complex reasoning required.

## Expected Answer

**"The ceiling"** — directly answerable from the spatial-knowledge facts persisted in DAS.

## Why This Is Easy

- Single-hop reasoning: room → has ceiling → ceiling is above
- No state changes to track (no light turning on/off)
- No ambiguity in the prompt
- Directly answerable from a single fact in the background text

## Grading Criteria

- **PASS**: Agent answers "the ceiling" (or equivalent) citing DAS facts
- **FAIL**: Agent answers anything else, or cannot find the answer in DAS
