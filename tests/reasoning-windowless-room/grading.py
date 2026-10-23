"""Grading v3 — STRICT GATING TEST (windowless room).

This is not a scored benchmark: it is a pass/fail GATE that verifies the
environment is set up for DAS-grounded reasoning governance. A case passes
only if EVERY gate condition holds:

  A-gate  (answer):     FINAL ANSWER line present + substantively correct.
  Q-gate  (query-first): a real das-retrieve query executed BEFORE the
                        answer, quoted with its DAS_RETRIEVE_OK receipt,
                        cross-attested against the benchmark-window
                        history, non-degenerate, and re-issued by the
                        harness with matching count.
  E-gate  (extraction): the agent actually extracted clauses from the
                        reasoning text and persisted them: the facts
                        index is non-empty, the first case's window shows
                        real persistence receipts, the case's FACTS line
                        resolves against the index, and every quoted
                        literal of the case's query comes from the index
                        (the extracted-predicate-awareness rule: queries
                        must REUSE the exact extracted vocabulary, never
                        reformulate it — a reformulated query matches
                        nothing and produces false absence).
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
  E_NO_EXTRACTION         facts index empty: no clauses were extracted at all
  E_NO_INGEST             first case: no real persistence receipts in the window
  E_NO_FACTS              knowledge case block has no FACTS: line
  E_FACTS_NOT_IN_INDEX    a FACTS: line expression is not in the facts index
  E_LITERAL_NOT_EXTRACTED a query literal does not come from the extracted
                          predicate vocabulary (reformulated query)
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
FACTS_LINE_RE = re.compile(r"^FACTS:\s*(.*)$", re.MULTILINE)
SOURCES_LINE_RE = re.compile(r"^SOURCES:\s*(.*)$", re.MULTILINE)
GIT_SHA_RE = re.compile(r"git:([0-9a-f]{40})")
URL_RE = re.compile(r"(https?://\S+)")
QUOTED_LITERAL_RE = re.compile(r'"([^"]+)"')

# The first case of the sequential run (facts.TEST_CASES order). After a
# DAS cleanup this is the case that MUST show real ingestion receipts
# (ARCHIVE-OK + BRIDGE-PERSIST-OK) — later cases may legitimately reuse
# already-persisted facts without new writes.
TEST_CASES_FIRST_ID = "original"


def normalize_expression(expr: str) -> str:
    """Whitespace-normalize a MeTTa expression for verbatim comparison."""
    return " ".join(expr.split())


def parse_facts_index(text: str) -> list[str]:
    """Parse the agent's facts index (extraction record) into expressions.

    One expression per line; markdown bullets/dashes and CASE markers are
    tolerated (stripped); blank lines and non-expression lines are skipped.
    """
    expressions: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("-") or line.startswith("*"):
            line = line.lstrip("-* ")
        if line.startswith("(") and line.endswith(")"):
            expressions.append(normalize_expression(line))
    return expressions


def index_literals(expressions: list[str]) -> set[str]:
    """The set of quoted literals used across the index expressions."""
    literals: set[str] = set()
    for expr in expressions:
        literals.update(QUOTED_LITERAL_RE.findall(expr))
    return literals


def query_literals(query: str) -> list[str]:
    """The quoted literals of a query pattern."""
    return QUOTED_LITERAL_RE.findall(query)


@dataclass
class CaseBlock:
    """Parsed per-case evidence block from answers.md."""
    case_id: str
    final_answer: str = ""
    queries: list[str] = field(default_factory=list)
    receipt_counts: list[int] = field(default_factory=list)
    facts_raw: str = ""
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
        facts = FACTS_LINE_RE.search(block_text)
        if facts:
            block.facts_raw = facts.group(1).strip()
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


def parse_facts_line(facts_raw: str) -> list[str]:
    """Parse a FACTS: line into normalized expressions (semicolon-separated)."""
    if not facts_raw:
        return []
    out: list[str] = []
    for part in facts_raw.split(";"):
        part = part.strip()
        if part.startswith("(") and part.endswith(")"):
            out.append(normalize_expression(part))
    return out


def parse_citations(sources_raw: str) -> list[tuple[str, str]]:
    """Extract (git:<sha>, url) citation pairs from a SOURCES line."""
    citations: list[tuple[str, str]] = []
    shas = GIT_SHA_RE.findall(sources_raw)
    urls = URL_RE.findall(sources_raw)
    for i, sha in enumerate(shas):
        url = urls[i] if i < len(urls) else ""
        citations.append((f"git:{sha}", url))
    return citations


INFORMATIONAL_CONDITIONS = {"Q_ATTESTED_VIA_ACCESS_LOG", "E_INGEST_ATTESTED_VIA_FACADE_LOG"}


def gate_case(
    case: dict,
    block: Optional[CaseBlock],
    history_queries: list[str],
    history_placeholder_calls: int,
    reissue_fn,
    citation_checks: list[tuple[str, str, list[str]]],
    facts_index: Optional[list[str]] = None,
    window_persist_receipts: int = 0,
    window_archive_receipts: int = 0,
    attestation: Optional[dict] = None,
) -> GateResult:
    """Apply the full gate (A/Q/E/P) to one case.

    reissue_fn(query) -> dict {"count": int, "error": str|None}
    citation_checks: list of (sha, url, conditions) — already resolved.
    facts_index: normalized expressions from the agent's facts index
    (extraction record); None = E-gate not applicable (legacy grading),
    [] = no clauses were extracted (fails every case).
    window_persist_receipts / window_archive_receipts: BRIDGE-PERSIST-OK /
    ARCHIVE-OK receipts in this case's benchmark window (E_NO_INGEST
    applies to the first case only: it must show a real ingest).
    attestation: harness-side attestation lane for the known history
    observability gap (PeTTa superpose/collapse collapses tool tuples to
    $_ in history): {"qe_pattern_match": bool, "access_count": int} —
    the query-engine log carried the exact pattern in the case window AND
    the read-proxy access log shows real POST /v1/query calls from the
    agent container. When both hold, a query missing from the (lossy)
    history is attested via the independent logs and recorded as the
    informational condition Q_ATTESTED_VIA_ACCESS_LOG instead of the
    blocking Q_NOT_IN_HISTORY. The evidence standard is unchanged: the
    query must still be proven real (now by two tamper-resistant
    machine logs instead of a known-lossy one) AND the receipt/reissue/
    degenerate checks still apply.
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
    is_first_case = case_id == TEST_CASES_FIRST_ID

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
        # das-retrieve args is fabricated evidence — UNLESS the harness-side
        # attestation lane proves it via the independent QE + access logs
        # (the history is known-lossy: tool tuples collapse to $_).
        if query not in history_queries:
            attested = bool(
                attestation
                and attestation.get("qe_pattern_match")
                and attestation.get("access_count", 0) >= 1
            )
            if attested:
                conditions.append("Q_ATTESTED_VIA_ACCESS_LOG")
            else:
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

    # --- E-gate: extraction + predicate-awareness ---
    # facts_index=None -> E-gate not applicable (batch/legacy grading);
    # facts_index=[] -> index exists but no clauses were extracted -> FAIL.
    if facts_index is not None:
        index = [normalize_expression(e) for e in facts_index]
        index_set = set(index)
        literals = index_literals(index)
        detail["facts_index_size"] = len(index)

        if not index:
            # No clauses were ever extracted from the reasoning text.
            conditions.append("E_NO_EXTRACTION")
        else:
            if is_first_case and (window_persist_receipts == 0 or window_archive_receipts == 0):
                # After a DAS cleanup the first case MUST show real ingestion:
                # at least one ARCHIVE-OK and one BRIDGE-PERSIST-OK receipt.
                # The history channel is lossy (tool outputs collapse to $_),
                # so when both receipts are missing from history the harness-
                # side facade-log lane may attest the ingest instead (real
                # 2xx POST /v1/write + POST /v1/archive from the agent IP):
                # recorded as the informational E_INGEST_ATTESTED_VIA_FACADE_LOG.
                attested_ingest = bool(
                    attestation
                    and attestation.get("write_count", 0) >= 1
                    and attestation.get("archive_count", 0) >= 1
                )
                if attested_ingest:
                    conditions.append("E_INGEST_ATTESTED_VIA_FACADE_LOG")
                else:
                    conditions.append("E_NO_INGEST")
            if not is_unsolvable:
                # FACTS: line must exist and resolve against the index.
                facts_line = parse_facts_line(block.facts_raw)
                if not facts_line:
                    conditions.append("E_NO_FACTS")
                else:
                    missing = [e for e in facts_line if e not in index_set]
                    if missing:
                        conditions.append("E_FACTS_NOT_IN_INDEX")
                        detail["facts_not_in_index"] = missing[:5]
                # every quoted literal of the executed query must come from the
                # extracted predicate vocabulary (reuse-verbatim rule)
                if block.queries:
                    foreign = [l for l in query_literals(normalize_query(block.queries[0]))
                               if l not in literals]
                    if foreign:
                        conditions.append("E_LITERAL_NOT_EXTRACTED")
                        detail["foreign_literals"] = foreign[:5]

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

    verdict = "PASS" if not [c for c in conditions if c not in INFORMATIONAL_CONDITIONS] else "FAIL"
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
