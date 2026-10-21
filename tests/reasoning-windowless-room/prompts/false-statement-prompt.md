# False Statement Prompt — Windowless Room Variant

## The Prompt

"When you look up in a windowless room after turning on a light, you see the sky. True or false?"

## Purpose

Tests whether the agent can correctly identify a **false** statement based on the persisted DAS facts about rooms, ceilings, and lighting.

## Expected Answer

**False** — the ceiling is what you see when you look up in a room, not the sky.

## Reasoning Trace

1. The room is enclosed (walls, floor, ceiling)
2. The ceiling is above the observer, blocking the view of the sky
3. The light is turned on, illuminating the room
4. Looking up → line of sight intersects the ceiling
5. Therefore: the statement is FALSE

## Grading Criteria

- **PASS**: Agent answers "false" with correct reasoning trace citing DAS facts
- **FAIL**: Agent answers "true" or provides incorrect reasoning
