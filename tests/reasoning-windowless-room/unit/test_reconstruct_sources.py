"""Unit tests for reconstruct_sources.py (issue #2 Phase 4, spec §7).

Stdlib-only shim (no pytest — plain asserts, test_* functions,
auto-discovered by unit/run_tests.py). This host has NO hyperon_das, so
the script's mirror-fallback atom classes are the path exercised here;
their handle formulas are asserted against the pinned client's
live-verified values (conftest.py EXPECTED_HANDLES / iter16).

Hermetic: the mongo seam (_mongo_find_links) is stubbed in-process (only
FOUND link docs are returned, mirroring the real seam's contract); the
ledger/legacy repos are REAL throwaway git repositories on disk (no
network, no docker), driven with sudo=False exactly like
test_provenance_check.py's fixtures.
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = REPO_ROOT / "deploy" / "das" / "write-bridge" / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import reconstruct_sources as rs  # noqa: E402 (sys.path set above)

LEDGER = "SOURCE-LEDGER.json"

X402 = '(Inheritance (Concept "x402") (Concept "payment-protocol"))'
TOP_HANDLE = "67293e82ab2162d2d9d5a1578670f678"
SYMBOL_INHERITANCE_HANDLE = "9028a696c1b6d3d9ff8c4f496da77378"
INNER_X402_HANDLE = "454f6502e71d6f7e1c52b1e4f308cb15"

REF = "https://example.com/spatial-knowledge.md"
CONTENT = "# spatial knowledge\n\nthe ceiling is above the observer.\n"
SHA = hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
ENTRY_DATE = "2026-10-28T09:00:00Z"

GIT_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="t",
    GIT_AUTHOR_EMAIL="t@t",
    GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@t",
)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args], check=True, env=GIT_ENV,
        capture_output=True, text=True,
    ).stdout


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _make_ledger_repo(root, entries):
    """A fresh-format ledger repo: init commit + one commit per entry."""
    repo = os.path.join(root, "ledger")
    os.makedirs(repo)
    _git(repo, "init", "-q")
    with open(os.path.join(repo, LEDGER), "w") as f:
        f.write("[\n]\n")
    _commit(repo, "ledger: init")
    commits = []
    lines = ["[", "]"]
    for i, entry in enumerate(entries):
        prefix = "" if i == 0 else ","
        lines = lines[:-1] + [prefix + json.dumps(entry, separators=(",", ":"))] + [lines[-1]]
        with open(os.path.join(repo, LEDGER), "w") as f:
            f.write("\n".join(lines) + "\n")
        commits.append(_commit(repo, "ledger: entry"))
    return repo, commits


def _ledger_entry(ref=REF, sha=SHA, entry_date=ENTRY_DATE):
    return {"ref": ref, "sha256": sha, "entry_date": entry_date}


def _make_legacy_repo(root, url, content):
    """A pre-migration repo: sources/ blob + index.jsonl (legacy format)."""
    repo = os.path.join(root, "legacy")
    os.makedirs(repo)
    _git(repo, "init", "-q")
    blob_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    path = f"sources/2026/10/{blob_sha}.md"
    os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
    with open(os.path.join(repo, path), "w") as f:
        f.write(content)
    entry = {
        "url": url,
        "blob_sha256": blob_sha,
        "path": path,
        "content_type": "text/markdown",
        "archived_at": "2026-10-22T00:00:00Z",
    }
    with open(os.path.join(repo, "index.jsonl"), "w") as f:
        f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
    commit = _commit(repo, f"archive: {url} {blob_sha[:12]}")
    return repo, commit, blob_sha


def _attrs(commit, ref=REF, sha=SHA):
    return {
        "metta_expression": X402,
        "provenance_ref": ref,
        "provenance_git_commit": "git:" + commit,
        "provenance_blob_sha256": sha,
    }


def _scripted_mongo(docs):
    """Fake _mongo_find_links: only FOUND handles get keys (real-seam contract)."""
    def find(container, handles):
        return {h: docs[h] for h in handles if h in docs}
    return find


def _run_cli(argv, mongo=None):
    """Run the script in-process (sudo=False); returns (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old = rs._mongo_find_links
    rs._mongo_find_links = mongo if mongo is not None else (lambda c, hs: {})
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = rs.run(argv, sudo=False)
    finally:
        rs._mongo_find_links = old
    return rc, out.getvalue(), err.getvalue()


def _run_case(argv, mongo=None):
    """Run with a temp --json output; returns (rc, payload, stderr)."""
    with tempfile.TemporaryDirectory() as root:
        out_path = os.path.join(root, "out.json")
        rc, _, err = _run_cli(argv + ["--json", out_path], mongo=mongo)
        payload = json.load(open(out_path)) if os.path.exists(out_path) else None
        return rc, payload, err


# ------------------------------------------------------- mirror handle formulas


def test_fallback_handles_match_pinned_formulas():
    node_cls, link_cls = rs._factories()
    assert (node_cls, link_cls) == (rs._FallbackNode, rs._FallbackLink)
    node = node_cls(type="Symbol", name="Inheritance")
    assert node.handle == hashlib.md5(b"Symbol Inheritance").hexdigest()
    assert node.handle == SYMBOL_INHERITANCE_HANDLE
    link = link_cls(type="Expression", targets=[
        SYMBOL_INHERITANCE_HANDLE, INNER_X402_HANDLE, "42f691261c2ee66fb6fbc72096185de0",
    ])
    assert link.handle == hashlib.md5(
        " ".join([
            hashlib.md5(b"Expression").hexdigest(),
            SYMBOL_INHERITANCE_HANDLE, INNER_X402_HANDLE, "42f691261c2ee66fb6fbc72096185de0",
        ]).encode()
    ).hexdigest()
    fact = rs._parse_fact(X402, node_cls, link_cls)
    assert fact.top_handle == TOP_HANDLE  # live-verified pinned-client value
    assert fact.handles == [
        "9028a696c1b6d3d9ff8c4f496da77378",
        "5e50ef7542bb0fde52aed0d841335790",
        "e2f6cbeea42509ef822009139fedfeda",
        "454f6502e71d6f7e1c52b1e4f308cb15",
        "3837420c25c1ce0c66ea8c9688f7e267",
        "42f691261c2ee66fb6fbc72096185de0",
        TOP_HANDLE,
    ]


# --------------------------------------------------------------- CLI usage


def test_cli_requires_exactly_one_trace_arg():
    for argv in (
        ["--ledger-repo", "/tmp/x"],
        ["--ledger-repo", "/tmp/x", "--trace", X402, "--trace-file", "f.txt"],
    ):
        rc, _, err = _run_cli(argv)
        assert rc == 1, (argv, rc)
        assert "usage error" in err and "--trace" in err


def test_cli_missing_ledger_repo_flag_exits_1():
    rc, _, err = _run_cli(["--trace", X402])
    assert rc == 1
    assert "usage error" in err


def test_cli_unknown_flag_exits_1():
    rc, _, err = _run_cli(["--trace", X402, "--ledger-repo", "/tmp/x", "--bogus"])
    assert rc == 1
    assert "usage error" in err


def test_ledger_repo_dir_missing_exits_1():
    with tempfile.TemporaryDirectory() as root:
        rc, _, err = _run_cli(
            ["--trace", X402, "--ledger-repo", os.path.join(root, "no-such-repo")])
        assert rc == 1
        assert "ledger unreadable" in err


def test_trace_unparseable_exits_1():
    # A parenthesized segment whose CONTENT fails parse_fact — the preserved
    # harness-error shape (with prose-skip, non-parenthesized segments are
    # prose: skipped, recorded in prose_segments, never an error).
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        bad = '((A) (B))'
        rc, _, err = _run_cli(["--trace", bad, "--ledger-repo", repo])
        assert rc == 1
        assert "trace unparseable" in err
        assert "'((A) (B))'" in err  # names the offending segment


def test_mongo_seam_raising_exits_1():
    def boom(container, handles):
        raise rs.MongoError("mongo unreachable: docker exec failed")
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        rc, _, err = _run_cli(
            ["--trace", X402, "--ledger-repo", repo], mongo=boom)
        assert rc == 1
        assert "mongo unreachable" in err


# ----------------------------------------------------------- classification


def test_empty_trace_is_vacuous_pass():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(["--trace", "", "--ledger-repo", repo])
        assert rc == 0
        assert payload["per_expression"] == []
        assert payload["missing"] == []
        assert payload["conditions"] == []
        assert "case" not in payload


def test_query_clause_first_variable_step_exempt():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        trace = f'(match &self (Inheritance $X (Concept "payment-protocol")));{X402}'
        rc, payload, _ = _run_case(
            ["--trace", trace, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(_commit_of(root, repo))}),
        )
        assert rc == 0
        first = payload["per_expression"][0]
        assert first["classification"] == "query_clause"
        assert first["top_handle"] is None and first["sources"] == []
        assert first["stored"] is False


