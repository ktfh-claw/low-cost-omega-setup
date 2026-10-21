# Failure Modes — Common Reasoning Errors

## Pattern-Matching Errors

Early LLMs frequently fail on spatial reasoning prompts by pattern-matching surface-level associations instead of simulating the physical scene:

- "Look up" → "sky" (outdoor association)
- "Dark room" → "can't see anything" (ignoring the light source being turned on)
- "Attic" → "dusty storage space" (ignoring the windowless/enclosed aspect)

## Why These Failures Occur

These errors happen because:
1. **Surface-level pattern matching**: The model associates "look up" with "sky" without considering the indoor context
2. **Missing scene simulation**: The model doesn't mentally construct the 3D environment described in the prompt
3. **Ignoring physical constraints**: The model doesn't account for opaque surfaces (ceiling) blocking line of sight
4. **Context window limitations**: When relevant facts are not in the immediate context, the model defaults to common associations

## The Windowless Room Failure

For the specific prompt "You are in a windowless room / attic in the dark. You turn on a bulb/lamp and look straight up. What do you see?":

- **Correct answer**: The ceiling (or the lamp/bulb hanging from the ceiling)
- **Common failure**: Answering "the sky" (or "the sun/stars")

The failure occurs because:
- The model pattern-matches "look up" → "sky" without simulating the indoor environment
- It ignores that a room has a ceiling (an opaque surface above)
- It doesn't consider that the ceiling blocks the view of anything above it

## How to Avoid These Failures

To reason correctly about spatial scenarios:
1. **Construct the scene**: Mentally build the 3D environment from the description
2. **Track the observer's position**: Where is the observer relative to surfaces?
3. **Identify light sources**: What is illuminated? What is in shadow?
4. **Trace line of sight**: What does the observer's gaze direction intersect?
5. **Consider physical constraints**: Opaque surfaces block views; enclosed spaces have boundaries

## Summary of Failure Modes

- Pattern-matching "look up" → "sky" without indoor context
- Ignoring the ceiling as an opaque barrier
- Not simulating the physical scene
- Defaulting to outdoor associations when the scene is indoor
