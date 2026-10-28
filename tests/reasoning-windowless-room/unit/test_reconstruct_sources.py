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
    with tempfile.TemporaryDirectory() as root:
        repo, _ = _make_ledger_repo(root, [_ledger_entry()])
        bad = "(match &self $X); this is prose, not metta"
        rc, _, err = _run_cli(["--trace", bad, "--ledger-repo", repo])
        assert rc == 1
        assert "trace unparseable" in err
        assert "prose, not metta" in err  # names the offending segment


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
            "missing", "conditions", "source_paths"}
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