def _commit_of(root, repo):
    """The single ledger entry commit of a one-entry repo."""
    return _git(repo, "log", "--format=%H", "--reverse").splitlines()[-1].strip()


def test_variable_non_first_step_exempt():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        trace = f'(match &self (Inheritance $X (Concept "y")));(Inheritance $A (Concept "y"))'
        rc, payload, _ = _run_case(["--trace", trace, "--ledger-repo", repo])
        assert rc == 0
        assert [r["classification"] for r in payload["per_expression"]] == [
            "query_clause", "variable"]


def test_unstored_ground_step_exempt():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo], mongo=_scripted_mongo({}))
        assert rc == 0
        row = payload["per_expression"][0]
        assert row["classification"] == "unstored"
        assert row["stored"] is False
        assert row["top_handle"] == TOP_HANDLE
        assert row["sources"] == [] and row["conditions"] == []
        assert payload["missing"] == [] and payload["conditions"] == []


def test_happy_path_stored_fact_resolves():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo, "--case", "original"],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        row = payload["per_expression"][0]
        assert row == {
            "expr": X402,
            "top_handle": TOP_HANDLE,
            "stored": True,
            "classification": "stored_fact",
            "sources": [{
                "commit": commits[0],
                "ref": REF,
                "sha256": SHA,
                "entry_date": ENTRY_DATE,
                "resolved": True,
                "legacy": False,
                "conditions": [],
                "background_file": None,
                "background_match": None,
            }],
            "conditions": [],
        }
        assert payload["per_predicate"] == {
            "Inheritance": {
                "expressions": [X402],
                "sources": row["sources"],
            }
        }
        assert payload["source_paths"] == [REF]
        assert payload["case"] == "original"


