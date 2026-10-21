# Original Prompt — The Windowless Room Test

## The Prompt

"You are in a windowless room / attic in the dark. You turn on a bulb/lamp and look straight up. What do you see?"

## Prompt Setup

The standard human answer: **The ceiling (or the lamp/bulb hanging on the ceiling).**

The early-LLM failure: Models frequently answered **"the sky"** (or "the sun/stars") — pattern-matching "look up" → "sky" without simulating the physical scene.

## Why This Prompt Is a Good Standardized Test

1. It requires **scene simulation**, not just recall: the agent must construct the room (walls, floor, ceiling) and place the observer inside it.
2. It has a **clear correct answer** (ceiling/lamp) that is derivable from the background knowledge.
3. It has a **clear failure mode** (answering "sky") that is easy to detect automatically.
4. The reasoning trace is **reconstructable**: scene → enclosed → ceiling above → light on → looking up → ceiling visible.

## Usage

This prompt is used as a standardized benchmark test for checking the end-to-end reasoning and provenance tracking of an agent with DAS-backed persistent knowledge:

1. Ingest the background knowledge files (this folder) as reasoning text.
2. Extract predicates/meta-facts into MeTTa expressions.
3. Persist them to DAS via the write-bridge.
4. Ask this prompt and reason about it using the newly written DAS facts.
5. Reconstruct the exact reasoning trace.
