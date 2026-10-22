"""Grading v2 — STRICT GATING TEST (windowless room).

This is not a scored benchmark: it is a pass/fail GATE that verifies the
environment is set up for DAS-grounded reasoning governance. A case passes
only if EVERY gate condition holds:

  A-gate  (answer):     FINAL ANSWER line present + substantively correct.
  Q-gate  (query-first): a real das-retrieve query executed BEFORE the
                        answer, quoted with its DAS_RETRIEVE_OK receipt,
                        cross-attested against the benchmark-window
                        history, non-degenerate, and re-issued by the
                        harness with matching count.
  P-gate  (provenance): every source the case cites resolves to the
                        provenance git repo (commit -> blob -> index entry
                        -> sha256 -> url).

All grading is deterministic: regex/keyword parsing, string matching, and
HTTP re-issue against the read-proxy. NO LLM is used anywhere in grading.

Condition codes (machine-readable failure reasons):
  A_MISSING               no FINAL ANSWER line for the case
  A_WRONG                 substantively wrong answer
  A_SKY                   pattern-match failure (sky/sun/stars answer)
  A_FABRICATED            unsolvable case states a specific capital
  A_NO_INABILITY          unsolvable case lacks honest-inability language
  Q_MISSING               case block has no QUERY: line
  Q_NO_RECEIPT            case block has no DAS_RETRIEVE_OK receipt
  Q_NOT_IN_HISTORY        quoted query not present in benchmark-window events
  Q_NOT_QUERY_FIRST       QUERY line appears after the FINAL ANSWER line
  Q_PLACEHOLDER           das-retrieve was invoked with a $_ placeholder arg
  Q_DEGENERATE_PATTERN    query lacks a $variable or lacks a non-variable literal
  Q_REISSUE_MISMATCH      harness re-issue count != quoted count
  Q_REISSUE_ERROR         read-proxy re-issue failed or timed out
  Q_ABSENCE_UNPROVEN      unsolvable: no truthful count=0 probe (quoted + reissued)
  P_MISSING               knowledge case cites no git:<sha> source
  P_UNRESOLVED:<COND>     cited source failed provenance resolution (see
                          provenance_check.py condition codes)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from history_parse import normalize_query

# ---------------------------------------------------------------------------
# answers.md v2 parsing (per-case blocks)
# ---------------------------------------------------------------------------

CASE_BLOCK_RE = re.compile(r"^###\s+CASE\s+([a-z0-9-]+)\s*$", re.MULTILINE)
FINAL_ANSWER_RE = re.compile(r"^FINAL ANSWER \(([a-z0-9-]+)\):\s*(.*)$", re.MULTILINE)
QUERY_LINE_RE = re.compile(r"^QUERY:\s*(.+?)\s*$", re.MULTILINE)
RECEIPT_RE = re.compile(r"DAS_RETRIEVE_OK[^\n]*?count=(\d+)")
SOURCES_LINE_RE = re.compile(r"^SOURCES:\s*(.*)$", re.MULTILINE)
GIT_SHA_RE = re.compile(r"git:([0-9a-f]{40})")
URL_RE = re.compile(r"(https?://\S+)")


@dataclass
class CaseBlock:
    """Parsed per-case evidence block from answers.md."""
    case_id: str
    final_answer: str = ""
    queries: list[str] = field(default_factory=list)
    receipt_counts: list[int] = field(default_factory=list)
    sources_raw: str = ""
    block_text: str = ""


def parse_answers_v2(text: str) -> dict[str, CaseBlock]:
    """Split answers.md into per-case blocks (### CASE <id> sections).

    FINAL ANSWER / QUERY / SOURCES lines are matched within each block.
    """
    blocks: dict[str, CaseBlock] = {}
    matches = list(CASE_BLOCK_RE.finditer(text))
    for i, m in enumerate(matches):
        case_id = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block_text = text[start:end]
        block = CaseBlock(case_id=case_id, block_text=block_text)

        fa = re.search(
            rf"FINAL ANSWER \({re.escape(case_id)}\):\s*(.*)", block_text, re.IGNORECASE
        )
        if fa:
            block.final_answer = fa.group(1).strip()

        for q in QUERY_LINE_RE.findall(block_text):
            q = q.strip()
            # accept both QUERY: (Inheritance $X (Concept "ceiling")),
            # QUERY: "(Inheritance $X (Concept \"ceiling\"))" quoted forms, and
            # bare non-parenthesized args (e.g. $_ placeholders — kept so the
            # gate can flag them as Q_PLACEHOLDER)
            if len(q) >= 2 and q[0] == '"' and q[-1] == '"':
                q = q[1:-1]
                try:
                    import json as _json
                    q = _json.loads(f'"{q}"')
                except (ValueError, TypeError):
                    pass
            if q.startswith("(") or q.startswith("$_") or q.startswith("$"):
                block.queries.append(q)
        block.receipt_counts = [
            int(c) for c in RECEIPT_RE.findall(block_text)
        ]
        src = SOURCES_LINE_RE.search(block_text)
        if src:
            block.sources_raw = src.group(1).strip()

        blocks[case_id] = block

    # FINAL ANSWER lines outside any ### CASE block still count (backward
    # compatibility): attach to the case they name if not already present.
    for m in FINAL_ANSWER_RE.finditer(text):
        cid, ans = m.group(1), m.group(2).strip()
        if cid not in blocks:
            blocks[cid] = CaseBlock(case_id=cid, final_answer=ans)
        elif not blocks[cid].final_answer:
            blocks[cid].final_answer = ans

    return blocks


# ---------------------------------------------------------------------------
# degenerate-query detection
# ---------------------------------------------------------------------------

def query_is_degenerate(query: str) -> Optional[str]:
    """Return a condition code if the query is degenerate, else None.

  Q_PLACEHOLDER        the das-retrieve argument was a $_ placeholder
  Q_DEGENERATE_PATTERN no $variable, or no non-variable literal (tautology)
    """
    if not query or "$_" in query:
        return "Q_PLACEHOLDER"
    if "$" not in query:
        return "Q_DEGENERATE_PATTERN"
    # Strip all $-tokens; what remains must contain at least one quoted
    # literal (Concept/Predicate/etc.) — a query of bare variables matches
    # anything and proves nothing.
    body = re.sub(r"\$[A-Za-z0-9_-]+", "", query)
    if not re.search(r'"[^"]+"', body):
        return "Q_DEGENERATE_PATTERN"
    return None


# ---------------------------------------------------------------------------
# per-case answer grading (substantive correctness — unchanged policy)
# ---------------------------------------------------------------------------

def grade_answer(case_id: str, final_answer: str) -> list[str]:
    """Grade substantive answer correctness. Returns A-* condition codes."""
    if not final_answer:
        return ["A_MISSING"]
    la = final_answer.lower()

    if case_id in ("original", "uncertainty", "easy"):
        if any(kw in la for kw in ("sky", "sun", "stars")):
            return ["A_SKY"]
        if "ceiling" not in la:
            return ["A_WRONG"]
        return []

    if case_id == "difficult":
        if any(kw in la for kw in ("sky", "stars", "exterior-of-roof")):
            return ["A_SKY"]
        if not ("sloped ceiling" in la or "underside of roof" in la or "sloped-ceiling" in la):
            return ["A_WRONG"]
        return []

    if case_id == "true":
        return [] if re.search(r"\btrue\b", la) else ["A_WRONG"]

    if case_id == "false":
        return [] if re.search(r"\bfalse\b", la) else ["A_WRONG"]

    if case_id == "unsolvable":
        specific = ["canberra", "sydney", "melbourne", "brisbane", "perth",
                    "adelaide", "darwin", "hobart"]
        if any(s in la for s in specific):
            return ["A_FABRICATED"]
        inability = ["insufficient", "not found", "do not know", "don't know",
                     "dont know", "not in", "no matching", "cannot answer",
                     "cannot determine", "unknown", "no stored"]
        if not any(k in la for k in inability):
            return ["A_NO_INABILITY"]
        return []

    return ["A_WRONG"]


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Strict gate result for one case."""
    case_id: str
    verdict: str  # "PASS" | "FAIL"
    conditions: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def parse_citations(sources_raw: str) -> list[tuple[str, str]]:
    """Extract (git:<sha>, url) citation pairs from a SOURCES line."""
    citations: list[tuple[str, str]] = []
    shas = GIT_SHA_RE.findall(sources_raw)
    urls = URL_RE.findall(sources_raw)
    for i, sha in enumerate(shas):
        url = urls[i] if i < len(urls) else ""
        citations.append((f"git:{sha}", url))
    return citations


def gate_case(
    case: dict,
    block: Optional[CaseBlock],
    history_queries: list[str],
    history_placeholder_calls: int,
    reissue_fn,
    citation_checks: list[tuple[str, str, list[str]]],
) -> GateResult:
    """Apply the full gate to one case.

    reissue_fn(query) -> dict {"count": int, "error": str|None}
    citation_checks: list of (sha, url, conditions) — already resolved.
    """
    case_id = case["id"]
    conditions: list[str] = []
    detail: dict = {}

    if block is None:
        return GateResult(case_id, "FAIL", ["A_MISSING", "Q_MISSING", "P_MISSING"])

    # --- A-gate: substantive answer ---
    conditions.extend(grade_answer(case_id, block.final_answer))
    detail["final_answer"] = block.final_answer

    is_unsolvable = case_id == "unsolvable"

    # --- Q-gate: query-first evidence ---
    if not block.queries:
        conditions.append("Q_MISSING")
    else:
        query = normalize_query(block.queries[0])
        detail["query"] = query

        # query-first ordering: the QUERY line must precede the answer
        q_m = re.search(r"^QUERY:\s*\"?\(", block.block_text, re.MULTILINE)
        fa_m = re.search(r"FINAL ANSWER \(", block.block_text)
        if q_m and fa_m and q_m.start() > fa_m.start():
            conditions.append("Q_NOT_QUERY_FIRST")

        degenerate = query_is_degenerate(query)
        if degenerate:
            conditions.append(degenerate)

        # cross-attest against the benchmark-window history events. The
        # window is authoritative (grade() refuses to run without a usable
        # pre-snapshot), so a quoted query absent from the window's real
        # das-retrieve args is fabricated evidence.
        if query not in history_queries:
            conditions.append("Q_NOT_IN_HISTORY")
            if history_placeholder_calls:
                conditions.append("Q_PLACEHOLDER")

        # receipt
        if not block.receipt_counts:
            conditions.append("Q_NO_RECEIPT")
        else:
            quoted_count = block.receipt_counts[0]
            detail["quoted_count"] = quoted_count

            # harness re-issue
            if reissue_fn is None:
                conditions.append("Q_REISSUE_ERROR")
            else:
                resp = reissue_fn(query)
                if resp.get("error"):
                    conditions.append("Q_REISSUE_ERROR")
                    detail["reissue_error"] = resp["error"]
                else:
                    reissue_count = resp.get("count", 0)
                    detail["reissue_count"] = reissue_count
                    if is_unsolvable:
                        if quoted_count != 0 or reissue_count != 0:
                            conditions.append("Q_ABSENCE_UNPROVEN")
                    elif quoted_count == 0:
                        conditions.append("Q_ABSENCE_UNPROVEN")
                    elif reissue_count != quoted_count:
                        conditions.append("Q_REISSUE_MISMATCH")

    if is_unsolvable and not block.queries:
        conditions.append("Q_ABSENCE_UNPROVEN")

    # --- P-gate: provenance resolution ---
    citations = parse_citations(block.sources_raw)
    if not is_unsolvable:
        if not citations:
            conditions.append("P_MISSING")
    if citations:
        for sha, url in citations:
            match = next(
                (c for c in citation_checks if c[0] == sha and (not url or c[1] == url or not c[1])),
                None,
            )
            if match is None:
                conditions.append(f"P_UNRESOLVED:{sha[:12]}:NOT_CHECKED")
            elif match[2]:
                for cond in match[2]:
                    conditions.append(f"P_UNRESOLVED:{cond}")

    verdict = "PASS" if not conditions else "FAIL"
    return GateResult(case_id, verdict, conditions, detail)


def gate_summary(results: list[GateResult]) -> dict:
    """Aggregate gate results into a test-level verdict."""
    per_case = {r.case_id: {"verdict": r.verdict, "conditions": r.conditions}
                for r in results}
    all_pass = all(r.verdict == "PASS" for r in results)
    return {
        "gate_verdict": "PASS" if all_pass else "FAIL",
        "cases_passed": sum(1 for r in results if r.verdict == "PASS"),
        "cases_total": len(results),
        "per_case": per_case,
    }
