"""Unit tests for grading.py — answer grading + verification logic."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from grading import extract_final_answer, grade_case, verify_trace, GradeResult, TraceVerification
from facts import TEST_CASES


def _case(case_id):
    for c in TEST_CASES:
        if c["id"] == case_id:
            return c
    return None


def test_extract_final_answer_found():
    text = "Some prose\nFINAL ANSWER (original): the ceiling\nmore text"
    assert extract_final_answer(text, "original") == "the ceiling"


def test_extract_final_answer_missing():
    text = "Some prose without the answer line."
    assert extract_final_answer(text, "original") == ""


def test_extract_final_answer_case_mismatch():
    text = "FINAL ANSWER (uncertainty): the ceiling"
    assert extract_final_answer(text, "original") == ""


def test_grade_case_original_pass():
    case = _case("original")
    text = "FINAL ANSWER (original): the ceiling"
    result = grade_case(case, text, [{"query": "(Inheritance $X $Y)", "count": 1}])
    assert result.verdict == "PASS"


def test_grade_case_original_sky_fail():
    case = _case("original")
    text = "FINAL ANSWER (original): the sky"
    result = grade_case(case, text, [{"query": "(Inheritance $X $Y)", "count": 1}])
    assert result.verdict == "FAIL"


def test_grade_case_original_missing_final_answer():
    case = _case("original")
    text = "Some prose without the answer line."
    result = grade_case(case, text, [])
    assert result.verdict == "FAIL"


def test_grade_case_difficult_pass():
    case = _case("difficult")
    text = "FINAL ANSWER (difficult): the sloped ceiling (underside of the roof)"
    result = grade_case(case, text, [{"query": "(Inheritance $X $Y)", "count": 1}])
    assert result.verdict == "PASS"


def test_grade_case_difficult_sky_fail():
    case = _case("difficult")
    text = "FINAL ANSWER (difficult): the sky"
    result = grade_case(case, text, [{"query": "(Inheritance $X $Y)", "count": 1}])
    assert result.verdict == "FAIL"


def test_grade_case_true_pass():
    case = _case("true")
    text = "FINAL ANSWER (true): true"
    result = grade_case(case, text, [{"query": "(Inheritance $X $Y)", "count": 1}])
    assert result.verdict == "PASS"


def test_grade_case_false_pass():
    case = _case("false")
    text = "FINAL ANSWER (false): false"
    result = grade_case(case, text, [{"query": "(Inheritance $X $Y)", "count": 1}])
    assert result.verdict == "PASS"


def test_grade_case_unsolvable_pass():
    case = _case("unsolvable")
    text = "FINAL ANSWER (unsolvable): I don't know — insufficient information in stored knowledge."
    result = grade_case(case, text, [])
    assert result.verdict == "PASS"


def test_grade_case_unsolvable_canberra_fail():
    case = _case("unsolvable")
    text = "FINAL ANSWER (unsolvable): Canberra"
    result = grade_case(case, text, [])
    assert result.verdict == "FAIL"


def test_verify_trace_all_ok():
    das_queries = [{"query": "(Inheritance $X $Y)", "count": 1, "results": ["a"]}]
    reissue = {"(Inheritance $X $Y)": {"count": 1, "results": ["a"]}}
    citations = ["abc123"]
    audit = {"abc123": True}
    result = verify_trace(das_queries, reissue, citations, audit)
    assert result.trace_ok is True


def test_grade_case_false_answering_true_fails():
    """The task says: answering 'true' -> FAIL for the false case."""
    case = _case("false")
    text = "FINAL ANSWER (false): true"
    result = grade_case(case, text, [{"query": "(Inheritance $X $Y)", "count": 1}])
    assert result.verdict == "FAIL"


def test_grade_case_true_no_trace_fails():
    """True case without trace should FAIL."""
    case = _case("true")
    text = "FINAL ANSWER (true): true"
    result = grade_case(case, text, [])
    assert result.verdict == "FAIL"


def test_grade_case_unsolvable_insufficient_pass():
    case = _case("unsolvable")
    text = "FINAL ANSWER (unsolvable): insufficient information — not found in stored knowledge"
    result = grade_case(case, text, [])
    assert result.verdict == "PASS"


def test_grade_case_unsolvable_unknown_pass():
    case = _case("unsolvable")
    text = "FINAL ANSWER (unsolvable): unknown — cannot answer from stored knowledge"
    result = grade_case(case, text, [])
    assert result.verdict == "PASS"


def test_grade_case_unsolvable_no_keywords_fail():
    case = _case("unsolvable")
    text = "FINAL ANSWER (unsolvable): The answer is definitely something."
    result = grade_case(case, text, [])
    assert result.verdict == "FAIL"


def test_verify_trace_mismatch():
    das_queries = [{"query": "(Inheritance $X $Y)", "count": 5, "results": ["a"]}]
    reissue = {"(Inheritance $X $Y)": {"count": 1, "results": ["a"]}}
    result = verify_trace(das_queries, reissue, [], {})
    assert result.trace_ok is False


def test_verify_trace_provenance_missing():
    das_queries = [{"query": "(Inheritance $X $Y)", "count": 1, "results": ["a"]}]
    reissue = {"(Inheritance $X $Y)": {"count": 1, "results": ["a"]}}
    citations = ["missing_sha"]
    audit = {"other_sha": True}
    result = verify_trace(das_queries, reissue, citations, audit)
    assert result.provenance_ok is False


def test_extract_final_answer_tolerates_prose():
    text = "Leading prose.\nSome text\nFINAL ANSWER (easy): the ceiling\nTrailing prose."
    assert extract_final_answer(text, "easy") == "the ceiling"
