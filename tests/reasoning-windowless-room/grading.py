"""Grading v3 — STRICT GATING TEST (windowless room).

This is not a scored benchmark: it is a pass/fail GATE that verifies the
environment is set up for DAS-grounded reasoning governance. A case passes
only if EVERY gate condition holds:

  A-gate  (answer):     FINAL ANSWER line present. Substance is judged
                        by ONE OpenAI chat-completions-compatible LLM
                        call (llm_judge.py, v16 single-prompt form):
                        ONE user message carrying the test prompt, the
                        agent's final answer, and the expected correct
                        answer; the endpoint replies TRUE or FALSE —
                        no reasoning, receipts, or other gate evidence.
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
  R-gate  (reasoning):   the REASONING: line must carry the MeTTa reasoning
                        trace — the formalized question clause (= the
                        executed query), the fact steps, and the derivation
                        conclusion — NOT prose. Every trace step must be an
                        existing atom: verbatim (whitespace-normalized) in
                        the extraction record, or the executed query clause
                        itself. This is the campaign-grade standard
                        (directive 2026-10-24): formalize the question as a
                        MeTTa clause, reason over retrieved/persisted facts,
                        persist the trace, quote it verbatim. The unsolvable
                        case still needs the trace shape (question clause +
                        the count=0 absence probes) but is exempt from index
                        grounding (no facts to ground).
  P-gate  (provenance): deterministic source reconstruction (v17): the
                        reconstruct_sources.py JSON payload (trace expr ->
                        handle -> mongo custom_attributes -> ledger
                        commit -> ledger entry) maps to
                        P_UNRESOLVED:<expr12>:<COND> / P_MISSING codes,
                        the H_* HANDLES cross-check rides in verbatim, and
                        sources outside the case's background set are the
                        informational P_SOURCE_SET_MISMATCH.

All grading EXCEPT the answer-substance call is deterministic: regex/keyword
parsing, string matching, and HTTP re-issue against the read-proxy. The one
LLM use is the A-gate judge (v16 directive 2026-10-26): a single
chat-completions call deciding TRUE/FALSE for the FINAL ANSWER line
from one prompt (question + agent answer + expected answer), with no
access to any other gate evidence.

Condition codes (machine-readable failure reasons):
  A_MISSING               no FINAL ANSWER line for the case
  A_WRONG                 answer judged INCORRECT by the LLM judge
  A_JUDGE_UNAVAILABLE     the judge call failed (harness-side error; fails
                          the case so an ungraded answer can never pass)
  Q_MISSING               case block has no QUERY: line
  Q_NO_RECEIPT            case block has no DAS_RETRIEVE_OK receipt
  Q_NOT_IN_HISTORY        quoted query not present in benchmark-window events
  Q_NOT_QUERY_FIRST       QUERY line appears after the FINAL ANSWER line
  Q_PLACEHOLDER           das-retrieve was invoked with a $_ placeholder arg
  Q_DEGENERATE_PATTERN    query lacks a $variable or lacks a non-variable literal
                          (quoted string or bare content symbol; structural
                          keywords do not count)
  Q_REISSUE_MISMATCH      harness re-issue count != quoted count
  Q_REISSUE_ERROR         read-proxy re-issue failed or timed out
  Q_ABSENCE_UNPROVEN      unsolvable: no truthful count=0 probe (quoted + reissued)
  E_NO_EXTRACTION         facts index empty: no clauses were extracted at all
  E_NO_INGEST             first case: no real persistence receipts in the window
  E_NO_FACTS              knowledge case block has no FACTS: line
  E_FACTS_NOT_IN_INDEX    a FACTS: line expression is not in the facts index
  E_LITERAL_NOT_EXTRACTED a query literal does not come from the extracted
                          predicate vocabulary (reformulated query)
  R_MISSING               case block has no REASONING: line
  R_NOT_METTA             the reasoning line is prose, or fewer than two
                          s-expression trace steps (a trace needs at least
                          the question clause + one derivation/fact step)
  R_NOT_EXECUTED          the trace carries no interpreter (stv ...) output
                          (or the extraction record has no `exec` lines):
                          hand-composed truth values do not count — the
                          reasoning must have been EXECUTED via the metta
                          skill (scenario A/A2 lesson, 2026-10-25; unsolvable
                          cases are exempt)
  R_TRACE_NOT_GROUNDED    a trace step is neither in the extraction record
                          nor the executed query clause (not an existing
                          atom — fabricated or paraphrased reasoning)
  P_MISSING               knowledge case: reconstruction finds no used
                          stored facts carrying any provenance attributes
                          (nothing citable; unsolvable exempt)
  P_UNRESOLVED:<expr12>:<COND>
                          a used stored fact's source failed resolution
                          (COND per GATES-REFERENCE §12: the 8-value set)
  H_MISSING / H_COUNT_MISMATCH / H_MISMATCH
                          the HANDLES cross-check failed (blocking, D4;
                          knowledge case — unsolvable exempt, parallel to
                          P_MISSING)
  P_SOURCE_SET_MISMATCH   informational: a source ref attached to the
                          case's facts is outside the case's background
                          source set
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
QUERY_LINE_RE = re.compile(r"^QUERY:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
RECEIPT_RE = re.compile(r"DAS_RETRIEVE_OK[^\n]*?count=(\d+)")
FACTS_LINE_RE = re.compile(r"^FACTS:[ \t]*(.*)$", re.MULTILINE)
HANDLES_LINE_RE = re.compile(r"^HANDLES:[ \t]*(.*)$", re.MULTILINE)
REASONING_LINE_RE = re.compile(r"^REASONING:[ \t]*(.*)$", re.MULTILINE)
STV_RE = re.compile(r"\(stv\s+-?[0-9]+(?:\.[0-9]+)?\s+-?[0-9]+(?:\.[0-9]+)?\)")


def parse_exec_outputs(text: str) -> list[str]:
    """Extract the interpreter-output s-expressions from the extraction
    record's `exec <call> => <output>` lines (scenario-A/A2 lesson,
    2026-10-25). The outputs are executed derivation atoms with their
    (stv ...) truth values; they count as grounded trace steps (existing
    atoms produced by the interpreter, recorded verbatim).

    v17 note (wr3o-20261028): the live exec lines record the output with
    ONE EXTRA outer paren layer (``exec (|~ ...) => (((Evaluation ...)
    (stv 1.0 0.81)))``) while the trace quotes the single-wrapped product.
    This function keeps the recorded form VERBATIM (unchanged); the
    R-gate grounds both shapes via ``exec_grounding_set`` (call side +
    raw and single-redundant-paren-stripped output variants)."""
    outputs: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("exec ") and "=>" in line:
            out = line.split("=>", 1)[1].strip()
            if out.startswith("(") and out.endswith(")"):
                outputs.append(normalize_expression(out))
    return outputs


def _strip_redundant_outer_paren(expr: str) -> str:
    """Strip ONE redundant outer paren layer from a balanced s-expression
    (v17, wr3o-20261028). The live extraction-record exec lines wrap the
    interpreter product in an extra paren pair — ``(((Evaluation ...)
    (stv 1.0 0.81)))`` — while the REASONING trace quotes the normal form
    ``((Evaluation ...) (stv 1.0 0.81))``. CONSERVATIVE single-strip rule:
    the outer layer is stripped only when the content it wraps is itself
    exactly ONE balanced parenthesized s-expression. Two-product outputs
    (``((A ...) (B ...))``) and the normal atom+stv pair keep their outer
    layer — a paired product is never mistaken for one redundant wrap.
    Returns the input unchanged when no redundant layer is present."""
    s = expr.strip()
    if not (s.startswith("(") and s.endswith(")")):
        return s
    inner = s[1:-1].strip()
    if not (inner.startswith("(") and inner.endswith(")")):
        return s
    if len(_top_level_sexprs(inner)) != 1:
        return s
    return normalize_expression(inner)


def exec_grounding_set(record_text: str) -> set[str]:
    """The R-gate grounding set minted from the extraction record's
    ``exec <call> => <output>`` lines (v17 harness iteration 2,
    wr3o-20261028).

    The executed-derivation trace step carries TWO atoms — the CALL and
    the CONCLUSION — and BOTH must ground. The live record shapes:

    - CALL side  ``(|~ premiseA premiseB)`` — an executed artifact in
      its own right; its literals include the agent-authored rule
      predicate, which is present in no stored atom, so it must enter
      the grounding set verbatim or the step can never ground.
    - OUTPUT side — recorded with ONE EXTRA outer paren layer
      (``(((Evaluation ...) (stv 1.0 0.81)))``) while the trace quotes
      the single-wrapped product; BOTH the raw recorded form and the
      single-redundant-paren-stripped variant enter the set
      (``_strip_redundant_outer_paren``).

    Every element is whitespace-normalized (the established comparison
    standard). No exec lines -> empty set (no phantom grounding)."""
    grounded: set[str] = set()
    if not record_text:
        return grounded
    for line in record_text.splitlines():
        line = line.strip()
        if not (line.startswith("exec ") and "=>" in line):
            continue
        left, _, right = line.partition("=>")
        call = left[len("exec"):].strip()
        if call.startswith("(") and call.endswith(")"):
            grounded.add(normalize_expression(call))
        out = right.strip()
        if out.startswith("(") and out.endswith(")"):
            grounded.add(normalize_expression(out))
            grounded.add(normalize_expression(_strip_redundant_outer_paren(out)))
    return grounded
QUOTED_LITERAL_RE = re.compile(r'"([^"]+)"')

# The first case of the sequential run (facts.TEST_CASES order). After a
# DAS cleanup this is the case that MUST show a real ingest receipt
# (BRIDGE-PERSIST-OK) — later cases may legitimately reuse
# already-persisted facts without new writes.
TEST_CASES_FIRST_ID = "original"


def normalize_expression(expr: str) -> str:
    """Whitespace-normalize a MeTTa expression for verbatim comparison."""
    return " ".join(expr.split())


def _balanced_expression_prefix(line: str) -> str | None:
    """The balanced, quote-aware parenthesized prefix of ``line``, if any.

    v9 (wr3h evidence): the agent's real extraction-record lines carry the
    expression plus trailing annotations — ``expr (...) src=<file> git:<sha>``
    or receipt strings like ``(BRIDGE-PERSIST-OK verified=19)`` — so the
    expression is the balanced prefix, not the whole line.
    """
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(line):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return line[: i + 1]
    return None


def parse_facts_index(text: str) -> list[str]:
    """Parse the agent's facts index (extraction record) into expressions.

    Tolerated line shapes (v9, from live wr3h evidence): plain parenthesized
    expressions, markdown bullets, a leading ``expr`` label (the template's
    recorded format), and trailing receipt/source annotations after the
    balanced expression. ``source <file> git:<sha>`` lines, headers, and
    non-expression lines are skipped.
    """
    expressions: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("-") or line.startswith("*"):
            line = line.lstrip("-* ")
        if line.startswith("expr ") or line.startswith("expr\t"):
            line = line[len("expr"):].lstrip()
        if not line.startswith("("):
            continue
        prefix = _balanced_expression_prefix(line)
        if prefix and len(prefix) > 2:
            expressions.append(normalize_expression(prefix))
    return expressions


def index_variable_form(expr: str) -> str | None:
    """A probe pattern for ``expr``: last top-level element replaced by $X.

    Ground (variable-free) patterns never complete in the pinned engine,
    so DAS presence is probed by binding the last element to a variable and
    comparing the count (>0 = present). Top-level element boundaries are
    found with a quote-aware scan (parenthesis depth + string state), so
    parentheses or spaces inside quoted literals cannot confuse it.
    Returns None when the expression admits no such form (not
    parenthesized / unbalanced / no second element to bind).
    """
    s = expr.strip()
    if not s.startswith("("):
        return None
    depth = 0
    in_str = False
    esc = False
    cur_start: int | None = None   # start of the current top-level element
    outer_close: int | None = None
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            if depth == 1 and cur_start is None:
                cur_start = i
            continue
        if ch == "(":
            depth += 1
            if depth > 1 and cur_start is None:
                cur_start = i
            continue
        if ch == ")":
            depth -= 1
            if depth == 0:
                outer_close = i
                break
            continue  # inner close: part of the current element
        if depth == 1 and ch.isspace():
            cur_start = None  # next element starts after this boundary
            continue
        if depth == 1 and cur_start is None:
            cur_start = i
    if outer_close is None or cur_start is None:
        return None  # unbalanced, or no element after the last boundary
    return s[:cur_start] + "$X" + s[outer_close:]


def index_literals(expressions: list[str]) -> set[str]:
    """The set of quoted literals used across the index expressions."""
    literals: set[str] = set()
    for expr in expressions:
        literals.update(QUOTED_LITERAL_RE.findall(expr))
    return literals


def query_literals(query: str) -> list[str]:
    """The quoted literals of a query pattern."""
    return QUOTED_LITERAL_RE.findall(query)


def parse_reasoning_trace(reasoning_raw: str) -> tuple[list[str], bool]:
    """Parse a REASONING: line into (normalized MeTTa trace steps, has_prose).

    The trace uses the same semicolon-separated convention as the FACTS:
    line: `<question-clause>; <fact-step-1>; ...; <conclusion-clause>`.
    STRICT: every non-empty semicolon-separated segment must be a
    parenthesized s-expression; any other content is prose (has_prose=True
    -> R_NOT_METTA). Generated text instead of the MeTTa trace fails the
    R-gate — that is the campaign-grade standard (2026-10-24 directive).
    # v17: stv-annotated interpreter outputs and trailing prose annotations are legitimate live trace shapes (mirrored by reconstruct_sources._strip_stv; prose → has_prose → R_NOT_METTA).
    """
    steps: list[str] = []
    has_prose = False
    for part in (reasoning_raw or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if part.startswith("(") and part.endswith(")"):
            steps.append(normalize_expression(part))
        else:
            has_prose = True
    return steps, has_prose


@dataclass
class CaseBlock:
    """Parsed per-case evidence block from answers.md."""
    case_id: str
    final_answer: str = ""
    queries: list[str] = field(default_factory=list)
    receipt_counts: list[int] = field(default_factory=list)
    facts_raw: str = ""
    handles_raw: str = ""
    reasoning_raw: str = ""
    block_text: str = ""


def parse_answers_v2(text: str) -> dict[str, CaseBlock]:
    """Split answers.md into per-case blocks (### CASE <id> sections).

    FINAL ANSWER / QUERY / FACTS / HANDLES / REASONING lines are matched
    within each block.
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
        handles = HANDLES_LINE_RE.search(block_text)
        if handles:
            block.handles_raw = handles.group(1).strip()
        reason = REASONING_LINE_RE.search(block_text)
        if reason:
            block.reasoning_raw = reason.group(1).strip()

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
    # v10 (wr3i evidence): strip all $-tokens; what remains must contain at
    # least one non-variable literal — a quoted string ("...") or a bare
    # CONTENT symbol. The live working query `(--> (looking-up windowless-room)
    # $X)` carries bare symbols and no quoted literals; the old quoted-only
    # check rejected it, contradicting this docstring. Bare STRUCTURAL
    # symbols (link-type keywords like Evaluation/Inheritance) do NOT count:
    # `(Evaluation $X $Y)` is still a matches-anything tautology probe.
    body = re.sub(r"\$[A-Za-z0-9_-]+", "", query)
    if not _has_query_literal(body):
        return "Q_DEGENERATE_PATTERN"
    return None


# Structural MeTTa/DAS vocabulary: type/link keywords that carry no specific
# content. A degeneracy check that accepted them as "literals" would pass
# tautology probes like `(Evaluation $X $Y)`.
STRUCTURAL_SYMBOLS = {
    "Concept", "Predicate", "Schema", "Type", "TypedAtom", "DAS",
    "Evaluation", "Inheritance", "Implication", "Equal", "Similarity",
    "Set", "List", "stv", "self", "Empty",
}


def _has_query_literal(body: str) -> bool:
    """True iff the $-stripped query body carries a non-variable literal:
    a quoted string or a bare CONTENT symbol (not a structural keyword)."""
    if re.search(r'"[^"]+"', body):
        return True
    return any(tok not in STRUCTURAL_SYMBOLS
               for tok in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", body))


def _bare_content_symbols(expr: str) -> set[str]:
    """Bare (unquoted) content symbols of a MeTTa expression — everything
    matching an identifier EXCEPT structural/type keywords, after stripping
    $-variables (a bare symbol check must not count variables as content;
    wr3i test evidence: $X leaked into the set). Operators (-->, |-, =)
    contain no letters and never match."""
    body = re.sub(r'"[^"]*"', "", expr)  # quoted symbols are NOT bare
    body = re.sub(r"\$[A-Za-z0-9_-]+", "", body)
    toks = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", body)
    return {t for t in toks if t not in STRUCTURAL_SYMBOLS}


def _top_level_sexprs(text: str) -> list[str]:
    """The top-level, balanced, quote-aware s-expressions of ``text``."""
    out: list[str] = []
    depth = 0
    in_str = False
    start = 0
    for i, ch in enumerate(text):
        if in_str:
            if ch == '"' and (i == 0 or text[i - 1] != "\\"):
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    out.append(normalize_expression(text[start:i + 1]))
    return out


def _split_derivation_atoms(step: str) -> list[str]:
    """Split an executed-derivation trace step into its component atoms.

    v10 (wr3i evidence): the executed derivation step carries the
    interpreter record line shape ``(<operator> <premises...>) => <output>``
    (the whole line parses as one s-expression because the output's closing
    paren balances the call's opening). Grounding must compare the ATOMS
    (call, output — each a balanced sub-expression), not the whole line:
    a whole-line comparison can never ground it. A step without ``=>`` is a
    single atom (the clause itself) — the pre-v10 shape."""
    if "=>" not in step:
        return [step]
    left, right = step.split("=>", 1)
    return _top_level_sexprs(left) + _top_level_sexprs(right)


# ---------------------------------------------------------------------------
# per-case answer grading (substantive correctness — unchanged policy)
# ---------------------------------------------------------------------------

def grade_answer(case: dict, final_answer: str,
                  judge_fn=None) -> tuple[list[str], dict]:
    """A-gate (v15b): presence + LLM-judged substance.

    The judge (llm_judge.make_judge, v16 single-prompt form) sees ONLY
    the test question, the agent's FINAL ANSWER text, and the expected
    correct answer — one user message, no reasoning trace, receipts, or
    other gate evidence. Returns (conditions, judge_detail).

    Fail-safe: no judge configured (or the judge call fails) ->
    A_JUDGE_UNAVAILABLE — an answer that was never judged can never
    pass the case (the deterministic v2-v14 keyword lexicons are gone;
    A_SKY/A_FABRICATED/A_NO_INABILITY no longer exist).
    """
    if not final_answer:
        return ["A_MISSING"], {}
    if judge_fn is None:
        return ["A_JUDGE_UNAVAILABLE"], {"judge": "no judge configured"}
    try:
        ok, jdetail = judge_fn(case, final_answer)
    except Exception as e:  # judge infra down: fail the case, never pass it
        return ["A_JUDGE_UNAVAILABLE"], {"judge_error": str(e)[:200]}
    detail = {"judge": jdetail} if jdetail else {}
    return ([], detail) if ok else (["A_WRONG"], detail)


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


INFORMATIONAL_CONDITIONS = {
    "Q_ATTESTED_VIA_ACCESS_LOG",
    "E_INDEXED_NOT_PERSISTED",
    "P_SOURCE_SET_MISMATCH",
}


def gate_case(
    case: dict,
    block: Optional[CaseBlock],
    history_queries: list[str],
    history_placeholder_calls: int,
    reissue_fn,
    reconstruction: Optional[dict] = None,
    case_source_refs: Optional[set[str]] = None,
    facts_index: Optional[list[str]] = None,
    window_persist_receipts: int = 0,
    attestation: Optional[dict] = None,
    facts_index_raw: str = "",
    presence_fn=None,
    judge_fn=None,
) -> GateResult:
    """Apply the full gate (A/Q/E/R/P/H) to one case.

    reissue_fn(query) -> dict {"count": int, "error": str|None}
    reconstruction: the reconstruct_sources.py JSON payload (a plain dict
    — run_benchmark invokes the script per case and feeds it here; the v4
    harness ALWAYS passes a payload for a present block). Mapped to gate
    conditions: each stored_fact row's conditions -> P_UNRESOLVED:
    <expr12>:<COND>; P_MISSING when no used stored fact carries any
    provenance attributes (nothing citable; unsolvable exempt); the
    handles_check conditions ride in for knowledge cases only (H_MISSING
    / H_COUNT_MISMATCH / H_MISMATCH, all blocking per D4; unsolvable
    exempt — the §2.6 triggers are knowledge-case, parallel to
    P_MISSING). None (or a
    legacy non-dict positional shape from older unit tests) = no P/H
    conditions.
    case_source_refs: the case's allowed source refs (the background
    SOURCE_URLS set); when given, any stored source ref outside it is the
    informational P_SOURCE_SET_MISMATCH (unsolvable exempt).
    facts_index: normalized expressions from the agent's facts index
    (extraction record); None = E-gate not applicable (legacy grading),
    [] = no clauses were extracted (fails every case).
    window_persist_receipts: BRIDGE-PERSIST-OK receipts in this case's
    benchmark window (E_NO_INGEST applies to the first case only: it
    must show a real ingest).
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
    presence_fn: v9 (wr3h evidence) — probe fn mapping a variable-form
    pattern to {"count": int, "error": ...} against DAS. When provided,
    every recorded index expression is probed; ones that resolve to zero
    are reported as the informational E_INDEXED_NOT_PERSISTED condition
    with per-expression detail (wr3h's failure mode: the index claimed
    ~23 persisted expressions but ~10 were never written; the agent then
    re-queried the missing atoms to deadline).
    """
    case_id = case["id"]
    conditions: list[str] = []
    detail: dict = {}

    if block is None:
        return GateResult(case_id, "FAIL", ["A_MISSING", "Q_MISSING", "P_MISSING", "R_MISSING"])

    # --- A-gate: presence + LLM-judged substance (v15b) ---
    a_conditions, judge_detail = grade_answer(case, block.final_answer, judge_fn)
    conditions.extend(a_conditions)
    detail["final_answer"] = block.final_answer
    if judge_detail:
        detail.update(judge_detail)

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
            if is_first_case and window_persist_receipts == 0:
                # After a DAS cleanup the first case MUST show a real
                # ingest: a BRIDGE-PERSIST-OK receipt in the case window.
                # Receipts ARE extractable from history windows
                # (history_parse.extract_persist_receipts,
                # history_parse.py:119-121), so no facade-log census is
                # needed (resolution 6).
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
                # v9 (wr3h evidence): presence cross-check — every recorded
                # index expression must actually resolve in DAS. wr3h
                # recorded ~23 expressions but ~10 (incl. the case-critical
                # spatial facts) were never persisted; the agent then
                # re-queried the missing atoms to deadline. Informational in
                # the gate (the discipline fix is prompt-side), but now
                # VISIBLE per expression instead of silently misleading the
                # whole run.
                if presence_fn is not None:
                    absent = []
                    for e in index:
                        probe = index_variable_form(e)
                        if probe is None:
                            continue
                        resp = presence_fn(probe)
                        if resp.get("error"):
                            continue  # probe failure is not gate evidence
                        if resp.get("count", 0) <= 0:
                            absent.append(e)
                    detail["index_absent_count"] = len(absent)
                    detail["index_absent"] = absent[:5]
                    if absent:
                        conditions.append("E_INDEXED_NOT_PERSISTED")

    # --- R-gate: MeTTa reasoning trace (campaign-grade standard, 2026-10-24
    # directive): the REASONING: line must carry the formalized reasoning
    # trace, NOT generated prose. Shape: the question clause (= the executed
    # query) first, then the fact steps used (verbatim extraction-record
    # atoms), then the derived conclusion clause — semicolon-separated
    # s-expressions. Grounding: the first step must be the executed query
    # clause (the formalized question the Q-gate re-issued against DAS);
    # middle steps must be existing atoms (verbatim in the extraction
    # record); the final step may be derived, but every quoted literal must
    # come from the extracted vocabulary (or the query). The unsolvable case
    # keeps the shape requirements (question clause + absence probes) but is
    # exempt from index grounding (no facts to ground against).
    if not block.reasoning_raw:
        conditions.append("R_MISSING")
    else:
        trace_steps, has_prose = parse_reasoning_trace(block.reasoning_raw)
        detail["trace_steps"] = len(trace_steps)
        if has_prose or len(trace_steps) < 2:
            conditions.append("R_NOT_METTA")
        else:
            query_norm = (normalize_expression(normalize_query(block.queries[0]))
                          if block.queries else None)
            # --- R_NOT_EXECUTED (scenario A/A2 lesson, 2026-10-25): the
            # reasoning must have been EXECUTED by the interpreter, not
            # hand-composed: either the extraction record carries `exec
            # <call> => <output-with-stv>` lines, or the trace itself quotes
            # an interpreter (stv ...) output. Unsolvable cases are exempt
            # (absence probes have no derivation to execute).
            exec_outputs = ([o for o in parse_exec_outputs(facts_index_raw)
                             if STV_RE.search(o)]
                            if facts_index_raw else [])
            if exec_outputs:
                detail["exec_outputs"] = len(exec_outputs)
            if not is_unsolvable:
                trace_has_stv = any(STV_RE.search(step) for step in trace_steps)
                if not (exec_outputs or trace_has_stv):
                    conditions.append("R_NOT_EXECUTED")
            ungrounded: list[str] = []
            if query_norm is not None and trace_steps[0] != query_norm:
                # the first trace step must BE the formalized question
                ungrounded.append(trace_steps[0])
            if not is_unsolvable and facts_index is not None:
                idx = [normalize_expression(e) for e in facts_index]
                idx_set = set(idx)
                # executed derivation artifacts are existing atoms (the
                # interpreter produced them; the record preserves them).
                # v17 (wr3o-20261028): the grounding set mints BOTH the
                # call side and the output side (raw + single-redundant-
                # paren-stripped) — the trace's derivation step carries
                # call AND conclusion atoms, and both must ground.
                idx_set |= exec_grounding_set(facts_index_raw)
                vocab = index_literals(idx)
                # v10: the agent's real dialect (NAL arrow syntax) uses bare
                # content symbols, not quoted literals — the derived
                # conclusion's bare symbols must come from the same stored
                # vocabulary (index + query). A fabricated conclusion needs
                # a NEW symbol; reusing stored ones is grounded derivation.
                bare_vocab = set()
                for e in idx:
                    bare_vocab |= _bare_content_symbols(e)
                if query_norm:
                    vocab |= set(query_literals(query_norm))
                    bare_vocab |= _bare_content_symbols(query_norm)
                for i, step in enumerate(trace_steps[1:], start=1):
                    if step == query_norm or step in idx_set:
                        continue  # the question clause / an existing atom
                    # v11 (wr3j evidence): atom-wise grounding for EVERY
                    # non-first trace step, not only the final one. wr3j's
                    # mid-trace steps were executed-derivation outputs the
                    # interpreter produced; the v10 i==last restriction
                    # flagged them although every atom grounds under the
                    # same literal/bare-symbol rule (v10's own final-step
                    # rule). A step without ``=>`` still parses as a single
                    # atom, so plain clauses keep the byte comparison; a
                    # fabricated mid-step still fails — its new symbol or
                    # literal is in no stored vocabulary.
                    grounded = True
                    for atom in _split_derivation_atoms(step):
                        if atom in idx_set or atom == query_norm:
                            continue
                        lits = set(query_literals(atom))
                        bare = _bare_content_symbols(atom)
                        if (lits and lits <= vocab) or (not lits and bare <= bare_vocab):
                            continue  # derived over stored vocabulary
                        grounded = False
                        break
                    if grounded:
                        continue  # every atom grounded
                    ungrounded.append(step)
            if ungrounded:
                conditions.append("R_TRACE_NOT_GROUNDED")
                detail["trace_not_grounded"] = ungrounded[:5]

    # --- P/H-gate: reconstruction-chain provenance (v17 item 4) ---
    # The reconstruction payload (reconstruct_sources.py --json, a plain
    # dict) is the gate's ONLY provenance input. Legacy callers passing
    # the retired positional citation-list shape are normalized to "no
    # payload" (the v4 harness always passes the script dict or None).
    if reconstruction is not None and not isinstance(reconstruction, dict):
        reconstruction = None
    if reconstruction is not None:
        per_expression = reconstruction.get("per_expression") or []
        seen_codes: set[str] = set()
        carries_attrs = False
        stored_refs: set[str] = set()
        for row in per_expression:
            if row.get("classification") != "stored_fact":
                # Derivation/query/exec rows are NOT mapped: a
                # derivation's conditions are the union of its stored
                # components' conditions, already emitted by those
                # components' own stored_fact rows (spec §2.4 rule (c)).
                continue
            expr12 = row.get("expr", "")[:12]
            for cond in row.get("conditions") or []:
                code = f"P_UNRESOLVED:{expr12}:{cond}"
                if code not in seen_codes:
                    seen_codes.add(code)
                    conditions.append(code)
            for src in row.get("sources") or []:
                if "NO_PROVENANCE_ATTRS" not in (src.get("conditions") or []):
                    carries_attrs = True
                if src.get("ref"):
                    stored_refs.add(src["ref"])
        if not is_unsolvable and not carries_attrs:
            # Reconstruction found no used stored facts carrying any
            # provenance attributes — nothing citable (unsolvable exempt).
            conditions.append("P_MISSING")
        # H-gate: the script's HANDLES cross-check rides in for knowledge
        # cases only (unsolvable exempt — the §2.6 triggers are
        # knowledge-case, parallel to P_MISSING; all H_* blocking, D4).
        if not is_unsolvable:
            for cond in (reconstruction.get("handles_check") or {}).get("conditions") or []:
                conditions.append(cond)
        if (not is_unsolvable and case_source_refs is not None
                and any(ref not in case_source_refs for ref in stored_refs)):
            # Informational: semantic-misattribution visibility — sources
            # attached to the case's facts fall outside its background set.
            conditions.append("P_SOURCE_SET_MISMATCH")
        detail["p_gate"] = {
            "stored_expressions": [
                row.get("expr") for row in per_expression
                if row.get("classification") == "stored_fact"
            ],
            "handles_check": reconstruction.get("handles_check") or {},
        }

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