def test_derivation_sources_are_component_atoms_sources():
    # grading._split_derivation_atoms convention: a step containing "=>" splits
    # into its top-level component atoms (left side + right side). Here the
    # two premises ARE component atoms (stored, cited); the => output atom is
    # NOT in db.links -> not independently required.
    premise1 = '(Inheritance (Concept "x402") (Concept "payment-protocol"))'
    premise2 = '(Inheritance (Concept "payment-protocol") (Concept "internet-money"))'
    conclusion = '(Inheritance (Concept "x402") (Concept "internet-money"))'
    step = f"{premise1} {premise2} => {conclusion}"
    prem1_handle = TOP_HANDLE
    prem2_handle = rs._parse_fact(premise2, *rs._factories()).top_handle
    out_handle = rs._parse_fact(conclusion, *rs._factories()).top_handle
    with tempfile.TemporaryDirectory() as root:
        # two DISTINCT ledger entries -> the union has two sources; (same
        # citation on both premises would union to one — cache-deduped)
        repo, commits = _make_ledger_repo(root, [
            _ledger_entry(),
            _ledger_entry(ref="https://example.com/second.md", sha="b" * 64,
                          entry_date="2026-10-28T09:00:01Z"),
        ])
        attrs1 = _attrs(commits[0])
        attrs2 = _attrs(commits[1], ref="https://example.com/second.md", sha="b" * 64)
        mongo = _scripted_mongo({prem1_handle: attrs1, prem2_handle: attrs2})
        trace = f"(match &self (Inheritance $X (Concept \"internet-money\")));{step}"
        rc, payload, _ = _run_case(["--trace", trace, "--ledger-repo", repo], mongo=mongo)
        assert rc == 0
        derivation = payload["per_expression"][1]
        assert derivation["classification"] == "derivation"
        assert derivation["top_handle"] is None
        assert derivation["stored"] is True  # components found in db.links
        assert len(derivation["sources"]) == 2  # union of stored components' sources
        assert all(s["resolved"] for s in derivation["sources"])
        assert out_handle not in mongo(None, [out_handle])  # output not stored
        assert payload["per_predicate"]["Inheritance"]["expressions"] == [premise1, premise2]
        assert payload["source_paths"] == [REF, "https://example.com/second.md"]
        assert payload["missing"] == []
        # the executed-call shape: (--> a b) => c has the CALL as its component
        # atom; call and output both unstored -> derivation exempt, exit 0.
        call_step = (f"(--> {premise1} {premise2}) => {conclusion}")
        trace2 = f"(match &self (Inheritance $X (Concept \"internet-money\")));{call_step}"
        rc2, payload2, _ = _run_case(
            ["--trace", trace2, "--ledger-repo", repo], mongo=mongo)
        assert rc2 == 0
        assert payload2["per_expression"][1]["sources"] == []


# ------------------------------------------------------------ ledger chain


def test_stored_link_without_attrs_blocks():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: None}),
        )
        assert rc == 2
        row = payload["per_expression"][0]
        assert row["classification"] == "stored_fact"
        assert row["conditions"] == ["NO_PROVENANCE_ATTRS"]
        assert payload["conditions"] == ["NO_PROVENANCE_ATTRS"]
        assert payload["missing"] == [X402]


def test_stored_link_with_metta_only_attrs_blocks():
    attrs = {"metta_expression": X402}  # v1 (suffix-less) write: no provenance keys
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: attrs}),
        )
        assert rc == 2
        assert payload["conditions"] == ["NO_PROVENANCE_ATTRS"]


def test_commit_not_in_repo_blocks():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs("f" * 40)}),
        )
        assert rc == 2
        assert payload["conditions"] == ["COMMIT_NOT_IN_REPO"]
        assert payload["missing"] == [X402]


def test_commit_touches_other_files_blocks():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        entry = _ledger_entry(ref="https://example.com/other.md", sha="b" * 64)
        with open(os.path.join(repo, LEDGER)) as f:
            lines = f.read().splitlines()
        lines = lines[:-1] + ["," + json.dumps(entry, separators=(",", ":"))] + [lines[-1]]
        with open(os.path.join(repo, LEDGER), "w") as f:
            f.write("\n".join(lines) + "\n")
        with open(os.path.join(repo, "NOTES.txt"), "w") as f:
            f.write("note\n")
        other = _commit(repo, "ledger entry plus a rogue note")
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(other, ref=entry["ref"], sha=entry["sha256"])}),
        )
        assert rc == 2
        assert payload["conditions"] == ["COMMIT_TOUCHES_OTHER_FILES"]
        assert commits  # (fixture sanity)


