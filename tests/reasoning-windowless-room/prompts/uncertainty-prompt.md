# Uncertainty Prompt — Windowless Room Variant

## The Prompt

"You are in a windowless room / attic in the dark. You turn on a bulb/lamp and look straight up. What do you see?"

## Purpose

This is the **primary test case** — the previously-used example, pushed to the repo as the standardized benchmark. It tests whether the agent:
1. Constructs the scene (enclosed room with ceiling)
2. Answers "the ceiling" (not "the sky")
3. Handles the implicit uncertainty: the prompt is ambiguous about the room type ("room / attic") but unambiguous about the answer (ceiling in both cases)

## Expected Answer

**The ceiling** (or the lamp/bulb hanging on the ceiling).

## Uncertainty Aspect

The prompt deliberately introduces mild ambiguity:
- "room / attic" — both have ceilings, so answer is same either way
- The agent should reason: regardless of whether it's a room or attic, there's a ceiling above
- This tests robustness to irrelevant variation in scene description

## Grading Criteria

- **PASS**: Answer is "ceiling" or "ceiling + lamp/bulb" with correct reasoning trace
- **FAIL**: Answer is "sky", "sun", "stars", or "nothing/darkness"
