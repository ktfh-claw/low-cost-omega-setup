# Perspective Knowledge — Visual Perspective, Line of Sight, and Looking Up

## Visual Perspective

Visual perspective is the position from which an observer sees a scene. When you look at a scene:
- Your eye position determines what is visible
- Your gaze direction determines which surfaces are in your line of sight
- Objects between you and your line of sight target can block the view

## Line of Sight

Line of sight is the straight path from the observer's eyes to the object or surface being viewed. When looking at a surface:
- The nearest surface along the gaze direction is what is visible
- Opaque surfaces block the view of anything behind them
- In a room, looking up means the ceiling is the first surface encountered

## Looking Up Indoors vs. Outdoors

**Outdoors:** When you look up outdoors (standing in an open field), you see the sky. There is no ceiling above you — only the atmosphere and space beyond.

**Indoors:** When you look up indoors, you see the ceiling. The ceiling is an opaque horizontal surface that separates the room from whatever is above it (another floor, attic space, or roof). You cannot see through the ceiling to the sky.

## The Windowless Room / Attic Scenario

The prompt: "You are in a windowless room / attic in the dark. You turn on a bulb/lamp and look straight up. What do you see?"

Breaking this down:
1. You are INSIDE a room (or attic) — this means walls, floor, and ceiling surround you
2. The room is windowless — no openings to the outside
3. It is dark — you cannot see anything initially
4. You turn on a bulb/lamp — an artificial light source is now active
5. You look straight up — your gaze is directed toward the ceiling

**What you see: the ceiling (and possibly the bulb/lamp hanging from it).**

You do NOT see the sky. The ceiling is between you and the sky. It is an opaque surface that blocks your view of anything above it.

## Why "Sky" is the Wrong Answer

Early LLMs frequently answered "the sky" (or "the sun/stars") for this prompt. This is a pattern-matching error:
- "Look up" → "sky" is a common association
- But the correct answer requires simulating the physical scene: being inside a room means there is a ceiling above you
- The ceiling is the surface you see when you look up indoors

## Summary of Perspective Facts

- Looking up indoors → you see the ceiling
- Looking up outdoors → you see the sky
- The ceiling is opaque — you cannot see through it
- A windowless room has no view of the outside
- The correct answer to "what do you see when you look up in a room" is "the ceiling"