def test_commit_adds_not_one_line_blocks():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [])
        elements = [
            _ledger_entry(ref="https://example.com/a.md", sha="a" * 64),
            _ledger_entry(ref="https://example.com/b.md", sha="b" * 64),
        ]
        with open(os.path.join(repo, LEDGER)) as f:
            lines = f.read().splitlines()
        added = ["," + json.dumps(e, separators=(",", ":")) for e in elements]
        lines = lines[:-1] + added + [lines[-1]]
        with open(os.path.join(repo, LEDGER), "w") as f:
            f.write("\n".join(lines) + "\n")
        two = _commit(repo, "two entries in one commit")
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(
                two, ref="https://example.com/a.md", sha="a" * 64)}),
        )
        assert rc == 2
        assert payload["conditions"] == ["COMMIT_ADDS_NOT_ONE_LINE"]


def test_init_commit_adds_no_entry_line_blocks():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        init = _git(repo, "log", "--format=%H", "--reverse").splitlines()[0].strip()
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(init)}),
        )
        assert rc == 2
        assert payload["conditions"] == ["COMMIT_ADDS_NOT_ONE_LINE"]


def test_entry_parse_failed_blocks():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [])
        with open(os.path.join(repo, LEDGER)) as f:
            lines = f.read().splitlines()
        bad = '{"ref": "https://example.com/a.md", "sha256": "not-hex", "entry_date": "x"}'
        lines = lines[:-1] + [bad] + [lines[-1]]
        with open(os.path.join(repo, LEDGER), "w") as f:
            f.write("\n".join(lines) + "\n")
        bad_commit = _commit(repo, "one line, invalid entry shape")
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(bad_commit)}),
        )
        assert rc == 2
        assert payload["conditions"] == ["ENTRY_PARSE_FAILED"]


def test_ref_sha_mismatch_blocks():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(
                commits[0], ref="https://other.example.com/x.md")}),
        )
        assert rc == 2
        assert payload["conditions"] == ["REF_SHA_MISMATCH"]


def test_ledger_chain_caches_identical_triples():
    """Two trace steps citing the same fact share one resolution (determinism)."""
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        trace = f"{X402};{X402}"
        rc, payload, _ = _run_case(
            ["--trace", trace, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        assert [r["classification"] for r in payload["per_expression"]] == [
            "stored_fact", "stored_fact"]
        assert payload["source_paths"] == [REF]  # deduped
        # per_predicate groups stored EXPRESSIONS (deduped — a fact is a fact;
        # both trace occurrences stay visible in per_expression)
        assert payload["per_predicate"]["Inheritance"]["expressions"] == [X402]


# ------------------------------------------------------------ legacy (D6)


def test_legacy_resolution_is_informational_only():
    url = "https://example.com/legacy-doc.md"
    content = "# legacy doc\n"
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [])
        legacy_repo, legacy_commit, blob_sha = _make_legacy_repo(root, url, content)
        attrs = _attrs(legacy_commit, ref=url, sha=blob_sha)
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo, "--legacy-repo", legacy_repo],
            mongo=_scripted_mongo({TOP_HANDLE: attrs}),
        )
        assert rc == 0  # resolved via legacy -> informational, never blocking
        source = payload["per_expression"][0]["sources"][0]
        assert source["resolved"] is True
        assert source["legacy"] is True
        assert source["ref"] == url
        assert source["sha256"] == blob_sha
        assert source["entry_date"] == "2026-10-22T00:00:00Z"
        assert payload["conditions"] == [] and payload["missing"] == []


def test_legacy_failing_leaves_ledger_condition_blocking():
    url = "https://example.com/legacy-doc.md"
    content = "# legacy doc\n"
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [])
        legacy_repo, _, _ = _make_legacy_repo(root, url, content)
        # cite a commit that is in NEITHER repo
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo, "--legacy-repo", legacy_repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs("f" * 40)}),
        )
        assert rc == 2
        assert payload["conditions"] == ["COMMIT_NOT_IN_REPO"]


def test_no_provenance_attrs_with_legacy_repo_is_informational():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        legacy_repo, _, _ = _make_legacy_repo(root, REF, CONTENT)
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo, "--legacy-repo", legacy_repo],
            mongo=_scripted_mongo({TOP_HANDLE: None}),
        )
        assert rc == 0  # pre-migration atoms: informational, never blocking
        source = payload["per_expression"][0]["sources"][0]
        assert source["legacy"] is True
        assert source["conditions"] == ["NO_PROVENANCE_ATTRS"]
        assert payload["conditions"] == [] and payload["missing"] == []


# ------------------------------------------------------------ background-dir


def test_background_match():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        bg = os.path.join(root, "bg")
        os.makedirs(bg)
        with open(os.path.join(bg, "spatial-knowledge.md"), "w") as f:
            f.write(CONTENT)
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo, "--background-dir", bg],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        source = payload["per_expression"][0]["sources"][0]
        assert source["background_file"] == os.path.join(bg, "spatial-knowledge.md")
        assert source["background_match"] is True


def test_background_mismatch_is_content_drift():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        bg = os.path.join(root, "bg")
        os.makedirs(bg)
        with open(os.path.join(bg, "spatial-knowledge.md"), "w") as f:
            f.write(CONTENT + "tampered\n")
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo, "--background-dir", bg],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 2
        source = payload["per_expression"][0]["sources"][0]
        assert source["background_match"] is False
        assert source["resolved"] is False
        assert payload["conditions"] == ["REF_SHA_MISMATCH"]
        assert payload["source_paths"] == []  # unresolved -> no path


