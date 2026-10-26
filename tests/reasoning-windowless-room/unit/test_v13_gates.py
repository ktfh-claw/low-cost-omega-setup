"""v13 gate tests: A_SKY lexical-blocker negation (wr3l evidence).

2026-10-26 19:04 UTC directive prep ("run all the other cases"). Live
wr3l evidence (close-out 2026-10-26 15:58Z): the uncertainty case FAILED
on A_SKY only — a grader-side false positive. The honest answer
"...which blocks any view of the sky; indoors looking up shows the
ceiling, not the sky" was failed because "blocks" was missing from
_NEGATION_RE's lexicon (the FIRST "sky" mention scored unnegated; the
second negated correctly under the v10 "not" rule). Replicated the
grader on the answer text before fixing.

v13 keeps the gate STRICT: an UNNEGATED sky/sun/stars answer still
fails, and negation/blocking must still PRECEDE the keyword ("sky
visible but no windows" still fails; "you can see the sky because the
ceiling does not block it" still fails — the blocker phrase trails the
claim and cannot rescue it).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from grading import _mentions_unnegated, grade_answer


# ---------------------------------------------------------------------------
# v13: the wr3l honest answer no longer false-fails
# ---------------------------------------------------------------------------

def test_wr3l_honest_answer_passes():
    la = ("you see the ceiling of the windowless room — an opaque interior "
          "surface above you which blocks any view of the sky; indoors "
          "looking up shows the ceiling, not the sky, made visible by the "
          "light you turned on")
    for cid in ("original", "uncertainty", "easy"):
        assert grade_answer(cid, la) == [], (cid, grade_answer(cid, la))


def test_blocks_phrasing_difficult_passes():
    la = ("you see the sloped ceiling — the underside of the roof — "
          "illuminated by the lamp; the roof slope blocks the view of the "
          "sky, and the windowless attic has no opening to the outside")
    assert grade_answer("difficult", la) == [], grade_answer("difficult", la)


def test_lexical_blocker_direct():
    assert _mentions_unnegated(
        "the ceiling blocks any view of the sky", ("sky",)) is False
    assert _mentions_unnegated(
        "the ceiling hides the sky overhead", ("sky",)) is False
    assert _mentions_unnegated("you see the sky", ("sky",)) is True


# ---------------------------------------------------------------------------
# strictness regressions: unnegated claims still fail
# ---------------------------------------------------------------------------

def test_unnegated_sky_still_fails():
    assert grade_answer("original", "you see the sky") == ["A_SKY"]
    assert grade_answer("uncertainty", "the sun is what you see") == ["A_SKY"]
    assert grade_answer("easy", "the stars are above you") == ["A_SKY"]


def test_negation_after_keyword_still_fails():
    # v10 invariant preserved: the negation must PRECEDE the claim
    assert grade_answer("original", "the sky visible but no windows") == ["A_SKY"]


def test_trailing_blocker_cannot_rescue_claim():
    # "does not block" trails the claim — the sky mention is UNNEGATED
    assert grade_answer(
        "original",
        "you can see the sky because the ceiling does not block it") == ["A_SKY"]


def test_true_false_unsolvable_gates_unaffected():
    assert grade_answer("true", "the statement is true") == []
    assert grade_answer("false", "the statement is false") == []
    assert grade_answer(
        "unsolvable", "not found in stored knowledge; I don't know") == []
    assert grade_answer("unsolvable", "Canberra, population 430000") == ["A_FABRICATED"]
