"""Unit tests for provenance_check.py — citation -> git repo resolution.

Uses a REAL throwaway git repo on disk (no network, no LLM) to verify the
resolution chain: commit exists -> single sources/ blob + index.jsonl ->
index entry at that commit -> sha256(blob) matches entry -> url matches.
"""
import os
import subprocess
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from provenance_check import (
    Citation,
    parse_sources_line,
    resolve_citation,
    check_citations,
)

SHA1 = "0123456789abcdef0123456789abcdef01234567"
URL1 = "https://example.com/spatial-knowledge.md"
CONTENT1 = "# spatial knowledge\n\nthe ceiling is above the observer.\n"


def _make_repo(root: str) -> str:
    """Create a provenance-style git repo with one archived source."""
    repo = os.path.join(root, "omega-provenance")
    os.makedirs(repo)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    def git(*a):
        subprocess.run(["git", "-C", repo, *a], check=True, env=env,
                       capture_output=True, text=True)
    git("init", "-q")
    # archive() layout: sources/YYYY/MM/<blob-sha>.<ext> + index.jsonl
    import hashlib
    blob_sha = hashlib.sha256(CONTENT1.encode("utf-8")).hexdigest()
    path = f"sources/2026/10/{blob_sha}.md"
    os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
    with open(os.path.join(repo, path), "w") as f:
        f.write(CONTENT1)
    import json
    entry = {"url": URL1, "blob_sha256": blob_sha, "path": path,
             "content_type": "text/markdown", "archived_at": "2026-10-22T00:00:00Z"}
    with open(os.path.join(repo, "index.jsonl"), "w") as f:
        f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
    git("add", "-A")
    git("commit", "-q", "-m", f"archive: {URL1} {blob_sha[:12]}")
    r = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                       capture_output=True, text=True, env=env)
    return repo, r.stdout.strip(), blob_sha


def test_parse_sources_line():
    line = f"SOURCES: git:{SHA1} {URL1} git:fedcba fedcba"
    # note: only 40-hex shas are treated as citations
    cits = parse_sources_line(line)
    assert cits == [Citation(sha=f"git:{SHA1}", url=URL1)]


def test_resolve_citation_ok():
    with tempfile.TemporaryDirectory() as root:
        repo, commit, _ = _make_repo(root)
        check = resolve_citation(repo, f"git:{commit}", URL1, sudo=False)
        assert check.resolved, check.conditions
        assert check.conditions == []
        assert check.detail["index_url"] == URL1


def test_resolve_citation_commit_missing():
    with tempfile.TemporaryDirectory() as root:
        repo, _, _ = _make_repo(root)
        fake = "f" * 40
        check = resolve_citation(repo, f"git:{fake}", URL1, sudo=False)
        assert not check.resolved
        assert check.conditions == ["COMMIT_NOT_IN_REPO"]


def test_resolve_citation_url_mismatch():
    with tempfile.TemporaryDirectory() as root:
        repo, commit, _ = _make_repo(root)
        check = resolve_citation(repo, f"git:{commit}",
                                 "https://other.example.com/x.md", sudo=False)
        assert not check.resolved
        assert check.conditions == ["URL_MISMATCH"]


def test_resolve_citation_tampered_blob():
    """Blob content edited after commit -> sha256 mismatch at resolution."""
    with tempfile.TemporaryDirectory() as root:
        repo, commit, blob_sha = _make_repo(root)
        import hashlib
        path = f"sources/2026/10/{blob_sha}.md"
        with open(os.path.join(repo, path), "a") as f:
            f.write("tampered\n")
        subprocess.run(
            ["git", "-C", repo, "add", "-A"], capture_output=True, text=True)
        subprocess.run(
            ["git", "-C", repo, "commit", "-q", "-m", "tamper"],
            capture_output=True, text=True,
            env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                     GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))
        # resolving the ORIGINAL commit still passes (content at that commit)
        ok = resolve_citation(repo, f"git:{commit}", URL1, sudo=False)
        assert ok.resolved, ok.conditions
        # but the tampered HEAD commit's blob no longer matches its index entry
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        bad = resolve_citation(repo, f"git:{head}", URL1, sudo=False)
        assert not bad.resolved
        assert bad.conditions == ["BLOB_SHA_MISMATCH"]


def test_check_citations_batch():
    with tempfile.TemporaryDirectory() as root:
        repo, commit, _ = _make_repo(root)
        checks = check_citations(
            [Citation(sha=f"git:{commit}", url=URL1),
             Citation(sha="git:" + "e" * 40, url=URL1)],
            repo, sudo=False)
        assert checks[0].resolved
        assert not checks[1].resolved
        assert checks[1].conditions == ["COMMIT_NOT_IN_REPO"]
