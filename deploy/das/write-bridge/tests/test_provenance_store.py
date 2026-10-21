"""ProvenanceStore: git archive semantics (unit, no network, tmp_path fixture)."""

from __future__ import annotations

import json
import subprocess

import pytest

from provenance_store import ArchiveError, ProvenanceStore


def _git(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, check=True
    ).stdout


def test_archive_creates_commit_blob_and_index(tmp_path):
    repo = str(tmp_path / "repo")
    store = ProvenanceStore(repo)
    result = store.archive("https://example.com/doc", "hello world", content_type="text/plain")
    assert result["deduped"] is False
    assert len(result["commit"]) == 40
    assert result["blob_sha256"] and result["path"].startswith("sources/")
    # The commit exists in the repo.
    log = _git(repo, "log", "--format=%H")
    assert result["commit"] in log.split()
    # The blob exists with the exact content.
    blob_path = repo + "/" + result["path"]
    assert open(blob_path).read() == "hello world"
    # The index has one line with the url.
    lines = [json.loads(l) for l in open(repo + "/index.jsonl") if l.strip()]
    assert len(lines) == 1
    assert lines[0]["url"] == "https://example.com/doc"
    assert lines[0]["blob_sha256"] == result["blob_sha256"]


def test_archive_dedupes_same_url_and_content(tmp_path):
    repo = str(tmp_path / "repo")
    store = ProvenanceStore(repo)
    first = store.archive("https://example.com/doc", "same", content_type="text/plain")
    second = store.archive("https://example.com/doc", "same", content_type="text/plain")
    assert second["deduped"] is True
    assert second["commit"] == first["commit"]
    assert second["archived_at"] == first["archived_at"]
    # Exactly one commit, one index line.
    assert len(_git(repo, "log", "--format=%H").split()) == 1


def test_archive_new_content_same_url_is_a_new_commit(tmp_path):
    repo = str(tmp_path / "repo")
    store = ProvenanceStore(repo)
    first = store.archive("https://example.com/doc", "v1", content_type="text/plain")
    second = store.archive("https://example.com/doc", "v2", content_type="text/plain")
    assert second["deduped"] is False
    assert second["commit"] != first["commit"]
    assert second["blob_sha256"] != first["blob_sha256"]


def test_archive_validation_errors(tmp_path):
    store = ProvenanceStore(str(tmp_path / "repo"))
    for url, content in [
        ("ftp://example.com", "x"),
        ("https://example.com/a b", "x"),
        ("", "x"),
        ("https://example.com", ""),
    ]:
        with pytest.raises(ArchiveError):
            store.archive(url, content)


def test_lookup_by_blob_prefix(tmp_path):
    repo = str(tmp_path / "repo")
    store = ProvenanceStore(repo)
    result = store.archive("https://example.com/doc", "content", content_type="text/plain")
    found = store.lookup(result["blob_sha256"][:12])
    assert found is not None
    assert found["url"] == "https://example.com/doc"
    assert found["commit"] == result["commit"]
    assert store.lookup("ffffffff") is None


def test_content_type_extension_mapping(tmp_path):
    repo = str(tmp_path / "repo")
    store = ProvenanceStore(repo)
    r1 = store.archive("https://a.com/x", "<html/>", content_type="text/html; charset=utf-8")
    r2 = store.archive("https://a.com/y", "{}", content_type="application/json")
    assert r1["path"].endswith(".html")
    assert r2["path"].endswith(".json")
    r3 = store.archive("https://a.com/z", "data", content_type=None)
    assert r3["path"].endswith(".txt")


# ---------------------------------------------------------------- v2.1 gate

def test_verify_commit_accepts_valid_pair(tmp_path):
    repo = str(tmp_path / "repo")
    store = ProvenanceStore(repo)
    result = store.archive("https://example.com/doc", "content", content_type="text/plain")
    citation = "git:" + result["commit"]
    verified = store.verify_commit(citation, "https://example.com/doc")
    assert verified["commit"] == result["commit"]
    assert verified["url"] == "https://example.com/doc"
    assert verified["blob_sha256"] == result["blob_sha256"]


def test_verify_commit_rejects_unknown_sha(tmp_path):
    repo = str(tmp_path / "repo")
    store = ProvenanceStore(repo)
    store.archive("https://example.com/doc", "content")
    with pytest.raises(ArchiveError) as exc:
        store.verify_commit("git:" + "f" * 40, "https://example.com/doc")
    assert "not found in the archive" in str(exc.value)
    assert "archive-source" in str(exc.value) and "retry" in str(exc.value)


def test_verify_commit_rejects_url_mismatch(tmp_path):
    repo = str(tmp_path / "repo")
    store = ProvenanceStore(repo)
    result = store.archive("https://example.com/a", "content-a")
    store.archive("https://example.com/b", "content-b")
    with pytest.raises(ArchiveError) as exc:
        store.verify_commit("git:" + result["commit"], "https://example.com/b")
    assert "archives a different source" in str(exc.value)
    assert "https://example.com/a" in str(exc.value)


def test_verify_commit_rejects_malformed_citation(tmp_path):
    repo = str(tmp_path / "repo")
    store = ProvenanceStore(repo)
    with pytest.raises(ArchiveError) as exc:
        store.verify_commit("deadbeef", "https://example.com/a")
    assert '"git:" + 40 hex' in str(exc.value)
    with pytest.raises(ArchiveError) as exc:
        store.verify_commit("git:" + "z" * 40, "https://example.com/a")
    assert '"git:" + 40 hex' in str(exc.value)


def test_verify_commit_empty_url_rejected(tmp_path):
    repo = str(tmp_path / "repo")
    store = ProvenanceStore(repo)
    result = store.archive("https://example.com/a", "content")
    with pytest.raises(ArchiveError):
        store.verify_commit("git:" + result["commit"], "")


def test_parse_archive_subject_roundtrip():
    from provenance_store import parse_archive_subject
    parsed = parse_archive_subject("archive: https://example.com/a abc123456789")
    assert parsed == ("https://example.com/a", "abc123456789")
    parsed = parse_archive_subject("archive: https://example.com/a abc123456789 (re-commit)")
    assert parsed == ("https://example.com/a", "abc123456789")
    assert parse_archive_subject("not an archive subject") is None
    assert parse_archive_subject("archive: onlyone-token") is None
    assert parse_archive_subject("archive: ") is None
