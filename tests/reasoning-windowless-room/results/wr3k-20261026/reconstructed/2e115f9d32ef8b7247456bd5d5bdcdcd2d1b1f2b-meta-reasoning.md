# Meta-Reasoning — Facts About Reasoning in 3D Worlds

## Reasoning About 3D Spaces

Reasoning about physical spaces requires more than recalling facts — it requires constructing an internal model of the scene and tracing consequences through it. Key meta-facts:

1. **A room is an enclosed volume**, bounded by six surface types: walls (vertical), floor (bottom), ceiling (top). Any "room" mention implies these surfaces exist.
2. **Interior vs. exterior is the fundamental divide**: being inside a room changes what "looking up" means. Indoors, the first opaque surface above you is the ceiling.
3. **Opaque surfaces block line of sight**: you cannot see through walls, floors, or ceilings. Visibility requires either an opening (window, hatch) or the surface being absent.
4. **Light enables visibility**: in darkness, nothing is visible; turning on a light illuminates the room's interior surfaces, making them visible.
5. **State changes propagate through the scene**: when a condition changes (light turns on), the consequences affect the whole scene (room becomes illuminated).

## The Simulation Requirement

Correct spatial reasoning requires simulating the scene, not pattern-matching phrases:

- "Look up" indoors → ceiling (not sky)
- "Look up" outdoors → sky
- The same phrase produces different answers depending on context (indoor vs. outdoor)

A reasoning agent must:
1. Parse the scene description (entities, surfaces, positions)
2. Place the observer within the scene
3. Trace the consequences of actions (turning on light, looking up)
4. Query the simulated scene for the answer

## Decomposition of the Windowless Room Prompt

"You are in a windowless room / attic in the dark. You turn on a bulb/lamp and look straight up. What do you see?"

Scene entities:
- Room (or attic) — enclosed space with walls, floor, ceiling
- Windowless — no openings to the exterior
- Dark — no active light sources initially
- Bulb/lamp — artificial light source
- Observer — inside the room

State changes:
1. Initial state: dark room, no visibility
2. Action: turn on bulb/lamp
3. Resulting state: illuminated room
4. Action: look straight up
5. Query: what is visible above the observer?

Answer derivation:
- Observer is inside a room → there is a ceiling above
- Room is enclosed → ceiling blocks view of anything above it
- Light is on → room interior is illuminated
- Looking up → line of sight intersects the ceiling
- **Answer: the ceiling (or the bulb/lamp hanging from it)**

## Meta-Facts for the Reasoning Agent

- "In a room" implies walls, floor, ceiling exist and bound the space
- "Windowless" implies no visibility of the exterior
- "Look up" indoors → ceiling, not sky
- "Look up" outdoors → sky
- Turning on a light in a dark room illuminates the interior
- The nearest opaque surface in the gaze direction is what is visible
- A reasoning trace must show: scene construction → state change → visibility query → answer

## Summary

- Spatial reasoning requires scene simulation, not phrase association
- The windowless-room prompt tests whether an agent constructs the scene (enclosed space, ceiling above) or pattern-matches (look up → sky)
- The correct reasoning trace shows: room → enclosed → ceiling above → light on → looking up → ceiling is visible
