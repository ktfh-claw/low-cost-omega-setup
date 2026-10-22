"""Provenance citation -> git repo resolution for the gating test.

The agent's answers must cite sources as ``git:<40 hex> <url>`` pairs. A
citation RESOLVES iff, in the provenance git repo:

  1. the commit exists (``git cat-file -e <sha>^{commit}``),
  2. the commit adds exactly one ``sources/...`` blob plus ``index.jsonl``,
  3. the ``index.jsonl`` AT THAT COMMIT contains an entry whose ``path``
     matches the added blob,
  4. sha256(blob content at that commit) == entry.blob_sha256,
  5. entry.url == cited url.

This mirrors the write-time ``verify_commit`` in the bridge facade
(provenance_store.py) but is fully read-only so the grader can run it any
time without touching the agent or the DAS.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field

INDEX_NAME = "index.jsonl"


@dataclass
class Citation:
    sha: str = ""
    url: str = ""


@dataclass
class CitationCheck:
    sha: str
    url: str
    resolved: bool = False
    conditions: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def parse_sources_line(line: str) -> list[Citation]:
    """Parse a SOURCES line: ``git:<40hex> <url>`` pairs (space separated)."""
    citations: list[Citation] = []
    tokens = line.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("git:") and len(tok) == 44:
            url = tokens[i + 1] if i + 1 < len(tokens) and not tokens[i + 1].startswith("git:") else ""
            citations.append(Citation(sha=tok, url=url))
            i += 2 if url else 1
        else:
            i += 1
    return citations


def _git(repo: str, *args: str, sudo: bool = True, timeout: float = 30.0) -> subprocess.CompletedProcess:
    cmd = (["sudo"] if sudo else []) + [
        "git", "-c", f"safe.directory={repo}", "-C", repo, "--no-pager",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _run_ok(result: subprocess.CompletedProcess) -> bool:
    return result.returncode == 0


def resolve_citation(repo: str, sha: str, url: str, sudo: bool = True) -> CitationCheck:
    """Resolve one git:<sha> citation against the provenance repo."""
    check = CitationCheck(sha=sha, url=url)
    short = sha[4:]

    # 1. commit exists
    if not _run_ok(_git(repo, "cat-file", "-e", f"{short}^{{commit}}", sudo=sudo)):
        check.conditions.append("COMMIT_NOT_IN_REPO")
        return check

    # 2. files changed by the commit
    show = _git(repo, "show", "--name-only", "--format=", short, sudo=sudo)
    if not _run_ok(show):
        check.conditions.append("COMMIT_UNREADABLE")
        return check
    files = [f for f in show.stdout.split("\n") if f.strip()]
    src_files = [f for f in files if f.startswith("sources/")]
    if not src_files:
        check.conditions.append("COMMIT_NOT_AN_ARCHIVE_COMMIT")
        check.detail["files"] = files
        return check
    if len(src_files) != 1:
        check.conditions.append("COMMIT_MULTIPLE_SOURCE_BLOBS")
        return check
    blob_path = src_files[0]

    # 3. index.jsonl at that commit: entry with path == blob_path
    idx = _git(repo, "show", f"{short}:{INDEX_NAME}", sudo=sudo)
    if not _run_ok(idx):
        check.conditions.append("INDEX_UNREADABLE_AT_COMMIT")
        return check
    entry = None
    for line in idx.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            cand = json.loads(line)
        except ValueError:
            continue
        if cand.get("path") == blob_path:
            entry = cand
            break
    if entry is None:
        check.conditions.append("INDEX_ENTRY_MISSING_FOR_BLOB")
        return check

    # 4. blob content hash matches index entry (tamper detector — checked
    #    BEFORE the archive-shape check so an edited blob reports
    #    BLOB_SHA_MISMATCH even if index.jsonl wasn't part of the edit)
    blob = _git(repo, "show", f"{short}:{blob_path}", sudo=sudo)
    if not _run_ok(blob):
        check.conditions.append("BLOB_UNREADABLE_AT_COMMIT")
        return check
    blob_sha = hashlib.sha256(blob.stdout.encode("utf-8")).hexdigest()
    if blob_sha != entry.get("blob_sha256"):
        check.conditions.append("BLOB_SHA_MISMATCH")
        return check

    # 5. the commit must be an archive commit (index.jsonl among its changes)
    if INDEX_NAME not in files:
        check.conditions.append("COMMIT_NOT_AN_ARCHIVE_COMMIT")
        check.detail["files"] = files
        return check

    # 6. cited url matches index entry url
    if url and entry.get("url") != url:
        check.conditions.append("URL_MISMATCH")
        return check

    check.resolved = True
    check.detail = {
        "path": blob_path,
        "index_url": entry.get("url", ""),
        "blob_sha256": blob_sha,
        "archived_at": entry.get("archived_at", ""),
    }
    return check


def check_citations(citations: list[Citation], repo: str, sudo: bool = True) -> list[CitationCheck]:
    """Resolve a list of citations; returns per-citation checks."""
    return [resolve_citation(repo, c.sha, c.url, sudo=sudo) for c in citations]
