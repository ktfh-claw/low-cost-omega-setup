# True Statement Prompt — Windowless Room Variant

## The Prompt

"When you look up in a windowless room after turning on a light, you see the ceiling. True or false?"

## Purpose

Tests whether the agent can correctly identify a **true** statement based on the persisted DAS facts about rooms, ceilings, and lighting.

## Expected Answer

**True** — the ceiling is the surface directly above the observer in a room, and turning on a light makes it visible.

## Reasoning Trace

1. The room is enclosed (walls, floor, ceiling)
2. The ceiling is above the observer
3. The light is turned on, illuminating the room
4. Looking up → line of sight intersects the ceiling
5. Therefore: the statement is TRUE

## Grading Criteria

- **PASS**: Agent answers "true" with correct reasoning trace citing DAS facts
- **FAIL**: Agent answers "false" or provides incorrect reasoning
