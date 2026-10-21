"""history.metta trace extraction for the windowless-room benchmark.

Parses the agent's history.metta (PeTTa-format skill invocation log) to
extract das-retrieve queries, add-atom persists, and archive-source calls
with timestamps. Tolerant of malformed lines; counts skips.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class HistoryEvent:
    """A single event extracted from history.metta."""
    kind: str  # "das_retrieve" | "add_atom" | "archive_source"
    query: Optional[str] = None
    expression: Optional[str] = None
    url: Optional[str] = None
    sha: Optional[str] = None
    timestamp: Optional[str] = None
    raw: Optional[str] = None


def _find_metta_string(line: str) -> Optional[str]:
    """Find the metta query/expression string in a line (quoted, starts with '(')."""
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', line):
        content = m.group(1)
        if content.startswith("("):
            return content
    return None


def _find_expression_after(line: str, marker: str = "&persistent") -> Optional[str]:
    """Find the first balanced s-expression after a marker (for add-atom)."""
    idx = line.find(marker)
    if idx == -1:
        return None
    start = line.find("(", idx + len(marker))
    if start == -1:
        return None
    depth = 0
    i = start
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            i += 2  # skip escaped char
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return line[start : i + 1]
        i += 1
    return None


def _find_url(line: str) -> Optional[str]:
    """Find a URL in a line."""
    for m in re.finditer(r'"(https?://[^"]+)"', line):
        return m.group(1)
    return None


def load_history(path: str) -> list[HistoryEvent]:
    """Load history.metta and extract events."""
    events: list[HistoryEvent] = []
    skipped = 0

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (OSError, IOError):
        return []

    lines = content.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # das-retrieve events
        if "das-retrieve" in line or "das_retrieve" in line:
            query = _find_metta_string(line)
            if query:
                events.append(
                    HistoryEvent(kind="das_retrieve", query=query, raw=line)
                )
            else:
                skipped += 1
            continue

        # add-atom events
        if "add-atom" in line or "add_atom" in line:
            expr = _find_expression_after(line)
            if not expr:
                expr = _find_metta_string(line)
            if expr:
                events.append(
                    HistoryEvent(kind="add_atom", expression=expr, raw=line)
                )
            else:
                skipped += 1
            continue

        # archive-source events
        if "archive-source" in line or "archive_source" in line:
            url = _find_url(line)
            if url:
                events.append(
                    HistoryEvent(kind="archive_source", url=url, raw=line)
                )
            else:
                skipped += 1
            continue

        # Not a recognized event; skip
        skipped += 1

    return events


def slice_window(
    events: list[HistoryEvent], start_iso: str, end_iso: str
) -> list[HistoryEvent]:
    """Return events within the benchmark run window [start_iso, end_iso]."""
    windowed: list[HistoryEvent] = []
    for event in events:
        if event.timestamp and start_iso <= event.timestamp <= end_iso:
            windowed.append(event)
    return windowed


def summarize(events: list[HistoryEvent]) -> dict:
    """Summarize events by kind, listing written metta expressions,
    archive shas, and das-retrieve queries."""
    counts: dict[str, int] = {}
    written_expressions: list[str] = []
    archive_shas: list[str] = []
    das_queries: list[str] = []

    for event in events:
        counts[event.kind] = counts.get(event.kind, 0) + 1
        if event.kind == "add_atom" and event.expression:
            written_expressions.append(event.expression)
        elif event.kind == "archive_source" and event.url:
            archive_shas.append(event.url)
        elif event.kind == "das_retrieve" and event.query:
            das_queries.append(event.query)

    return {
        "counts": counts,
        "written_expressions": written_expressions,
        "archive_shas": archive_shas,
        "das_queries": das_queries,
    }
