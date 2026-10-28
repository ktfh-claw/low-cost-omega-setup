"""migrate_ledger_repo.sh --check: verification-only ledger repo format checks.

Real git repositories under tmp_path (subprocess, no network): the checks
mirror the Phase 3 helper contract — spec §6 test strategy + decision D6
(the helper never mutates anything).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "migrate_ledger_repo.sh"
LEDGER = "SOURCE-LEDGER.json"

REF_A = "https://example.com/a.md"
SHA_A = "a" * 64
ENTRY_DATE = "2026-10-28T00:00:00Z"
ENTRY_A = {"ref": REF_A, "sha256": SHA_A, "entry_date": ENTRY_DATE}


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


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _init_repo(repo_dir: Path, ledger_name: str = LEDGER) -> str:
    repo_dir.mkdir(parents=True)
    repo = str(repo_dir)
    _git(repo, "init", "--quiet")
    (repo_dir / ledger_name).write_text("[\n]\n", encoding="utf-8")
    _commit(repo, "ledger: init")
    return repo


def _commit(repo: str, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _add_entry(repo: str, entry: dict, ledger_name: str = LEDGER) -> str:
    """Append one element line before ``]`` (leading-comma form) + commit."""
    ledger = Path(repo) / ledger_name
    lines = ledger.read_text(encoding="utf-8").splitlines()
    has_elements = any(
        line.startswith(("{", ",{")) for line in lines[:-1]
    )
    prefix = "" if not has_elements else ","
    element = json.dumps(entry, separators=(",", ":"))
    lines.insert(len(lines) - 1, prefix + element)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _commit(repo, "ledger: entry")


# ------------------------------------------------------------------- checks


@pytest.mark.parametrize("argv", [[], ["--check"]])
def test_check_happy_path(tmp_path, argv):
    repo = _init_repo(tmp_path / "repo")
    _add_entry(repo, ENTRY_A)
    proc = _run(*argv, "--repo", repo)
    assert proc.returncode == 0
    assert "FAIL" not in proc.stdout
    assert "PASS: HEAD touches only SOURCE-LEDGER.json" in proc.stdout
    assert f"OK: ledger repo format verified: {repo} ({LEDGER})" in proc.stdout


def test_check_init_only_repo(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    proc = _run("--repo", repo)
    assert proc.returncode == 0
    assert "PASS: HEAD is the ledger: init commit" in proc.stdout
    assert "FAIL" not in proc.stdout


def test_check_allows_empty_tree_commit(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = str(repo_dir)
    _git(repo, "init", "--quiet")
    _git(repo, "commit", "--quiet", "--allow-empty", "-m", "bootstrap")
    (repo_dir / LEDGER).write_text("[\n]\n", encoding="utf-8")
    proc = _run("--repo", repo)
    assert proc.returncode == 0
    assert "PASS: HEAD is an empty-tree commit (init allowed)" in proc.stdout


def test_check_rejects_repo_without_commits(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = str(repo_dir)
    _git(repo, "init", "--quiet")
    proc = _run("--repo", repo)
    assert proc.returncode == 1
    assert "FAIL: no HEAD commit" in proc.stdout


def test_check_rejects_head_touching_other_file(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _add_entry(repo, ENTRY_A)
    (Path(repo) / "NOTES.txt").write_text("note\n", encoding="utf-8")
    _commit(repo, "notes only")
    proc = _run("--repo", repo)
    assert proc.returncode == 1
    assert "FAIL: HEAD commit touches files other than SOURCE-LEDGER.json" in proc.stdout


def test_check_rejects_head_touching_ledger_and_other_file(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _add_entry(repo, ENTRY_A)
    (Path(repo) / "NOTES.txt").write_text("note\n", encoding="utf-8")
    _add_entry(repo, {"ref": "https://example.com/b.md", "sha256": "b" * 64, "entry_date": ENTRY_DATE})
    proc = _run("--repo", repo)
    assert proc.returncode == 1
    assert "FAIL: HEAD commit touches files other than SOURCE-LEDGER.json" in proc.stdout


def test_check_rejects_non_list_json(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (Path(repo) / LEDGER).write_text(
        json.dumps({"ref": REF_A, "sha256": SHA_A, "entry_date": ENTRY_DATE}) + "\n",
        encoding="utf-8",
    )
    _commit(repo, "not a list")
    proc = _run("--repo", repo)
    assert proc.returncode == 1
    assert "FAIL: SOURCE-LEDGER.json must exist and json.load to a list" in proc.stdout


def test_check_rejects_element_missing_key(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _add_entry(repo, {"ref": REF_A, "sha256": SHA_A})
    proc = _run("--repo", repo)
    assert proc.returncode == 1
    assert "FAIL: entries must be objects with exactly ref/sha256/entry_date" in proc.stdout
    assert "missing: entry_date" in proc.stdout


def test_check_rejects_element_extra_key(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _add_entry(repo, {**ENTRY_A, "note": "extra"})
    proc = _run("--repo", repo)
    assert proc.returncode == 1
    assert "unexpected: note" in proc.stdout


@pytest.mark.parametrize(
    "sha256",
    [
        "A" * 64,
        "a" * 63,
        "a" * 65,
        "z" * 64,
        123,
    ],
)
def test_check_rejects_bad_sha256(tmp_path, sha256):
    repo = _init_repo(tmp_path / "repo")
    _add_entry(repo, {"ref": REF_A, "sha256": sha256, "entry_date": ENTRY_DATE})
    proc = _run("--repo", repo)
    assert proc.returncode == 1
    assert "sha256 is not 64 lowercase hex characters" in proc.stdout


def test_check_rejects_empty_entry_date(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _add_entry(repo, {"ref": REF_A, "sha256": SHA_A, "entry_date": ""})
    proc = _run("--repo", repo)
    assert proc.returncode == 1
    assert "entry_date must be a non-empty string" in proc.stdout


def test_check_rejects_missing_repo(tmp_path):
    proc = _run("--repo", str(tmp_path / "no-such-repo"))
    assert proc.returncode == 1
    assert f"FAIL: repo directory does not exist: {tmp_path / 'no-such-repo'}" in proc.stdout


def test_check_alternate_ledger_file_name(tmp_path):
    repo = _init_repo(tmp_path / "repo", ledger_name="MY-LEDGER.json")
    _add_entry(repo, ENTRY_A, ledger_name="MY-LEDGER.json")
    default = _run("--repo", repo)
    assert default.returncode == 1
    proc = _run("--repo", repo, "--file", "MY-LEDGER.json")
    assert proc.returncode == 0
    assert f"OK: ledger repo format verified: {repo} (MY-LEDGER.json)" in proc.stdout


def test_help(tmp_path):
    proc = _run("--help")
    assert proc.returncode == 0
    assert "Usage: migrate_ledger_repo.sh" in proc.stdout
    assert "--check" in proc.stdout
    assert "ledger_repo_format" in proc.stdout


@pytest.mark.parametrize(
    "argv",
    [
        ["--bogus"],
        ["positional"],
        ["--repo"],
        ["--file"],
    ],
)
def test_usage_error(argv):
    proc = _run(*argv)
    assert proc.returncode == 2
    assert "Usage: migrate_ledger_repo.sh" in proc.stderr
