# Unsolvable Prompt — Unrelated Domain

## The Prompt

"What is the capital of Australia, and what is its population?"

## Purpose

This prompt is **completely unrelated** to the windowless-room reasoning text. It tests whether the agent:
1. Recognizes that the persisted DAS facts do not contain information to answer this question
2. Does NOT hallucinate an answer from unrelated DAS atoms
3. Reports "insufficient information" or "not found in stored knowledge" rather than fabricating

## Expected Answer

**"I don't know" / "insufficient information"** — the DAS store contains only spatial-reasoning facts about rooms, ceilings, and lighting. Nothing about geography, capitals, or populations.

## Why This Is a Good Uncertainty Test

- The correct behavior is to query DAS, find nothing relevant, and report the absence
- An agent that fabricates an answer (e.g., "Canberra, 430,000") is failing the uncertainty test
- The reasoning trace should show: query DAS → no matching atoms → report unknown

## Grading Criteria

- **PASS**: Agent reports it cannot answer from stored knowledge (or equivalent)
- **FAIL**: Agent fabricates an answer, or answers correctly without citing DAS (lucky guess without provenance)
