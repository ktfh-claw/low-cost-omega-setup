#!/usr/bin/env python3
# websearch.py overlay (provenance campaign, 2026-10-21).
#
# WHY THIS OVERLAY EXISTS: the stock skill formats results as
# "(TITLE: ... SNIPPET: ...)" and DROPS THE URL — the root cause of the
# URL-level provenance gap (nothing downstream could reconstruct WHERE a
# fact came from). This overlay keeps the stock module interface
# (search(query, max_results) -> str) and adds the URL to every result so
# the agent can archive sources at research time via (archive-source ...)
# and cite them in DAS writes via the v2 provenance suffix.
#
# Deployed by bind-mounting over /PeTTa/repos/Omega/src/websearch.py
# (read-only) — the same overlay pattern as the das-read skill file; see
# deploy/omega/start.sh.

from ddgs import DDGS

try:
    from src.logger import get_logger
except ModuleNotFoundError:  # imported directly with src/ on the path
    from logger import get_logger

logger = get_logger(__name__)


def search_(query, max_results=10):
    with DDGS() as ddgs:
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in ddgs.text(query, max_results=max_results)
        ]


def search(query, max_results=10):
    try:
        ret = "("
        for r in search_(query):
            ret += "(TITLE: " + r["title"] + " URL: " + r["url"] + " SNIPPET: " + r["snippet"] + ") "
        ret += ")"
        return ret
    except Exception as e:
        logger.exception(f"Web search failed for query {query!r}: {e}")
        return ""
