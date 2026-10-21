# Windowless Room Reasoning Test

## Purpose

Standardized test for checking the end-to-end reasoning trace of an agent (Omega) with DAS-backed persistent knowledge. The test uses the classic "windowless room" prompt:

> "You are in a windowless room / attic in the dark. You turn on a bulb/lamp and look straight up. What do you see?"

**Expected correct answer:** The ceiling (or the lamp/bulb hanging from the ceiling).

**Common early-LLM failure:** Answering "the sky" (or "the sun/stars") — pattern-matching "look up" → "sky" without simulating the physical scene.

## Test Structure

This folder contains background knowledge files that describe the environment and reasoning domain. The agent should:

1. **Extract predicates** from these markdown files into MeTTa expressions
2. **Persist them** into DAS via the write-bridge
3. **Ask the original prompt** and reason about it using the persisted knowledge
4. **Record the answer** and reconstruct the exact reasoning trace

## Files

- `background/spatial-knowledge.md` — Basic spatial concepts: rooms, walls, ceilings, floors
- `background/lighting.md` — Light sources, darkness, illumination
- `background/perspective.md` — Visual perspective, line of sight, looking up/down
- `background/failure-modes.md` — Common reasoning failure modes and why they occur
- `background/meta-reasoning.md` — Meta-facts about reasoning in 3D worlds
- `prompts/original-prompt.md` — The original test prompt
- `prompts/expected-answer.md` — Expected answer and reasoning trace
- `results/` — Will contain test results and reasoning traces

## Success Criteria

- Agent extracts correct predicates from background knowledge
- Predicates are persisted into DAS (verified via write-bridge)
- Agent answers the original prompt correctly (ceiling/lamp)
- Reasoning trace is reconstructable from DAS queries + agent's chain-of-thought
- No fabricated facts or reasoning steps

## Provenance

- Generated: 2026-10-21
- Test type: standardized reasoning test
- Target: Omega agent with DAS persistent knowledge
- Reference: windowless-room prompt (classic LLM failure case)
