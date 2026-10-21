"""Canonical fact set for the windowless-room reasoning benchmark.

Defines CANONICAL_FACTS (the seed/oracle fact set), SOURCE_URLS (background
file -> raw.githubusercontent.com URL), and TEST_CASES (the 7 benchmark cases
with expected answers and grading keys). Derived from the 5 background files.
"""
from __future__ import annotations

SOURCE_URL_BASE = "https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/main/tests/reasoning-windowless-room/background"

# background file name -> raw URL
SOURCE_URLS: dict[str, str] = {
    "spatial-knowledge.md": f"{SOURCE_URL_BASE}/spatial-knowledge.md",
    "lighting.md": f"{SOURCE_URL_BASE}/lighting.md",
    "perspective.md": f"{SOURCE_URL_BASE}/perspective.md",
    "meta-reasoning.md": f"{SOURCE_URL_BASE}/meta-reasoning.md",
    "failure-modes.md": f"{SOURCE_URL_BASE}/failure-modes.md",
}

ALL_BACKGROUND_FILES: list[str] = [
    "spatial-knowledge.md",
    "lighting.md",
    "perspective.md",
    "meta-reasoning.md",
    "failure-modes.md",
]

CANONICAL_FACTS: list[dict] = [
    # --- room structure (spatial-knowledge.md) ---
    {"id": "F01", "metta": '(Inheritance (Concept "room") (Concept "enclosed-space"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "easy", "difficult", "true", "false"], "notes": "A room is an enclosed space within a building."},
    {"id": "F02", "metta": '(Evaluation (Predicate "has-part") (Concept "room") (Concept "wall"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "Walls are vertical surfaces that enclose a room."},
    {"id": "F03", "metta": '(Evaluation (Predicate "has-part") (Concept "room") (Concept "floor"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult"], "notes": "A room has a floor (the bottom surface)."},
    {"id": "F04", "metta": '(Evaluation (Predicate "has-part") (Concept "room") (Concept "ceiling"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "easy", "difficult", "true", "false"], "notes": "A room has a ceiling (the top surface)."},
    {"id": "F05", "metta": '(Inheritance (Concept "windowless-room") (Concept "room"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "A windowless room is a room that has no windows."},
    {"id": "F06", "metta": '(Evaluation (Predicate "has-no-openings") (Concept "windowless-room") (Concept "exterior"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "A windowless room has no openings to the exterior."},
    {"id": "F07", "metta": '(Inheritance (Concept "attic") (Concept "room"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "easy", "difficult", "true", "false"], "notes": "An attic is a kind of room (an enclosed space below the roof)."},
    {"id": "F08", "metta": '(Evaluation (Predicate "has-surface-property") (Concept "attic") (Concept "sloped-ceiling"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["difficult"], "notes": "Attics have sloped ceilings following the roof line."},
    {"id": "F09", "metta": '(Evaluation (Predicate "directly-below") (Concept "attic") (Concept "roof"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["difficult"], "notes": "An attic is a space directly below the roof."},
    # --- spatial relations / looking up (perspective.md) ---
    {"id": "F10", "metta": '(Inheritance (Concept "ceiling") (Concept "opaque-surface"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "The ceiling is opaque — you cannot see through it."},
    {"id": "F11", "metta": '(Evaluation (Predicate "blocks-view-of") (Concept "ceiling") (Concept "sky"))', "source_file": "perspective.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "The ceiling blocks the view of the sky from inside a room."},
    {"id": "F12", "metta": '(Evaluation (Predicate "visible-when-looking-up") (Concept "observer-inside-room") (Concept "ceiling"))', "source_file": "perspective.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "easy", "difficult", "true", "false"], "notes": "Looking up indoors, the observer sees the ceiling."},
    {"id": "F13", "metta": '(Evaluation (Predicate "visible-when-looking-up") (Concept "observer-outdoors") (Concept "sky"))', "source_file": "perspective.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "Looking up outdoors you see the sky (not the ceiling)."},
    {"id": "F14", "metta": '(Evaluation (Predicate "visible-when-looking-up") (Concept "observer-inside-windowless-room") (Concept "ceiling"))', "source_file": "meta-reasoning.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "easy", "difficult", "true", "false"], "notes": "In a windowless room looking up you see the ceiling (or lamp/bulb on it)."},
    # --- lighting (lighting.md) ---
    {"id": "F15", "metta": '(Evaluation (Predicate "has-no-openings") (Concept "windowless-room") (Concept "exterior-light"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "A windowless room admits no exterior light; windowless-room light is artificial."},
    {"id": "F16", "metta": '(Evaluation (Predicate "illuminates") (Concept "artificial-light-source") (Concept "room-interior"))', "source_file": "lighting.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "Turning on an artificial light source illuminates the room interior."},
    {"id": "F17", "metta": '(Evaluation (Predicate "makes-visible") (Concept "artificial-light-source") (Concept "room-surfaces"))', "source_file": "lighting.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "An active artificial light source makes the room's surfaces visible."},
    {"id": "F18", "metta": '(Evaluation (Predicate "has-no-openings") (Concept "windowless-room") (Concept "natural-light"))', "source_file": "lighting.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "A windowless room admits no natural light."},
    # --- meta-reasoning (meta-reasoning.md) ---
    {"id": "F19", "metta": '(Evaluation (Predicate "requires") (Concept "spatial-reasoning") (Concept "scene-simulation"))', "source_file": "meta-reasoning.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "Spatial reasoning requires scene simulation, not pattern-matching."},
    {"id": "F20", "metta": '(Evaluation (Predicate "context-dependent") (Concept "look-up") (Concept "indoor-outdoor"))', "source_file": "meta-reasoning.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "Look-up is context-dependent: indoors ceiling, outdoors sky."},
    {"id": "F21", "metta": '(Evaluation (Predicate "reasoning-step") (Concept "reasoning-trace") (Concept "scene-construction"))', "source_file": "meta-reasoning.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "Reasoning trace step: scene construction."},
    {"id": "F22", "metta": '(Evaluation (Predicate "reasoning-step") (Concept "reasoning-trace") (Concept "state-change"))', "source_file": "meta-reasoning.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "Reasoning trace step: state change."},
    {"id": "F23", "metta": '(Evaluation (Predicate "reasoning-step") (Concept "reasoning-trace") (Concept "visibility-query"))', "source_file": "meta-reasoning.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "Reasoning trace step: visibility query."},
    {"id": "F24", "metta": '(Evaluation (Predicate "reasoning-step") (Concept "reasoning-trace") (Concept "answer"))', "source_file": "meta-reasoning.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "Reasoning trace step: answer."},
    {"id": "F25", "metta": '(Evaluation (Predicate "propagates-through") (Concept "state-change") (Concept "scene"))', "source_file": "meta-reasoning.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "State changes propagate through the scene."},
    {"id": "F26", "metta": '(Evaluation (Predicate "nearest-surface-in-gaze") (Concept "observer") (Concept "opaque-surface"))', "source_file": "meta-reasoning.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "The nearest opaque surface in the gaze direction is what is visible."},
    # --- failure modes (failure-modes.md) ---
    {"id": "F27", "metta": '(Evaluation (Predicate "is-failure") (Concept "look-up-to-sky-association") (Concept "pattern-matching-failure"))', "source_file": "failure-modes.md", "stv": [0.9, 0.8], "requires": ["unsolvable"], "notes": "Look-up -> sky is a pattern-matching failure."},
    {"id": "F28", "metta": '(Evaluation (Predicate "failure-mode") (Concept "spatial-reasoning") (Concept "phrase-association-without-scene-simulation"))', "source_file": "failure-modes.md", "stv": [0.9, 0.8], "requires": ["unsolvable"], "notes": "Failure = phrase association without scene simulation."},
    # --- additional spatial relations (spatial-knowledge.md) ---
    {"id": "F29", "metta": '(Evaluation (Predicate "above") (Concept "ceiling") (Concept "observer-inside-room"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "easy", "difficult", "true", "false"], "notes": "The ceiling is above the observer inside a room."},
    {"id": "F30", "metta": '(Evaluation (Predicate "below") (Concept "floor") (Concept "observer-inside-room"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult"], "notes": "The floor is below the observer inside a room."},
    # --- additional lighting (lighting.md / spatial-knowledge.md) ---
    {"id": "F31", "metta": '(Evaluation (Predicate "lacks") (Concept "dark-room") (Concept "active-light-source"))', "source_file": "lighting.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "A dark room has no active light source."},
    {"id": "F32", "metta": '(Evaluation (Predicate "light-source-type") (Concept "windowless-room") (Concept "artificial"))', "source_file": "spatial-knowledge.md", "stv": [0.9, 0.8], "requires": ["original", "uncertainty", "difficult", "true", "false"], "notes": "Windowless-room light is artificial (only artificial sources available)."},
]

TEST_CASES: list[dict] = [
    {
        "id": "original",
        "prompt_file": "prompts/original-prompt.md",
        "expected_answer": "The ceiling (or the lamp/bulb hanging from the ceiling).",
        "grading": "PASS iff answer mentions ceiling (accept 'ceiling', 'the ceiling', ceiling + lamp/bulb) AND does not answer sky/sun/stars as the primary answer; reasoning trace present (>=1 quoted das-retrieve query + result summary).",
        "required_facts": ["F04", "F07", "F12", "F14", "F11", "F05"],
    },
    {
        "id": "uncertainty",
        "prompt_file": "prompts/uncertainty-prompt.md",
        "expected_answer": "The ceiling (or the lamp/bulb hanging on the ceiling).",
        "grading": "PASS iff answer is ceiling or ceiling + lamp/bulb with correct reasoning trace; FAIL if sky, sun, stars, or nothing/darkness.",
        "required_facts": ["F04", "F07", "F12", "F14", "F11", "F05"],
    },
    {
        "id": "unsolvable",
        "prompt_file": "prompts/unsolvable-unrelated-prompt.md",
        "expected_answer": "Reports inability to answer from stored knowledge (insufficient information / not found).",
        "grading": "PASS iff agent reports inability from stored knowledge AND does not state a specific capital/population answer (e.g. 'Canberra' -> FAIL).",
        "required_facts": ["F27", "F28"],
    },
    {
        "id": "true",
        "prompt_file": "prompts/true-statement-prompt.md",
        "expected_answer": "True — the ceiling is what you see when you look up in a room after turning on a light.",
        "grading": "PASS iff answer is true-affirming ('true', 'the statement is true') with reasoning trace.",
        "required_facts": ["F04", "F07", "F12", "F14", "F11", "F05"],
    },
    {
        "id": "false",
        "prompt_file": "prompts/false-statement-prompt.md",
        "expected_answer": "False — the ceiling is what you see when you look up in a room, not the sky.",
        "grading": "PASS iff answer is false-affirming ('false', 'the statement is false') with reasoning trace; answering 'true' -> FAIL.",
        "required_facts": ["F04", "F07", "F12", "F14", "F11", "F05"],
    },
    {
        "id": "easy",
        "prompt_file": "prompts/easy-prompt.md",
        "expected_answer": "The ceiling — directly answerable from the spatial-knowledge facts persisted in DAS.",
        "grading": "PASS iff agent answers 'the ceiling' (or equivalent) citing DAS facts; FAIL on anything else.",
        "required_facts": ["F04", "F12", "F14"],
    },
    {
        "id": "difficult",
        "prompt_file": "prompts/difficult-prompt.md",
        "expected_answer": "The sloped ceiling (underside of the roof) — illuminated by the lamp.",
        "grading": "PASS iff answer mentions sloped ceiling / underside of roof AND not sky/stars/exterior-of-roof; reasoning trace present.",
        "required_facts": ["F08", "F09", "F10", "F11", "F16", "F17"],
    },
]

def get_fact(fact_id: str) -> dict | None:
    """Return a fact dict (copy) by ID, or None."""
    for fact in CANONICAL_FACTS:
        if fact["id"] == fact_id:
            return dict(fact)
    return None

def facts_for_case(case_id: str) -> list[dict]:
    """Return facts required by a given test case id."""
    for case in TEST_CASES:
        if case["id"] == case_id:
            ids = set()
            for c in TEST_CASES:
                if c["id"] == case_id:
                    ids.update(c["required_facts"])
            return [get_fact(fid) for fid in sorted(ids) if get_fact(fid) is not None]
    return []
