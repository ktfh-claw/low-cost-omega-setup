"""LedgerStore: git source-ledger semantics (unit, no network, tmp_path)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading

import pytest

from provenance_store import ArchiveError, LedgerStore, LEDGER_NAME

REF_A = "https://example.com/a.md"
REF_B = "https://example.com/b.md"
REF_C = "https://example.com/c.md"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
ENTRY_DATE_RE = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"


def _git(repo: str, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            repo,
            "-c",
            "user.name=probe",
            "-c",
            "user.email=probe@omega.local",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _ledger_path(repo: str) -> str:
    return os.path.join(repo, LEDGER_NAME)


def _commit_count(repo: str) -> int:
    return int(_git(repo, "rev-list", "--count", "HEAD").strip())


def _commit_subject(repo: str, sha: str) -> str:
    return _git(repo, "log", "-1", "--format=%s", sha).strip()


def _manual_commit(repo: str, message: str) -> str:
    _git(repo, "commit", "--quiet", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _append_manual_lines(repo: str, elements: list[str]) -> str:
    """Rewrite the ledger adding ``elements`` (with leading commas) in one commit."""
    with open(_ledger_path(repo), "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    new_lines = lines[:-1] + ["," + element for element in elements] + [lines[-1]]
    with open(_ledger_path(repo), "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")
    _git(repo, "add", "--", LEDGER_NAME)
    return _manual_commit(repo, "manual entries")


# ------------------------------------------------------------------ init


def test_ensure_repo_fresh_init(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    store.ensure_repo()
    with open(_ledger_path(repo)) as f:
        assert f.read() == "[\n]\n"
    assert json.load(open(_ledger_path(repo))) == []
    assert _commit_count(repo) == 1
    assert _commit_subject(repo, "HEAD") == "ledger: init"
    # Idempotent: no second init, no second commit.
    store.ensure_repo()
    assert _commit_count(repo) == 1


# ----------------------------------------------------------------- record


def test_record_appends_one_entry_line(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    result = store.record(REF_A, SHA_A)
    assert result["deduped"] is False
    assert re.fullmatch(r"[0-9a-f]{40}", result["commit"])
    assert re.fullmatch(ENTRY_DATE_RE, result["entry_date"])
    element = json.dumps(
        {"ref": REF_A, "sha256": SHA_A, "entry_date": result["entry_date"]},
        separators=(",", ":"),
    )
    with open(_ledger_path(repo)) as f:
        assert f.read().splitlines() == ["[", element, "]"]
    assert json.load(open(_ledger_path(repo))) == [
        {"ref": REF_A, "sha256": SHA_A, "entry_date": result["entry_date"]}
    ]
    # The entry commit adds exactly ONE line (pure +1-line diff).
    numstat = _git(
        repo, "diff", result["commit"] + "~1", result["commit"], "--numstat"
    ).split()
    assert numstat == ["1", "0", LEDGER_NAME]
    assert _commit_subject(repo, result["commit"]) == f"ledger: {SHA_A[:12]} {REF_A[:96]}"


def test_record_leading_comma_for_second_entry(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    first = store.record(REF_A, SHA_A)
    second = store.record(REF_B, SHA_B)
    with open(_ledger_path(repo)) as f:
        lines = f.read().splitlines()
    assert lines[0] == "["
    assert lines[1].startswith("{")
    assert lines[2].startswith(",{")
    assert lines[3] == "]"
    assert json.load(open(_ledger_path(repo))) == [
        {"ref": REF_A, "sha256": SHA_A, "entry_date": first["entry_date"]},
        {"ref": REF_B, "sha256": SHA_B, "entry_date": second["entry_date"]},
    ]
    numstat = _git(
        repo, "diff", second["commit"] + "~1", second["commit"], "--numstat"
    ).split()
    assert numstat == ["1", "0", LEDGER_NAME]


def test_record_accepts_absolute_path_ref(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    result = store.record("/var/lib/sources/doc.md", SHA_A)
    assert result["deduped"] is False
    assert json.load(open(_ledger_path(repo)))[0]["ref"] == "/var/lib/sources/doc.md"


def test_record_dedup_returns_original_commit(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    first = store.record(REF_A, SHA_A)
    store.record(REF_B, SHA_B)
    again = store.record(REF_A, SHA_A)
    assert again["deduped"] is True
    assert again["commit"] == first["commit"]
    assert again["entry_date"] == first["entry_date"]
    # No file change, no new commit: init + 2 entries.
    assert _commit_count(repo) == 3
    with open(_ledger_path(repo)) as f:
        lines = f.read().splitlines()
    assert len(lines) == 4  # [ + two elements + ]


def test_record_same_ref_new_sha_is_new_entry(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    first = store.record(REF_A, SHA_A)
    second = store.record(REF_A, SHA_B)
    assert second["deduped"] is False
    assert second["commit"] != first["commit"]
    assert _commit_count(repo) == 3
    entries = json.load(open(_ledger_path(repo)))
    assert [(e["ref"], e["sha256"]) for e in entries] == [
        (REF_A, SHA_A),
        (REF_A, SHA_B),
    ]


# ------------------------------------------------------------- verification


def test_verify_commit_valid_pair(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    recorded = store.record(REF_A, SHA_A)
    verified = store.verify_commit("git:" + recorded["commit"], REF_A, SHA_A)
    assert verified == {
        "commit": recorded["commit"],
        "ref": REF_A,
        "sha256": SHA_A,
        "entry_date": recorded["entry_date"],
    }


def test_verify_commit_unknown_sha(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    store.record(REF_A, SHA_A)
    with pytest.raises(ArchiveError) as exc:
        store.verify_commit("git:" + "f" * 40, REF_A, SHA_A)
    assert "not found in the ledger" in str(exc.value)
    assert "write the source first via the skill" in str(exc.value)


def test_verify_commit_rejects_commit_touching_other_files(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    store.record(REF_A, SHA_A)
    with open(os.path.join(repo, "NOTES.txt"), "w") as f:
        f.write("note\n")
    _git(repo, "add", "NOTES.txt")
    other = _manual_commit(repo, "touch another file")
    with pytest.raises(ArchiveError) as exc:
        store.verify_commit("git:" + other, REF_A, SHA_A)
    assert "is not a ledger commit (touching only SOURCE-LEDGER.json)" in str(exc.value)


def test_verify_commit_rejects_commit_adding_two_entries(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    store.record(REF_A, SHA_A)
    two = _append_manual_lines(
        repo,
        [
            json.dumps(
                {"ref": REF_B, "sha256": SHA_B, "entry_date": "2026-10-27T00:00:00Z"},
                separators=(",", ":"),
            ),
            json.dumps(
                {"ref": REF_C, "sha256": SHA_C, "entry_date": "2026-10-27T00:00:01Z"},
                separators=(",", ":"),
            ),
        ],
    )
    with pytest.raises(ArchiveError) as exc:
        store.verify_commit("git:" + two, REF_B, SHA_B)
    assert "does not add the cited source entry" in str(exc.value)


def test_verify_commit_rejects_ref_sha_mismatch(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    recorded = store.record(REF_A, SHA_A)
    for ref, sha in ((REF_B, SHA_A), (REF_A, SHA_B), (REF_B, SHA_B)):
        with pytest.raises(ArchiveError) as exc:
            store.verify_commit("git:" + recorded["commit"], ref, sha)
        assert "does not add the cited source entry" in str(exc.value)
        assert "re-run the skill write" in str(exc.value)


def test_verify_commit_rejects_init_commit(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    store.ensure_repo()
    init = _git(repo, "rev-parse", "HEAD").strip()
    store.record(REF_A, SHA_A)
    with pytest.raises(ArchiveError) as exc:
        store.verify_commit("git:" + init, REF_A, SHA_A)
    assert "does not add the cited source entry" in str(exc.value)


@pytest.mark.parametrize(
    "citation",
    ["deadbeef", "git:" + "z" * 40, "git:" + "a" * 39, "git:" + "a" * 41, None, 123],
)
def test_verify_commit_malformed_citation(tmp_path, citation):
    store = LedgerStore(str(tmp_path / "repo"))
    with pytest.raises(ArchiveError) as exc:
        store.verify_commit(citation, REF_A, SHA_A)
    assert 'must be "git:" + 40 hex chars' in str(exc.value)


# ----------------------------------------------------------------- locking


def test_concurrent_records_serialize(tmp_path):
    repo = str(tmp_path / "repo")
    store = LedgerStore(repo)
    results: dict[str, dict] = {}
    errors: list[Exception] = []

    def worker(name: str, ref: str, sha256: str) -> None:
        try:
            results[name] = store.record(ref, sha256)
        except Exception as exc:  # pragma: no cover - surfaced by assert below
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("a", REF_A, SHA_A)),
        threading.Thread(target=worker, args=("b", REF_B, SHA_B)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    assert results["a"]["deduped"] is False
    assert results["b"]["deduped"] is False
    assert results["a"]["commit"] != results["b"]["commit"]
    # init + exactly two entry commits; the ledger stays valid JSON.
    assert _commit_count(repo) == 3
    entries = json.load(open(_ledger_path(repo)))
    assert sorted((e["ref"], e["sha256"]) for e in entries) == [
        (REF_A, SHA_A),
        (REF_B, SHA_B),
    ]
    # Each entry commit adds exactly one line.
    for name in ("a", "b"):
        numstat = _git(
            repo,
            "diff",
            results[name]["commit"] + "~1",
            results[name]["commit"],
            "--numstat",
        ).split()
        assert numstat == ["1", "0", LEDGER_NAME]


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "ref, message",
    [
        ("", "ref must be a non-empty string of at most 480 characters"),
        ("x" * 481, "ref must be a non-empty string of at most 480 characters"),
        (123, "ref must be a non-empty string of at most 480 characters"),
        ("https://example.com/a b", "ref must not contain whitespace"),
        ("   ", "ref must not contain whitespace"),
        ("ftp://example.com/doc", "ref must be an http(s) URL or an absolute path"),
        ("relative/path", "ref must be an http(s) URL or an absolute path"),
        ("http://", "ref must be an http(s) URL or an absolute path"),
    ],
)
def test_record_ref_validation_errors(tmp_path, ref, message):
    store = LedgerStore(str(tmp_path / "repo"))
    with pytest.raises(ArchiveError) as exc:
        store.record(ref, SHA_A)
    assert str(exc.value) == message


@pytest.mark.parametrize(
    "sha256",
    ["A" * 64, "a" * 63, "a" * 65, "z" * 64, "", 123, None],
)
def test_record_sha256_validation_errors(tmp_path, sha256):
    store = LedgerStore(str(tmp_path / "repo"))
    with pytest.raises(ArchiveError) as exc:
        store.record(REF_A, sha256)
    assert str(exc.value) == "sha256 must be 64 lowercase hex characters"
