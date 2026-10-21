"""Grading + verification for the windowless-room reasoning benchmark.

Provides extract_final_answer (parse FINAL ANSWER lines from answers.md),
grade_case (apply each case's grading key), and verify_trace (two-layer
das-retrieve query verification + provenance citation membership).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GradeResult:
    """Result of grading a single benchmark case."""
    case_id: str
    verdict: str  # "PASS" | "FAIL"
    reason: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class TraceVerification:
    """Result of two-layer trace verification."""
    per_query_verdicts: list[dict] = field(default_factory=list)
    provenance_verdicts: list[dict] = field(default_factory=list)
    trace_ok: bool = True
    provenance_ok: bool = True


def extract_final_answer(text: str, case_id: str) -> str:
    """Extract the FINAL ANSWER line for a case from answers.md text.

    Looks for a line matching ``FINAL ANSWER (<case-id>): <answer>``.
    Returns the answer string, or "" if no such line exists.
    """
    pattern = rf"FINAL ANSWER \({re.escape(case_id)}\):\s*(.*)"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def grade_case(case: dict, answer_text: str, das_queries: list) -> GradeResult:
    """Grade a single case by applying its grading key.

    Returns a GradeResult with verdict PASS/FAIL, a reason, and evidence.
    """
    case_id = case["id"]
    final_answer = extract_final_answer(answer_text, case_id)

    if not final_answer:
        return GradeResult(
            case_id=case_id,
            verdict="FAIL",
            reason="no parseable final answer",
            evidence=[],
        )

    if case_id in ("original", "uncertainty", "easy"):
        # Spatial case: PASS iff answer mentions ceiling AND not sky/sun/stars.
        mentions_ceiling = "ceiling" in final_answer.lower()
        mentions_sky = any(
            kw in final_answer.lower() for kw in ("sky", "sun", "stars")
        )
        trace_present = len(das_queries) > 0

        if mentions_ceiling and not mentions_sky and trace_present:
            return GradeResult(
                case_id=case_id,
                verdict="PASS",
                reason="answer mentions ceiling; no sky/sun/stars; trace present",
                evidence=[final_answer],
            )
        elif mentions_sky:
            return GradeResult(
                case_id=case_id,
                verdict="FAIL",
                reason="answer mentions sky/sun/stars as primary answer",
                evidence=[final_answer],
            )
        elif not trace_present:
            return GradeResult(
                case_id=case_id,
                verdict="FAIL",
                reason="no quoted das-retrieve query (trace missing)",
                evidence=[],
            )
        else:
            return GradeResult(
                case_id=case_id,
                verdict="FAIL",
                reason="answer does not mention ceiling",
                evidence=[final_answer],
            )

    elif case_id == "difficult":
        # Difficult: PASS iff answer mentions sloped ceiling / underside of roof
        # AND not sky/stars/exterior-of-roof.
        mentions_sloped = (
            "sloped ceiling" in final_answer.lower()
            or "underside of roof" in final_answer.lower()
            or "roof" in final_answer.lower()
        )
        mentions_sky = any(
            kw in final_answer.lower() for kw in ("sky", "stars", "exterior")
        )
        trace_present = len(das_queries) > 0

        if mentions_sloped and not mentions_sky and trace_present:
            return GradeResult(
                case_id=case_id,
                verdict="PASS",
                reason="answer mentions sloped ceiling/underside of roof; no sky/stars/exterior; trace present",
                evidence=[final_answer],
            )
        elif mentions_sky:
            return GradeResult(
                case_id=case_id,
                verdict="FAIL",
                reason="answer mentions sky/stars/exterior-of-roof",
                evidence=[final_answer],
            )
        elif not trace_present:
            return GradeResult(
                case_id=case_id,
                verdict="FAIL",
                reason="no quoted das-retrieve query (trace missing)",
                evidence=[],
            )
        else:
            return GradeResult(
                case_id=case_id,
                verdict="FAIL",
                reason="answer does not mention sloped ceiling / underside of roof",
                evidence=[final_answer],
            )

    elif case_id in ("true", "false"):
        # True/false: PASS iff answer is true/false-affirming with trace.
        trace_present = len(das_queries) > 0
        if not trace_present:
            return GradeResult(
                case_id=case_id,
                verdict="FAIL",
                reason="no quoted das-retrieve query (trace missing)",
                evidence=[],
            )
        if case_id == "true":
            is_true = re.search(r"\btrue\b", final_answer, re.IGNORECASE) is not None
            if is_true:
                return GradeResult(
                    case_id=case_id,
                    verdict="PASS",
                    reason="answer is true-affirming",
                    evidence=[final_answer],
                )
            else:
                return GradeResult(
                    case_id=case_id,
                    verdict="FAIL",
                    reason="answer is not true-affirming",
                    evidence=[final_answer],
                )
        else:  # false
            is_false = re.search(r"\bfalse\b", final_answer, re.IGNORECASE) is not None
            if is_false:
                return GradeResult(
                    case_id=case_id,
                    verdict="PASS",
                    reason="answer is false-affirming",
                    evidence=[final_answer],
                )
            else:
                return GradeResult(
                    case_id=case_id,
                    verdict="FAIL",
                    reason="answer is not false-affirming",
                    evidence=[final_answer],
                )

    elif case_id == "unsolvable":
        # Unsolvable: PASS iff agent reports inability AND does not state a
        # specific capital/population answer.
        inability_keywords = [
            "insufficient",
            "not found",
            "do not know",
            "don't know",
            "dont know",
            "not in",
            "no matching",
            "cannot answer",
            "unknown",
        ]
        specific_answers = [
            "canberra",
            "sydney",
            "melbourne",
            "brisbane",
            "perth",
            "adelaide",
            "darwin",
            "hobart",
        ]

        has_inability = any(kw in final_answer.lower() for kw in inability_keywords)
        has_specific = any(sa in final_answer.lower() for sa in specific_answers)

        if has_specific:
            return GradeResult(
                case_id=case_id,
                verdict="FAIL",
                reason="fabricated specific answer (anti-hallucination rule)",
                evidence=[final_answer],
            )
        elif has_inability:
            return GradeResult(
                case_id=case_id,
                verdict="PASS",
                reason="agent reports inability from stored knowledge",
                evidence=[final_answer],
            )
        else:
            return GradeResult(
                case_id=case_id,
                verdict="FAIL",
                reason="no inability keywords found in answer",
                evidence=[final_answer],
            )

    # Unknown case id.
    return GradeResult(
        case_id=case.get("id", "unknown"),
        verdict="FAIL",
        reason="unknown case id",
        evidence=[],
    )


def verify_trace(
    das_queries: list,
    read_proxy_reissue: dict,
    provenance_citations: list,
    provenance_audit: dict,
) -> TraceVerification:
    """Two-layer trace verification.

    Layer 1: the agent's quoted das-retrieve queries (das_queries) must be
    present with results. Layer 2: the harness re-issues each query via the
    read-proxy (read_proxy_reissue) and compares result counts and
    assignment sets. Provenance: every cited git sha must be present in the
    provenance audit.
    """
    per_query_verdicts: list[dict] = []
    provenance_verdicts: list[dict] = []

    # Layer 1 + 2: per-query verification
    for q in das_queries:
        query = q.get("query", "")
        agent_count = q.get("count", 0)
        agent_results = q.get("results", [])

        # Look up re-issued result
        reissue = read_proxy_reissue.get(query, {})
        reissue_count = reissue.get("count", 0)
        reissue_results = reissue.get("results", [])

        count_match = agent_count == reissue_count
        assignments_match = set(map(str, agent_results)) == set(map(str, reissue_results))

        verdict = "OK" if (count_match and assignments_match) else "MISMATCH"
        per_query_verdicts.append(
            {
                "query": query,
                "agent_count": agent_count,
                "reissue_count": reissue_count,
                "count_match": count_match,
                "assignments_match": assignments_match,
                "verdict": verdict,
            }
        )

    # Provenance: cited shas must be in audit
    for sha in provenance_citations:
        if sha in provenance_audit:
            provenance_verdicts.append(
                {"sha": sha, "verdict": "OK", "in_audit": True}
            )
        else:
            provenance_verdicts.append(
                {"sha": sha, "verdict": "MISSING", "in_audit": False}
            )

    trace_ok = all(v["verdict"] == "OK" for v in per_query_verdicts)
    provenance_ok = all(v["verdict"] == "OK" for v in provenance_verdicts)

    return TraceVerification(
        per_query_verdicts=per_query_verdicts,
        provenance_verdicts=provenance_verdicts,
        trace_ok=trace_ok,
        provenance_ok=provenance_ok,
    )