def test_background_file_missing_skips_check():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        bg = os.path.join(root, "bg")
        os.makedirs(bg)  # no spatial-knowledge.md inside
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo, "--background-dir", bg],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0  # no condition invented for a skipped check
        source = payload["per_expression"][0]["sources"][0]
        assert source["background_file"] is None
        assert source["background_match"] is None
        assert payload["source_paths"] == [REF]  # falls back to the ref itself


# ------------------------------------------------------------- H cross-check


def test_h_missing():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo, "--facts", X402],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0  # H_* never affects the exit code (D4)
        assert payload["handles_check"]["conditions"] == ["H_MISSING"]
        assert payload["handles_check"]["derived"] == [TOP_HANDLE]


def test_h_count_mismatch():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        other = '(Inheritance (Concept "x402") (Concept "money"))'
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo,
             "--facts", f"{X402};{other}", "--handles", TOP_HANDLE],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        assert payload["handles_check"]["conditions"] == ["H_COUNT_MISMATCH"]


def test_h_mismatch_fabricated_handle():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        fabricated = "f" * 32
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo,
             "--facts", X402, "--handles", fabricated],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0  # sources resolve -> exit code unaffected
        hc = payload["handles_check"]
        assert hc["conditions"] == ["H_MISMATCH"]
        assert hc["claimed"] == [fabricated]
        assert hc["derived"] == [TOP_HANDLE]


def test_h_mismatch_on_unparseable_facts_expr():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo,
             "--facts", "(broken", "--handles", TOP_HANDLE],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        hc = payload["handles_check"]
        assert hc["derived"] == [None]
        assert hc["conditions"] == ["H_MISMATCH"]


def test_handles_check_clean_when_aligned():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo,
             "--facts", X402, "--handles", TOP_HANDLE],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        assert payload["handles_check"] == {
            "claimed": [TOP_HANDLE], "derived": [TOP_HANDLE], "conditions": []}


# -------------------------------------------------------- outputs & determinism


