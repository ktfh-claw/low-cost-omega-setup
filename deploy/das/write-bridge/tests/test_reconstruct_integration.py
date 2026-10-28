"""reconstruct_sources.py integration tests (issue #2 Phase 4, spec §7).

Runs inside the omega-write-bridge-tests image (hyperon_das installed —
the pinned-factories branch is exercised; conftest's mirror classes carry
the identical handle formulas, so derived handles equal the live-verified
EXPECTED_HANDLES ground truth). Hermetic, no docker/no network:

- the mongo seam (``reconstruct_sources._mongo_find_links``) is
  monkeypatched with scripted mongosh outputs (only FOUND link docs get
  keys, mirroring the real seam's contract);
- the LEDGER repos are REAL temp git repositories built with
  ``LedgerStore.record`` (provenance_store — import-safe, stdlib only)
  or direct git appends for the bad-commit fixtures (the
  ``test_provenance_store.py`` ``_git`` helper pattern);
- every git call runs with ``sudo=False`` (the ``run(argv, sudo=False)``
  seam threads the sudo param, mirroring provenance_check's signature).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import EXPECTED_HANDLES, TOP_HANDLE, X402_METTA
from provenance_store import LEDGER_NAME, LedgerStore

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import reconstruct_sources as rs  # noqa: E402 (sys.path set above)

X402 = X402_METTA
OTHER = '(Evaluation (Concept "ceiling") (Concept "above-observer"))'
REF = "https://example.com/spatial-knowledge.md"
REF2 = "https://example.com/lighting.md"
SHA = "a" * 64
SHA2 = "b" * 64
CONTENT = "# spatial knowledge\n\nthe ceiling is above the observer.\n"


def _git(repo: str, *args: str) -> str:
    return subprocess.run(
        [
            "git", "-C", repo,
            "-c", "user.name=probe",
            "-c", "user.email=probe@omega.local",
            "-c", "commit.gpgsign=false",
            *args,
        ],
        capture_output=True, text=True, check=True,
    ).stdout


def _commit(repo: str, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _attrs(commit: str, ref: str = REF, sha: str = SHA) -> dict:
    return {
        "metta_expression": X402,
        "provenance_ref": ref,
        "provenance_git_commit": "git:" + commit,
        "provenance_blob_sha256": sha,
    }


def _mongo(docs: dict):
    """Scripted _mongo_find_links: only FOUND handles get keys."""
    def find(container, handles):
        return {h: docs[h] for h in handles if h in docs}
    return find


def _other_handle() -> str:
    return rs._parse_fact(OTHER, *rs._factories()).top_handle


@pytest.fixture()
def ledger_repo(tmp_path):
    """A real LedgerStore-built ledger repo with two recorded entries."""
    store = LedgerStore(str(tmp_path / "ledger"))
    first = store.record(REF, SHA)
    second = store.record(REF2, SHA2)
    repo = str(tmp_path / "ledger")
    return repo, first, second


def _run(argv, monkeypatch, docs=None, mongo=None):
    """In-process CLI run (sudo=False); returns (rc, stdout, stderr)."""
    monkeypatch.setattr(
        rs, "_mongo_find_links", mongo if mongo is not None else _mongo(docs or {}))
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = rs.run(argv, sudo=False)
    return rc, out.getvalue(), err.getvalue()


def _run_json(tmp_path, argv, monkeypatch, docs=None, mongo=None):
    out_path = tmp_path / "out.json"
    rc, stdout, stderr = _run(
        list(argv) + ["--json", str(out_path)], monkeypatch,
        docs=docs, mongo=mongo)
    payload = json.loads(out_path.read_text()) if out_path.exists() else None
    return rc, payload, stdout, stderr


# --------------------------------------------------------------- handles


def test_handles_via_pinned_factories_match_groundtruth():
    node_cls, link_cls = rs._factories()
    assert (node_cls, link_cls) != (rs._FallbackNode, rs._FallbackLink)
    fact = rs._parse_fact(X402, node_cls, link_cls)
    assert fact.handles == EXPECTED_HANDLES
    assert fact.top_handle == TOP_HANDLE


# ------------------------------------------------------------ happy path


def test_happy_path_all_resolved(tmp_path, monkeypatch, ledger_repo):
    repo, first, _ = ledger_repo
    docs = {TOP_HANDLE: _attrs(first["commit"]), _other_handle(): _attrs(
        first["commit"], ref=REF, sha=SHA)}
    trace = f'(match &self (Inheritance $X (Concept "payment-protocol")));{X402};{OTHER}'
    rc, payload, stdout, stderr = _run_json(
        tmp_path,
        ["--trace", trace, "--ledger-repo", repo,
         "--facts", f"{X402};{OTHER}", "--handles", f"{TOP_HANDLE} {_other_handle()}",
         "--case", "original", "--source-paths-out", str(tmp_path / "paths.txt")],
        monkeypatch, docs=docs)
    assert rc == 0, stderr
    rows = payload["per_expression"]
    assert [r["classification"] for r in rows] == [
        "query_clause", "stored_fact", "stored_fact"]
    assert rows[1]["top_handle"] == TOP_HANDLE
    assert rows[1]["stored"] is True
    source = rows[1]["sources"][0]
    assert source == {
        "commit": first["commit"], "ref": REF, "sha256": SHA,
        "entry_date": first["entry_date"], "resolved": True, "legacy": False,
        "conditions": [], "background_file": None, "background_match": None,
    }
    assert rows[2]["sources"][0]["ref"] == REF
    assert payload["per_predicate"] == {
        "Inheritance": {"expressions": [X402],
                        "sources": [source]},
        "Evaluation": {"expressions": [OTHER],
                       "sources": [rows[2]["sources"][0]]},
    }
    assert payload["source_paths"] == [REF]
    assert (tmp_path / "paths.txt").read_text() == REF + "\n"
    assert payload["handles_check"]["conditions"] == []
    assert payload["missing"] == [] and payload["conditions"] == []
    assert payload["case"] == "original"
    assert "verdict: PASS (exit 0" in stdout


def test_stored_link_without_attrs_fails(tmp_path, monkeypatch, ledger_repo):
    repo, _, _ = ledger_repo
    rc, payload, _, stderr = _run_json(
        tmp_path,
        ["--trace", X402, "--ledger-repo", repo],
        monkeypatch, docs={TOP_HANDLE: None})
    assert rc == 2, stderr
    row = payload["per_expression"][0]
    assert row["classification"] == "stored_fact"
    assert row["conditions"] == ["NO_PROVENANCE_ATTRS"]
    assert payload["conditions"] == ["NO_PROVENANCE_ATTRS"]
    assert payload["missing"] == [X402]


def test_fabricated_handle_h_mismatch_exit_unaffected(tmp_path, monkeypatch, ledger_repo):
    repo, first, _ = ledger_repo
    rc, payload, _, stderr = _run_json(
        tmp_path,
        ["--trace", X402, "--ledger-repo", repo,
         "--facts", X402, "--handles", "f" * 32],
        monkeypatch, docs={TOP_HANDLE: _attrs(first["commit"])})
    assert rc == 0, stderr  # sources resolve -> exit code unaffected (D4)
    hc = payload["handles_check"]
    assert hc["conditions"] == ["H_MISMATCH"]
    assert hc["claimed"] == ["f" * 32]
    assert hc["derived"] == [TOP_HANDLE]


def test_h_missing_and_count_mismatch(tmp_path, monkeypatch, ledger_repo):
    repo, first, _ = ledger_repo
    docs = {TOP_HANDLE: _attrs(first["commit"])}
    rc, payload, _, _ = _run_json(
        tmp_path,
        ["--trace", X402, "--ledger-repo", repo, "--facts", X402],
        monkeypatch, docs=docs)
    assert rc == 0
    assert payload["handles_check"]["conditions"] == ["H_MISSING"]
    rc, payload, _, _ = _run_json(
        tmp_path,
        ["--trace", X402, "--ledger-repo", repo,
         "--facts", f"{X402};{OTHER}", "--handles", TOP_HANDLE],
        monkeypatch, docs=docs)
    assert rc == 0
    assert payload["handles_check"]["conditions"] == ["H_COUNT_MISMATCH"]


# --------------------------------------------------------- classification


def test_query_clause_and_unstored_exempt(tmp_path, monkeypatch, ledger_repo):
    repo, first, _ = ledger_repo
    trace = (f'(match &self (Inheritance $X (Concept "payment-protocol")));'
             f'(Inheritance $Y (Concept "unwritten"));'
             f'{X402};'
             f'(Similarity (Concept "never-written"))')
    rc, payload, _, stderr = _run_json(
        tmp_path, ["--trace", trace, "--ledger-repo", repo], monkeypatch,
        docs={TOP_HANDLE: _attrs(first["commit"])})
    assert rc == 0, stderr
    kinds = [r["classification"] for r in payload["per_expression"]]
    assert kinds == ["query_clause", "variable", "stored_fact", "unstored"]
    for row in payload["per_expression"][:2] + payload["per_expression"][3:]:
        assert row["sources"] == [] and row["conditions"] == []
    assert payload["missing"] == []


def test_derivation_sources_from_component_atoms(tmp_path, monkeypatch, ledger_repo):
    repo, first, second = ledger_repo
    premise1 = X402
    premise2 = '(Inheritance (Concept "payment-protocol") (Concept "internet-money"))'
    conclusion = '(Inheritance (Concept "x402") (Concept "internet-money"))'
    step = f"{premise1} {premise2} => {conclusion}"
    prem2_handle = rs._parse_fact(premise2, *rs._factories()).top_handle
    docs = {
        TOP_HANDLE: _attrs(first["commit"]),
        prem2_handle: _attrs(second["commit"], ref=REF2, sha=SHA2),
    }
    rc, payload, _, stderr = _run_json(
        tmp_path, ["--trace", step, "--ledger-repo", repo], monkeypatch, docs=docs)
    assert rc == 0, stderr
    row = payload["per_expression"][0]
    assert row["classification"] == "derivation"
    assert row["top_handle"] is None
    assert row["stored"] is True
    assert len(row["sources"]) == 2  # union of the stored components' sources
    assert {s["ref"] for s in row["sources"]} == {REF, REF2}
    # the => output atom is not in db.links -> not independently required
    assert payload["missing"] == [] and payload["conditions"] == []
    assert payload["per_predicate"]["Inheritance"]["expressions"] == [premise1, premise2]
    assert payload["source_paths"] == [REF, REF2]


def test_per_predicate_leading_symbol_grouping(tmp_path, monkeypatch, ledger_repo):
    repo, first, _ = ledger_repo
    docs = {TOP_HANDLE: _attrs(first["commit"]), _other_handle(): _attrs(first["commit"])}
    rc, payload, _, _ = _run_json(
        tmp_path, ["--trace", f"{X402};{OTHER}", "--ledger-repo", repo],
        monkeypatch, docs=docs)
    assert rc == 0
    assert list(payload["per_predicate"]) == ["Inheritance", "Evaluation"]
    assert payload["per_predicate"]["Inheritance"]["expressions"] == [X402]
    assert payload["per_predicate"]["Evaluation"]["expressions"] == [OTHER]


# --------------------------------------------------------- ledger conditions


def test_commit_not_in_repo(tmp_path, monkeypatch, ledger_repo):
    repo, _, _ = ledger_repo
    rc, payload, _, _ = _run_json(
        tmp_path, ["--trace", X402, "--ledger-repo", repo],
        monkeypatch, docs={TOP_HANDLE: _attrs("f" * 40)})
    assert rc == 2
    assert payload["conditions"] == ["COMMIT_NOT_IN_REPO"]


def test_commit_touches_other_files(tmp_path, monkeypatch, ledger_repo):
    repo, first, _ = ledger_repo
    entry = {"ref": REF2, "sha256": SHA2, "entry_date": "2026-10-28T00:00:01Z"}
    with open(os.path.join(repo, LEDGER_NAME), "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    lines = lines[:-1] + ["," + json.dumps(entry, separators=(",", ":"))] + [lines[-1]]
    with open(os.path.join(repo, LEDGER_NAME), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(repo, "NOTES.txt"), "w", encoding="utf-8") as f:
        f.write("note\n")
    other = _commit(repo, "ledger entry plus a rogue file")
    rc, payload, _, _ = _run_json(
        tmp_path, ["--trace", X402, "--ledger-repo", repo],
        monkeypatch, docs={TOP_HANDLE: _attrs(other, ref=REF2, sha=SHA2)})
    assert rc == 2
    assert payload["conditions"] == ["COMMIT_TOUCHES_OTHER_FILES"]


def test_commit_adds_not_one_line(tmp_path, monkeypatch):
    repo = str(tmp_path / "two")
    store = LedgerStore(repo)
    store.ensure_repo()
    elements = [
        json.dumps({"ref": REF, "sha256": SHA, "entry_date": "2026-10-28T00:00:00Z"},
                   separators=(",", ":")),
        json.dumps({"ref": REF2, "sha256": SHA2, "entry_date": "2026-10-28T00:00:01Z"},
                   separators=(",", ":")),
    ]
    with open(os.path.join(repo, LEDGER_NAME), "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    lines = lines[:-1] + ["," + e for e in elements] + [lines[-1]]
    with open(os.path.join(repo, LEDGER_NAME), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    two = _commit(repo, "two entries in one commit")
    rc, payload, _, _ = _run_json(
        tmp_path, ["--trace", X402, "--ledger-repo", repo],
        monkeypatch, docs={TOP_HANDLE: _attrs(two)})
    assert rc == 2
    assert payload["conditions"] == ["COMMIT_ADDS_NOT_ONE_LINE"]
    # the init commit adds no entry-shaped line either
    init = _git(repo, "log", "--format=%H", "--reverse").splitlines()[0].strip()
    rc, payload, _, _ = _run_json(
        tmp_path, ["--trace", X402, "--ledger-repo", repo],
        monkeypatch, docs={TOP_HANDLE: _attrs(init)})
    assert rc == 2
    assert payload["conditions"] == ["COMMIT_ADDS_NOT_ONE_LINE"]


def test_ref_sha_mismatch(tmp_path, monkeypatch, ledger_repo):
    repo, first, _ = ledger_repo
    rc, payload, _, _ = _run_json(
        tmp_path, ["--trace", X402, "--ledger-repo", repo],
        monkeypatch, docs={TOP_HANDLE: _attrs(
            first["commit"], ref="https://other.example.com/x.md")})
    assert rc == 2
    assert payload["conditions"] == ["REF_SHA_MISMATCH"]


# ------------------------------------------------------------------ legacy


def _make_legacy_repo(root: str, url: str, content: str) -> tuple[str, str, str]:
    repo = os.path.join(root, "legacy")
    os.makedirs(repo)
    _git(repo, "init", "--quiet")
    blob_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    path = f"sources/2026/10/{blob_sha}.md"
    os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
    with open(os.path.join(repo, path), "w", encoding="utf-8") as f:
        f.write(content)
    entry = {"url": url, "blob_sha256": blob_sha, "path": path,
             "content_type": "text/markdown", "archived_at": "2026-10-22T00:00:00Z"}
    with open(os.path.join(repo, "index.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
    commit = _commit(repo, f"archive: {url} {blob_sha[:12]}")
    return repo, commit, blob_sha


def test_legacy_repo_resolution_informational(tmp_path, monkeypatch):
    url = "https://example.com/legacy-doc.md"
    content = "# legacy doc\n"
    store = LedgerStore(str(tmp_path / "ledger"))
    store.ensure_repo()
    legacy_repo, legacy_commit, blob_sha = _make_legacy_repo(str(tmp_path), url, content)
    docs = {TOP_HANDLE: _attrs(legacy_commit, ref=url, sha=blob_sha)}
    rc, payload, _, stderr = _run_json(
        tmp_path,
        ["--trace", X402, "--ledger-repo", str(tmp_path / "ledger"),
         "--legacy-repo", legacy_repo],
        monkeypatch, docs=docs)
    assert rc == 0, stderr  # informational — never blocking
    source = payload["per_expression"][0]["sources"][0]
    assert source["resolved"] is True
    assert source["legacy"] is True
    assert source["ref"] == url
    assert source["sha256"] == blob_sha
    assert payload["conditions"] == [] and payload["missing"] == []


def test_legacy_no_attrs_informational(tmp_path, monkeypatch, ledger_repo):
    repo, _, _ = ledger_repo
    legacy_repo, _, _ = _make_legacy_repo(str(tmp_path), REF, CONTENT)
    rc, payload, _, stderr = _run_json(
        tmp_path,
        ["--trace", X402, "--ledger-repo", repo, "--legacy-repo", legacy_repo],
        monkeypatch, docs={TOP_HANDLE: None})
    assert rc == 0, stderr
    source = payload["per_expression"][0]["sources"][0]
    assert source["legacy"] is True
    assert source["conditions"] == ["NO_PROVENANCE_ATTRS"]
    assert payload["conditions"] == [] and payload["missing"] == []


# ---------------------------------------------------------- background-dir


def test_background_dir_match_mismatch_skip(tmp_path, monkeypatch):
    # a real content hash: the ledger entry must match the background bytes
    real_sha = hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
    store = LedgerStore(str(tmp_path / "ledger"))
    recorded = store.record(REF, real_sha)
    repo = str(tmp_path / "ledger")
    bg = tmp_path / "bg"
    bg.mkdir()
    (bg / "spatial-knowledge.md").write_text(CONTENT, encoding="utf-8")
    docs = {TOP_HANDLE: _attrs(recorded["commit"], sha=real_sha)}
    rc, payload, _, _ = _run_json(
        tmp_path,
        ["--trace", X402, "--ledger-repo", repo, "--background-dir", str(bg)],
        monkeypatch, docs=docs)
    assert rc == 0
    source = payload["per_expression"][0]["sources"][0]
    assert source["background_file"] == str(bg / "spatial-knowledge.md")
    assert source["background_match"] is True
    # mismatched bytes -> content drift -> REF_SHA_MISMATCH, exit 2
    (bg / "spatial-knowledge.md").write_text(CONTENT + "tampered\n", encoding="utf-8")
    rc, payload, _, _ = _run_json(
        tmp_path,
        ["--trace", X402, "--ledger-repo", repo, "--background-dir", str(bg)],
        monkeypatch, docs=docs)
    assert rc == 2
    source = payload["per_expression"][0]["sources"][0]
    assert source["background_match"] is False
    assert payload["conditions"] == ["REF_SHA_MISMATCH"]
    assert payload["source_paths"] == []
    # missing background file -> check skipped, no condition invented
    os.remove(bg / "spatial-knowledge.md")
    rc, payload, _, _ = _run_json(
        tmp_path,
        ["--trace", X402, "--ledger-repo", repo, "--background-dir", str(bg)],
        monkeypatch, docs=docs)
    assert rc == 0
    source = payload["per_expression"][0]["sources"][0]
    assert source["background_file"] is None
    assert source["background_match"] is None
    assert payload["source_paths"] == [REF]


# ------------------------------------------------------- outputs & exit 1


def test_json_shape_and_determinism(tmp_path, monkeypatch, ledger_repo):
    repo, first, _ = ledger_repo
    argv = ["--trace", X402, "--ledger-repo", repo,
            "--facts", X402, "--handles", TOP_HANDLE]
    docs = {TOP_HANDLE: _attrs(first["commit"])}
    out1, out2 = tmp_path / "a.json", tmp_path / "b.json"
    rc1, _, _ = _run(argv + ["--json", str(out1)], monkeypatch, docs=docs)
    rc2, _, _ = _run(argv + ["--json", str(out2)], monkeypatch, docs=docs)
    assert (rc1, rc2) == (0, 0)
    assert out1.read_bytes() == out2.read_bytes()
    payload = json.loads(out1.read_text())
    assert set(payload) == {
        "per_expression", "per_predicate", "handles_check",
        "missing", "conditions", "source_paths"}


def test_mongo_seam_raising_exits_1(tmp_path, monkeypatch, ledger_repo):
    repo, _, _ = ledger_repo
    def boom(container, handles):
        raise rs.MongoError("mongo unreachable: docker exec failed")
    rc, _, stderr = _run(
        ["--trace", X402, "--ledger-repo", repo], monkeypatch, mongo=boom)
    assert rc == 1
    assert "mongo unreachable" in stderr


def test_ledger_repo_missing_exits_1(tmp_path, monkeypatch):
    rc, _, stderr = _run(
        ["--trace", X402, "--ledger-repo", str(tmp_path / "no-such-repo")],
        monkeypatch)
    assert rc == 1
    assert "ledger unreadable" in stderr


def test_trace_unparseable_exits_1(tmp_path, monkeypatch, ledger_repo):
    repo, _, _ = ledger_repo
    rc, _, stderr = _run(
        ["--trace", "(match &self $X);plain prose segment", "--ledger-repo", repo],
        monkeypatch)
    assert rc == 1
    assert "trace unparseable" in stderr and "prose segment" in stderr


@pytest.mark.parametrize("argv", [
    ["--ledger-repo", "/tmp/x"],
    ["--ledger-repo", "/tmp/x", "--trace", X402, "--trace-file", "f"],
])
def test_usage_errors_exit_1(argv, monkeypatch):
    rc, _, stderr = _run(argv, monkeypatch)
    assert rc == 1
    assert "usage error" in stderr


def test_unknown_flag_usage_error(monkeypatch):
    rc, _, stderr = _run(["--trace", X402, "--ledger-repo", "/tmp/x", "--bogus"],
                         monkeypatch)
    assert rc == 1
    assert "usage error" in stderr


def test_empty_trace_vacuous_pass(tmp_path, monkeypatch, ledger_repo):
    repo, _, _ = ledger_repo
    rc, payload, _, _ = _run_json(
        tmp_path, ["--trace", "", "--ledger-repo", repo], monkeypatch)
    assert rc == 0
    assert payload["per_expression"] == []
    assert payload["conditions"] == [] and payload["missing"] == []
