# Difficult Prompt — Multi-Step Spatial Reasoning

## The Prompt

"You are in a windowless attic with a sloped ceiling. It is completely dark. You turn on a lamp that is sitting on the floor. The lamp illuminates the room. Now you look straight up through the slope of the roof. What do you see, and why?"

## Purpose

Tests **multi-step chained reasoning** over the persisted DAS facts:

1. Attic → sloped ceiling (roof line) — from spatial-knowledge
2. Lamp on floor → light source at floor level — from lighting
3. Looking up through the slope → line of sight intersects the sloped ceiling — from perspective
4. Answer: the sloped ceiling / underside of the roof — illuminated by the lamp

## Expected Answer

**The sloped ceiling (underside of the roof)** — because the attic has a sloped ceiling following the roof line, and looking up means the line of sight intersects it.

## Why This Is Difficult

- Requires chaining: attic → sloped ceiling → looking up → sloped ceiling visible
- The lamp on the floor (not ceiling-mounted) is a distractor — some models reason "lamp on floor → light shines up → see the sky"
- Requires resolving "through the slope of the roof" as referring to the ceiling surface, not an opening
- Requires understanding that a windowless attic still has a ceiling

## Grading Criteria

- **PASS**: Agent answers "the sloped ceiling" (or equivalent) with reasoning trace citing DAS facts
- **FAIL**: Agent answers "the sky", "stars", "the roof exterior", or provides incorrect reasoning