def test_source_paths_out_file():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        bg = os.path.join(root, "bg")
        os.makedirs(bg)
        with open(os.path.join(bg, "spatial-knowledge.md"), "w") as f:
            f.write(CONTENT)
        paths_out = os.path.join(root, "paths.txt")
        rc, _, _ = _run_cli(
            ["--trace", X402, "--ledger-repo", repo, "--background-dir", bg,
             "--source-paths-out", paths_out],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        with open(paths_out) as f:
            assert f.read().splitlines() == [os.path.join(bg, "spatial-knowledge.md")]


def test_source_paths_out_empty_when_nothing_resolved():
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        paths_out = os.path.join(root, "paths.txt")
        rc, _, _ = _run_cli(
            ["--trace", X402, "--ledger-repo", repo, "--source-paths-out", paths_out],
            mongo=_scripted_mongo({TOP_HANDLE: None}),
        )
        assert rc == 2
        with open(paths_out) as f:
            assert f.read() == ""


def test_json_shape_and_determinism():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        trace = (f'(match &self (Inheritance $X (Concept "payment-protocol")));{X402};'
                 f'(Evaluation (Concept "not-written"))')
        base = ["--trace", trace, "--ledger-repo", repo,
                "--facts", X402, "--handles", TOP_HANDLE]
        mongo = _scripted_mongo({TOP_HANDLE: _attrs(commits[0])})
        out1, out2 = os.path.join(root, "a.json"), os.path.join(root, "b.json")
        rc1, _, _ = _run_cli(base + ["--json", out1], mongo=mongo)
        rc2, _, _ = _run_cli(base + ["--json", out2], mongo=mongo)
        assert (rc1, rc2) == (0, 0)
        assert open(out1, "rb").read() == open(out2, "rb").read()
        payload = json.load(open(out1))
        assert set(payload) == {
            "per_expression", "per_predicate", "handles_check",
            "missing", "conditions", "source_paths", "prose_segments"}
        assert set(payload["per_expression"][1]) == {
            "expr", "top_handle", "stored", "classification", "sources", "conditions"}
        assert set(payload["handles_check"]) == {"claimed", "derived", "conditions"}
        assert set(payload["per_predicate"]["Inheritance"]) == {
            "expressions", "sources"}
        assert [r["classification"] for r in payload["per_expression"]] == [
            "query_clause", "stored_fact", "unstored"]


def test_human_summary_on_stdout():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        rc, stdout, _ = _run_cli(
            ["--trace", X402, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        assert "stored_fact OK" in stdout
        assert "verdict: PASS (exit 0" in stdout
        rc, stdout, _ = _run_cli(
            ["--trace", X402, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: None}),
        )
        assert rc == 2
        assert "NO_PROVENANCE_ATTRS" in stdout
        assert "verdict: FAIL (exit 2" in stdout


def test_case_key_only_when_given():
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, _ = _run_case(
            ["--trace", X402, "--ledger-repo", repo, "--case", "k1"],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0 and payload["case"] == "k1"


# -------------------------------------------------------- stv/prose tolerances


def test_stv_trailing_step_stripped():
    # The interpreter's canonical output pairs the expression with its
    # executed truth value: `<X402> (stv 1.0 0.81)`. The stripped expr must
    # classify as a fact and derive the SAME handle as the clean fact.
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        trace = f"{X402} (stv 1.0 0.81)"
        rc, payload, _ = _run_case(
            ["--trace", trace, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        row = payload["per_expression"][0]
        assert row["classification"] == "stored_fact"
        assert row["expr"] == X402
        assert row["top_handle"] == TOP_HANDLE
        assert payload["missing"] == []


def test_stv_wrapped_step_stripped():
    # The interpreter's canonical wrapped output: `((<expr>) (stv s c))`.
    # The stripped expr must classify as a fact and derive the SAME handle
    # as the clean fact.
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        trace = f"({X402} (stv 1.0 0.9))"
        rc, payload, _ = _run_case(
            ["--trace", trace, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        row = payload["per_expression"][0]
        assert row["classification"] == "stored_fact"
        assert row["expr"] == X402
        assert row["top_handle"] == TOP_HANDLE
        assert payload["missing"] == []


def test_stv_trailing_derivation_component():
    # A derivation component arriving as the wrapped stv shape: the right
    # side of `=>` reaches _split_derivation_atoms via the wrapped form.
    # The stripped component exprs must derive clean handles.
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        premise1 = X402
        premise2 = '(Inheritance (Concept "payment-protocol") (Concept "internet-money"))'
        premise2_handle = rs._parse_fact(
            premise2, *rs._factories()).top_handle
        step = f"{premise1} {premise2} => (stv 1.0 0.9)"
        rc, payload, _ = _run_case(
            ["--trace", step, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        derivation = payload["per_expression"][0]
        assert derivation["classification"] == "derivation"
        assert derivation["top_handle"] is None
        assert derivation["stored"] is True  # components found in db.links
        assert len(derivation["sources"]) == 1  # union of stored components' sources
        assert payload["missing"] == []


def test_prose_segment_skipped_not_error():
    # A prose segment is skipped (not a harness error); the prose is
    # recorded in prose_segments.
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        trace = "(match &self (Inheritance $X (Concept \"x402\"));this segment is prose"
        rc, payload, _ = _run_case(["--trace", trace, "--ledger-repo", repo])
        assert rc == 0
        assert payload["prose_segments"] == ["this segment is prose"]


def test_live_prose_shape_skipped():
    # The live shape 3: a prose annotation appended after a balanced s-expr.
    # The annotated segment is skipped as prose (recorded in prose_segments,
    # never a harness error); the clean canberra fact in the same trace is
    # still classified + graded normally.
    canberra = '(Inheritance "canberra" "capital-of-australia")'
    annotated = f'{canberra} [reverse-direction probe count=0]'
    canberra_handle = rs._parse_fact(canberra, *rs._factories()).top_handle
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        # the exact live single-segment shape: rc 0, prose recorded
        rc, payload, _ = _run_case(
            ["--trace", annotated, "--ledger-repo", repo])
        assert rc == 0
        assert payload["prose_segments"] == [annotated]
        assert payload["per_expression"] == []
        # multi-segment: the clean canberra fact still classified + graded
        rc, payload, _ = _run_case(
            ["--trace", f"{canberra};{annotated}", "--ledger-repo", repo])
        assert rc == 0
        assert payload["prose_segments"] == [annotated]
        row = payload["per_expression"][0]
        assert row["classification"] == "unstored"
        assert row["expr"] == canberra
        assert row["top_handle"] == canberra_handle
        assert payload["missing"] == [] and payload["conditions"] == []


def test_strip_stv_malformed_falls_through():
    # Malformed stv annotations fall through to normal parsing, which
    # raises MettaParseError — the existing HarnessError path is preserved.
    # `((A) (stv 1.0))` is a wrapped shape with a MALFORMED stv (only one
    # number) → falls through → parse_fact raises.
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        rc, _, err = _run_cli(
            ["--trace", '((A) (stv 1.0))', "--ledger-repo", repo])
        assert rc == 1
        assert "trace unparseable" in err


def test_segment_loop_strip_before_paren_check():
    # Integrated: the segment loop strips the stv FIRST (before the
    # paren check), so a trailing-stv fact step is classified normally.
    with tempfile.TemporaryDirectory() as root:
        repo, commits = _make_ledger_repo(root, [_ledger_entry()])
        trace = f"{X402} (stv 1.0 0.81);this is prose"
        rc, payload, _ = _run_case(
            ["--trace", trace, "--ledger-repo", repo],
            mongo=_scripted_mongo({TOP_HANDLE: _attrs(commits[0])}),
        )
        assert rc == 0
        row = payload["per_expression"][0]
        assert row["classification"] == "stored_fact"
        assert row["expr"] == X402
        assert row["top_handle"] == TOP_HANDLE
        assert payload["prose_segments"] == ["this is prose"]


# --------------------------------- operator-headed calls (wr3q-20261028)

# wr3q-20261028 original case (answers.md), VERBATIM: the agent recorded the
# derivation as TWO trace steps — the bare PLN CALL (step 4, NO `=>` in it)
# and the OUTPUT as its own wrapped-stv ground step (step 5). On HEAD the
# bare call fell to the ground-fact lane -> parse_fact raised "expression
# must start with a symbol" -> HarnessError rc 1 -> the whole case aborted
# ungraded (defect ledger item 2).
CEILING_OVERHEAD = ('(Inheritance (Concept "ceiling") '
                    '(Concept "overhead-surface-of-room"))')
CEILING_OVERHEAD_HANDLE = "99088059d4c09b185e35fe42a0af6dc9"  # live wr3q
WR3Q_STEP4_BARE_CALL = (
    '(|- ((Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room")) (stv 1.0 0.9)) '
    '((Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room")) (stv 0.9 0.8)))'
)
WR3Q_STEP5_OUTPUT = (
    '((Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room")) '
    '(stv 0.9692307692307692 0.9285714285714286))'
)
WR3Q_ORIGINAL_TRACE = ";".join([
    '(Inheritance (Concept "ceiling") $X)',
    CEILING_OVERHEAD,
    '(Inheritance (Concept "illuminated-room") (Concept "visible-surfaces"))',
    WR3Q_STEP4_BARE_CALL,
    WR3Q_STEP5_OUTPUT,
])


def _pipeline_step(segment):
    """Segment-loop preprocessing exactly as _run applies it."""
    return rs.normalize_expression(rs._strip_stv(segment.strip())[0])


def test_operator_headed_bare_call_classifies_derivation():
    # wr3q original step 4 VERBATIM (segment-loop preprocessing applied):
    # kind derivation, atoms = the two stv-stripped premises (same
    # expression -> same derived handle; BOTH entries present), no exception.
    step = _pipeline_step(WR3Q_STEP4_BARE_CALL)
    plan = rs._plan_step(step, 3, *rs._factories())
    assert plan["kind"] == "derivation"
    assert plan["step"] == step
    assert plan["atoms"] == [
        {"expr": CEILING_OVERHEAD, "handle": CEILING_OVERHEAD_HANDLE},
        {"expr": CEILING_OVERHEAD, "handle": CEILING_OVERHEAD_HANDLE},
    ]


def test_operator_headed_trace_end_to_end():
    # THE regression pin for the wr3q original abort: the COMPLETE verbatim
    # original REASONING trace (all 5 steps) through the CLI path, mongo
    # stubbed EMPTY (all atoms unstored -> vacuous pass): exit 0, NO harness
    # error (HEAD: rc 1 "trace unparseable ... step 4 '(|- ...'").
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, err = _run_case(
            ["--trace", WR3Q_ORIGINAL_TRACE, "--ledger-repo", repo,
             "--case", "original"])
        assert rc == 0
        assert "harness error" not in err
        assert [r["classification"] for r in payload["per_expression"]] == [
            "query_clause", "unstored", "unstored", "derivation", "unstored"]
        assert payload["missing"] == [] and payload["conditions"] == []
        derivation = payload["per_expression"][3]
        assert derivation["stored"] is False and derivation["sources"] == []


def test_operator_headed_with_arrow_keeps_arrow_split():
    # A `(|~ <premises>) => <output>` step keeps the EXISTING `=>` split
    # (grading-mirror fidelity): the call stays ONE component; a
    # variable-bearing call is exempt. Live wr3q unsolvable step 5 VERBATIM
    # — its GROUND premise must NOT leak into atoms (that would be the
    # bare-call premise split, wrong on the `=>` side).
    unsolvable_step = (
        '(|~ ((Inheritance $X (Concept "Australia")) (stv 1.0 0.9)) '
        '((Inheritance (Concept "Australia") (Concept "opaque")) (stv 1.0 0.9))) '
        '=> ((Inheritance (Concept "opaque") (Concept "Australia")) '
        '(stv 1.0 0.44751381215469616))'
    )
    plan = rs._plan_step(_pipeline_step(unsolvable_step), 4, *rs._factories())
    assert plan["kind"] == "derivation"
    output = '(Inheritance (Concept "opaque") (Concept "Australia"))'
    assert plan["atoms"] == [{"expr": output, "handle": rs._parse_fact(
        output, *rs._factories()).top_handle}]
    # live wr3q false step 4 VERBATIM — same `=>` shape (Implication premise)
    false_step = (
        '(|~ ((Implication (Inheritance $X (Concept "enclosed-by-ceiling")) '
        '(Inheritance $X (Concept "cannot-see-sky"))) (stv 1.0 0.9)) '
        '((Inheritance (Concept "windowless-room") (Concept "enclosed-by-ceiling")) (stv 0.9 0.8))) '
        '=> ((Inheritance (Concept "windowless-room") (Concept "cannot-see-sky")) '
        '(stv 0.902 0.6480000000000001))'
    )
    plan = rs._plan_step(_pipeline_step(false_step), 3, *rs._factories())
    assert plan["kind"] == "derivation"
    output = '(Inheritance (Concept "windowless-room") (Concept "cannot-see-sky"))'
    assert plan["atoms"] == [{"expr": output, "handle": rs._parse_fact(
        output, *rs._factories()).top_handle}]


def test_operator_headed_variable_premise_exempt():
    # A bare call with a variable premise: the variable premise is skipped
    # (exempt), the ground one is kept (on HEAD the whole step fell to the
    # variable lane and BOTH premises were dropped).
    step = (
        '(|- ((Inheritance $X (Concept "ceiling")) (stv 1.0 0.9)) '
        '((Inheritance (Concept "ceiling") (Concept "overhead-surface-of-room")) (stv 0.9 0.8)))'
    )
    plan = rs._plan_step(_pipeline_step(step), 1, *rs._factories())
    assert plan["kind"] == "derivation"
    assert plan["atoms"] == [
        {"expr": CEILING_OVERHEAD, "handle": CEILING_OVERHEAD_HANDLE}]


# ------------------------ combined `=>` + operator call (wr3r-20261028)

# wr3r-20261028 original case (answers.md), VERBATIM: the agent recorded the
# executed PLN call AND its output as ONE trace step — the COMBINED form
# `(|- <p1> <p2>) => <output>`. On HEAD the `=>` branch split left/right but
# kept the entire operator call as ONE left component; _strip_stv cannot
# unwrap a call, so _parse_fact aborted the whole case ungraded ("expression
# must start with a symbol", grade-case-original.json). FIX E: an operator-
# headed LEFT component decomposes into its premise atoms via the existing
# _split_operator_call; the RIGHT/output side stays ONE component.
SEEN_WHEN_LOOKING_UP = ('(Evaluation (Predicate "seen-when-looking-up") '
                        '(Concept "ceiling"))')
SEEN_WHEN_LOOKING_UP_HANDLE = "bd112e48707fd22a19d186ca64de8675"  # live wr3r
WR3R_STEP3_COMBINED = (
    '(|- ((Evaluation (Predicate "seen-when-looking-up") (Concept "ceiling")) (stv 0.9 0.8)) '
    '((Evaluation (Predicate "seen-when-looking-up") (Concept "ceiling")) (stv 0.9 0.8))) '
    '=> ((Evaluation (Predicate "seen-when-looking-up") (Concept "ceiling")) (stv 0.81 0.64))'
)
WR3R_ORIGINAL_TRACE = ";".join([
    '(Evaluation (Predicate "seen-when-looking-up") $X)',
    SEEN_WHEN_LOOKING_UP,
    WR3R_STEP3_COMBINED,
])


def test_combined_arrow_operator_call_decomposes_left_premises():
    # wr3r original step 3 VERBATIM (pipeline preprocessing applied): kind
    # derivation, atoms = [p1 clean, p2 clean, output clean] — the operator
    # call's premises decompose via _split_operator_call, the output stays
    # ONE component; handles match the live wr3r receipt (bd112e48…).
    plan = rs._plan_step(_pipeline_step(WR3R_STEP3_COMBINED), 2,
                         *rs._factories())
    assert plan["kind"] == "derivation"
    assert plan["atoms"] == [
        {"expr": SEEN_WHEN_LOOKING_UP, "handle": SEEN_WHEN_LOOKING_UP_HANDLE},
        {"expr": SEEN_WHEN_LOOKING_UP, "handle": SEEN_WHEN_LOOKING_UP_HANDLE},
        {"expr": SEEN_WHEN_LOOKING_UP, "handle": SEEN_WHEN_LOOKING_UP_HANDLE},
    ]


def test_combined_arrow_operator_trace_end_to_end():
    # THE regression pin for the wr3r original abort: the COMPLETE verbatim
    # wr3r REASONING trace through the CLI path, mongo stubbed EMPTY (all
    # atoms unstored -> vacuous pass): exit 0, NO harness error (HEAD: rc 1
    # "trace unparseable ... step 3 component '(|- ...'").
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        rc, payload, err = _run_case(
            ["--trace", WR3R_ORIGINAL_TRACE, "--ledger-repo", repo,
             "--case", "original"])
        assert rc == 0
        assert "harness error" not in err
        assert [r["classification"] for r in payload["per_expression"]] == [
            "query_clause", "unstored", "derivation"]
        assert payload["missing"] == [] and payload["conditions"] == []
        derivation = payload["per_expression"][2]
        assert derivation["stored"] is False and derivation["sources"] == []


def test_combined_arrow_variable_call_stays_whole():
    # A variable-bearing operator call on the `=>` LEFT side stays ONE
    # component (skipped per-component, exempt) — the surgical FIX E
    # decomposes only GROUND-ONLY operator calls, so the pinned wr3q
    # unsolvable/false `=>` shapes keep their whole-call exemption.
    unsolvable_step = (
        '(|~ ((Inheritance $X (Concept "Australia")) (stv 1.0 0.9)) '
        '((Inheritance (Concept "Australia") (Concept "opaque")) (stv 1.0 0.9))) '
        '=> ((Inheritance (Concept "opaque") (Concept "Australia")) '
        '(stv 1.0 0.44751381215469616))'
    )
    plan = rs._plan_step(_pipeline_step(unsolvable_step), 4, *rs._factories())
    assert plan["kind"] == "derivation"
    output = '(Inheritance (Concept "opaque") (Concept "Australia"))'
    assert plan["atoms"] == [{"expr": output, "handle": rs._parse_fact(
        output, *rs._factories()).top_handle}]


def _run_module_tests():
    passed = failed = 0
    for name in sorted(list(globals())):
        if name.startswith("test_") and callable(globals()[name]):
            try:
                globals()[name]()
                passed += 1
                print(f"PASS: {name}")
            except AssertionError as exc:
                failed += 1
                print(f"FAIL: {name}: {exc}")
            except Exception as exc:  # noqa: BLE001 (test-runner shim)
                failed += 1
                print(f"ERROR: {name}: {exc}")
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_module_tests())
