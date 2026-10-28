#!/usr/bin/env python3
"""v17 item 8 / SDD T027: cleanup nets N1+N3 contract tests (offline).

N1 rewire: the discovery net is a mongo $or over
custom_attributes.provenance_ref (v4 writes — the ref IS the source URL,
D5) and custom_attributes.provenance_url (pre-migration v2.1 residue),
both $regex-matched against facts.SOURCE_URL_BASE — catches v4 writes
AND legacy residue; N2 (benchmark-only literals) is untouched and the
union/dedupe behavior is preserved.

N3 companion sweep (decision D2): per discovered benchmark fact
expression, the top_handle is computed client-side with the Phase-4
mirror (reconstruct_sources.parse_fact + the fallback hasher formulas —
NO hyperon_das; identical to conftest.py EXPECTED_HANDLES ground truth),
the old WriteProvenance companion links are censused scoped to the
"fact:<top_handle>" Symbol target under a WriteProvenance leading symbol
(targets.0), rebuilt from stored node names, and deleted via the bridge's
cleanup.py (links-only). Scoping is BY CONSTRUCTION (spec §11 residual
risk 7): live research companions (docs/status.md:239) and
CampaignProvenance links (deploy/das/import-wrapper/import_wrapper.py)
can never match. Residue invariant: remaining companions == 0 — a
non-zero remainder is a WARNING + phase rc 1 (parallel to the
remaining-expressions branch). The OLD companion data shape is fixed
(git show 5d978ec~1:deploy/das/write-bridge/write_client.py):
  (WriteProvenance "fact:<top_handle>" "git:<sha>" "url:<url>" "ts:<ts>")

All tests offline: _mongo_eval / _run / _canary_counts / _write_json /
_container_ip are monkeypatched module attributes (the established
pattern — test_preflight_v4.ModPatch); the fake mongo interprets the
EXACT query shapes the production code builds. No network, no docker,
no hyperon_das.
"""
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import run_benchmark as rb  # noqa: E402 (sys.path set above)
from facts import SOURCE_URL_BASE  # noqa: E402


class ModPatch:
    """Context manager swapping run_benchmark module attributes."""

    def __init__(self, **overrides):
        self.overrides = overrides
        self.saved = {}

    def __enter__(self):
        import run_benchmark as rb
        for name, value in self.overrides.items():
            self.saved[name] = getattr(rb, name)
            setattr(rb, name, value)
        return rb

    def __exit__(self, *exc):
        import run_benchmark as rb
        for name, value in self.saved.items():
            setattr(rb, name, value)
        return False


# Pinned ground-truth handles — the REAL pinned client's values
# (live-verified iter16/iter18), copied from deploy/das/write-bridge/tests/
# conftest.py EXPECTED_HANDLES and unit/test_handles_gate.py (which pins
# the same mirror against unit/test_reconstruct_sources.py fixtures).
X402 = '(Inheritance (Concept "x402") (Concept "payment-protocol"))'
X402_TOP_HANDLE = "67293e82ab2162d2d9d5a1578670f678"
MONEY = '(Inheritance (Concept "x402") (Concept "money"))'
MONEY_TOP_HANDLE = "09155ce2dea69ce956a78986008606c7"
SYMBOL_INHERITANCE_HANDLE = "9028a696c1b6d3d9ff8c4f496da77378"
SYMBOL_CONCEPT_HANDLE = "5e50ef7542bb0fde52aed0d841335790"
SYMBOL_X402_HANDLE = "e2f6cbeea42509ef822009139fedfeda"  # quoted name kept

GIT_SHA = "git:" + "ab" * 20
COMPANION_URL = "url:" + SOURCE_URL_BASE + "/spatial-knowledge.md"
COMPANION_TS = "ts:2026-10-22T00:00:00Z"


# ---------------------------------------------------------------------------
# fixtures: build stored atom docs with the same Phase-4 mirror the
# production code uses (parse_fact + fallback factories)
# ---------------------------------------------------------------------------

def _parse(expr):
    rs = rb._handle_helpers()
    node_cls, link_cls = rs._factories()
    return rs._parse_fact(expr, node_cls, link_cls)


def _link_doc(expr, attrs=None):
    """The mongo doc of an expression's TOP link (carries custom_attributes)."""
    fact = _parse(expr)
    return {"_id": fact.top_handle,
            "targets": list(fact.atoms[-1].targets),
            "custom_attributes": dict(attrs or {})}


def _companion(expr):
    """(expression, link doc, node docs) for one stored companion shape."""
    fact = _parse(expr)
    link = {"_id": fact.top_handle, "targets": list(fact.atoms[-1].targets)}
    nodes = [{"_id": a.handle, "name": a.name}
             for a in fact.atoms if not hasattr(a, "targets")]
    return expr, link, nodes


def _companion_of(top_handle, prefix="WriteProvenance", ts=COMPANION_TS):
    return _companion(
        f'({prefix} "fact:{top_handle}" "{GIT_SHA}" '
        f'"{COMPANION_URL}" "{ts}")')


class FakeMongo:
    """In-memory mongo interpreting the exact queries the cleanup code
    builds (routing by query shape; evaluation by the same predicates the
    real queries encode). eval(js) is the _mongo_eval seam."""

    def __init__(self, links=(), nodes=()):
        self.links = [dict(d) for d in links]
        # mongo _id uniqueness: one doc per _id (first occurrence wins)
        uniq: dict[str, dict] = {}
        for d in nodes:
            uniq.setdefault(d["_id"], dict(d))
        self.nodes = list(uniq.values())
        self.queries = []

    def remove_links(self, handles):
        gone = set(handles)
        self.links = [d for d in self.links if d["_id"] not in gone]

    def eval(self, js, timeout=60.0):
        self.queries.append(js)
        if "countDocuments" in js:
            return json.dumps({"nodes": len(self.nodes),
                               "links": len(self.links)}) + "\n"
        if "db.nodes.find" in js:
            targets = json.loads(re.search(
                r"db\.nodes\.find\(\{_id: \{\$in: (\[.*?\])\}\}", js).group(1))
            wanted = set(targets)
            out = [{"_id": d["_id"], "name": d["name"]}
                   for d in self.nodes if d["_id"] in wanted]
            return json.dumps(out) + "\n"
        if "const q = " in js:
            # N3 census: targets include a benchmark fact-symbol handle
            # AND targets.0 is the WriteProvenance symbol handle
            query = json.loads(
                re.search(r"const q = (\{.*\}); const out", js).group(1))
            wp = query["targets.0"]
            fact_syms = set(query["targets"]["$in"])
            out = [{"_id": d["_id"], "targets": d["targets"]}
                   for d in self.links
                   if d.get("targets") and d["targets"][0] == wp
                   and any(t in fact_syms for t in d["targets"])]
            return json.dumps(out) + "\n"
        if '"custom_attributes.provenance_ref"' in js:
            # N1: $or over provenance_ref (v4) + provenance_url (legacy)
            bases = [json.loads(m) for m in
                     re.findall(r'\{\$regex: ("[^"]*")\}', js)]
            assert len(bases) == 2, bases
            assert all(b == SOURCE_URL_BASE for b in bases), bases
            out = [d["custom_attributes"]["metta_expression"]
                   for d in self.links
                   if any((d.get("custom_attributes") or {}).get(k, "").find(b) >= 0
                          for k in ("provenance_ref", "provenance_url")
                          for b in bases)]
            return json.dumps(out) + "\n"
        if '"custom_attributes.metta_expression"' in js:
            # N2: benchmark-only literal net (untouched)
            alt = json.loads(re.search(
                r'"custom_attributes\.metta_expression": '
                r'\{\$regex: ("[^"]*")\}', js).group(1))
            # the production net re.escape()s each literal into the $regex
            # alternation — unescape for matching (plain ASCII words)
            lits = alt.replace("\\", "").split("|")
            out = [attrs["metta_expression"]
                   for d in self.links
                   for attrs in [(d.get("custom_attributes") or {})]
                   if any(l in attrs.get("metta_expression", "")
                          for l in lits)]
            return json.dumps(out) + "\n"
        raise AssertionError(f"unexpected mongo query: {js[:120]}")


class FakeRunner:
    """_run seam: records every command; simulates the links-only cleanup.py
    deletion (re-derives the expression's link handles with the same
    Phase-4 mirror and removes those link docs). skip_companion marks
    companion deletions as non-landing (the eventual-apply residue case)."""

    def __init__(self, mongo, skip_companion=False):
        self.mongo = mongo
        self.skip_companion = skip_companion
        self.cmds = []

    def cleanup_cmds(self):
        return [c for c in self.cmds if "cleanup.py" in c]

    def run(self, cmd, timeout=30.0):
        cmd = [str(c) for c in cmd]
        self.cmds.append(cmd)
        out, err = "", ""
        if "cleanup.py" in cmd:
            expr = cmd[cmd.index("--metta") + 1]
            if self.skip_companion and expr.startswith("(WriteProvenance"):
                out = "absent: false\n"
            else:
                fact = _parse(expr)
                self.mongo.remove_links(fact.link_handles)
                out = "absent: true\n"
        return SimpleNamespace(returncode=0, stdout=out, stderr=err)


def _cleanup_args(run_id="unit-cleanup", dry_run=False):
    return SimpleNamespace(run_id=run_id, dry_run=dry_run)


def _bench_residue_store(companions=()):
    """A store with ONE v4 benchmark residue fact (X402, provenance_ref)
    plus optional companion fixtures (link doc + node docs each)."""
    bench = _link_doc(X402, {"metta_expression": X402,
                             "provenance_ref": SOURCE_URL_BASE + "/spatial-knowledge.md"})
    links = [bench] + [c[1] for c in companions]
    nodes = [n for c in companions for n in c[2]]
    return FakeMongo(links=links, nodes=nodes)


# ---------------------------------------------------------------------------
# N1: the $or discovery net (v4 provenance_ref + legacy provenance_url)
# ---------------------------------------------------------------------------

def test_n1_or_discovers_v4_ref_and_legacy_url_residue():
    v4 = _link_doc(X402, {"metta_expression": X402,
                          "provenance_ref": SOURCE_URL_BASE + "/spatial-knowledge.md"})
    legacy = _link_doc(MONEY, {"metta_expression": MONEY,
                              "provenance_url": SOURCE_URL_BASE + "/lighting.md"})
    unrelated = _link_doc('(Inheritance (Concept "x402") (Concept "unrelated"))',
                          {"metta_expression": '(Inheritance (Concept "x402") (Concept "unrelated"))',
                           "provenance_ref": "https://elsewhere.example/x.md"})
    mongo = FakeMongo(links=[v4, legacy, unrelated])
    with ModPatch(_mongo_eval=mongo.eval):
        exprs = rb._discover_benchmark_expressions()
    assert X402 in exprs, exprs        # v4 write: discovered via provenance_ref
    assert MONEY in exprs, exprs       # legacy residue: via provenance_url
    assert all("unrelated" not in e for e in exprs), exprs


def test_discovery_union_dedupes_across_nets():
    # one residue doc matched by BOTH nets (N1 via provenance_url, N2 via a
    # benchmark-only literal in the expression) + one N2-only doc: the
    # union must contain each exactly once
    both = '(Inheritance (Concept "windowless-room") (Concept "enclosed-space"))'
    n2_only = ('(Evaluation (Predicate "has-no-openings") '
               '(Concept "windowless-room") (Concept "exterior"))')
    mongo = FakeMongo(links=[
        _link_doc(both, {"metta_expression": both,
                         "provenance_url": SOURCE_URL_BASE + "/spatial-knowledge.md"}),
        _link_doc(n2_only, {"metta_expression": n2_only}),
    ])
    with ModPatch(_mongo_eval=mongo.eval):
        exprs = rb._discover_benchmark_expressions()
    assert exprs.count(both) == 1, exprs
    assert exprs.count(n2_only) == 1, exprs
    assert sorted(exprs) == sorted([both, n2_only])


def test_n1_query_shape_or_both_provenance_keys():
    # grep-hook: the N1 net is a $or over BOTH attr keys; N2 untouched
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "run_benchmark.py"),
              encoding="utf-8") as f:
        src = f.read()
    start = src.index("def _discover_benchmark_expressions")
    end = src.find("\ndef ", start + 1)
    body = src[start:end]
    assert "$or" in body
    assert '"custom_attributes.provenance_ref"' in body
    assert '"custom_attributes.provenance_url"' in body
    # N2's benchmark-only literal net stays exactly as it was
    assert '"custom_attributes.metta_expression"' in body
    assert "windowless-room" in body
    assert "sloped-ceiling" in body


# ---------------------------------------------------------------------------
# N3: client-side handle computation (Phase-4 mirror, pinned ground truth)
# ---------------------------------------------------------------------------

def test_n3_fact_top_handles_match_pinned_ground_truth():
    handles, errors = rb._fact_top_handles([X402, MONEY])
    assert errors == []
    assert handles[X402] == X402_TOP_HANDLE, handles
    assert handles[MONEY] == MONEY_TOP_HANDLE, handles
    # the Symbol-node handle helper reproduces the pinned node-handle
    # formula (conftest EXPECTED_HANDLES): bare symbols and quoted names
    rs = rb._handle_helpers()
    node_cls, _ = rs._factories()
    assert rb._symbol_node_handle(node_cls, "Inheritance") == SYMBOL_INHERITANCE_HANDLE
    assert rb._symbol_node_handle(node_cls, "Concept") == SYMBOL_CONCEPT_HANDLE
    # quoted literal names KEEP their quotes (metta_to_atoms convention)
    assert rb._symbol_node_handle(node_cls, '"x402"') == SYMBOL_X402_HANDLE


def test_n3_unparseable_expression_recorded_not_raised():
    handles, errors = rb._fact_top_handles([X402, "(broken"])
    assert handles == {X402: X402_TOP_HANDLE}
    assert len(errors) == 1 and errors[0]["metta"] == "(broken"
    assert "error" in errors[0]


# ---------------------------------------------------------------------------
# N3: scoping — benchmark companions only, by construction
# ---------------------------------------------------------------------------

def test_n3_sweep_scopes_to_benchmark_fact_companions_only():
    bench_expr, bench_link, bench_nodes = _companion_of(X402_TOP_HANDLE)
    _research_expr, research_link, research_nodes = _companion_of("f" * 32)
    _cp_expr, cp_link, cp_nodes = _companion_of(X402_TOP_HANDLE,
                                                prefix="CampaignProvenance")
    mongo = FakeMongo(links=[bench_link, research_link, cp_link],
                      nodes=bench_nodes + research_nodes + cp_nodes)
    runner = FakeRunner(mongo)
    with ModPatch(_mongo_eval=mongo.eval, _run=runner.run):
        sweep = rb._sweep_write_provenance_companions([X402])
    # (a) the benchmark fact's companion IS matched and cleaned
    assert [d["_id"] for d in sweep["discovered"]] == [bench_link["_id"]]
    cleanups = runner.cleanup_cmds()
    assert len(cleanups) == 1, runner.cmds
    assert cleanups[0][cleanups[0].index("--metta") + 1] == bench_expr
    assert sweep["cleanup_results"][0]["returncode"] == 0
    assert sweep["remaining_count"] == 0
    # (b) a WriteProvenance companion of a NON-benchmark handle survives
    #     (live research companions — docs/status.md:239)
    assert any(d["_id"] == research_link["_id"] for d in mongo.links)
    # (c) a CampaignProvenance link on the SAME benchmark handle survives
    #     (leading symbol differs — never matched)
    assert any(d["_id"] == cp_link["_id"] for d in mongo.links)


def test_companion_expression_rebuild_matches_stored_form():
    stored = (f'(WriteProvenance "fact:{X402_TOP_HANDLE}" "{GIT_SHA}" '
              f'"{COMPANION_URL}" "{COMPANION_TS}")')
    expr, link, nodes = _companion(stored)
    mongo = FakeMongo(links=[link], nodes=nodes)
    runner = FakeRunner(mongo)
    with ModPatch(_mongo_eval=mongo.eval, _run=runner.run):
        sweep = rb._sweep_write_provenance_companions([X402])
    entry = sweep["cleanup_results"][0]
    # the rebuilt expression string equals the stored companion form
    assert entry["metta"] == stored
    assert entry["returncode"] == 0
    assert entry["stdout"] == "absent: true"
    assert entry["stderr"] == ""
    # the cleanup.py invocation is the validated links-only exec pattern
    cleanups = runner.cleanup_cmds()
    assert cleanups == [["docker", "exec", "-w", "/app",
                         rb.CONTAINER_WRITE_BRIDGE,
                         "python", "cleanup.py", "--metta", stored]]


def test_companion_parse_failure_recorded_phase_does_not_crash():
    # a discovered companion whose stored target names drifted into an
    # unparseable form: recorded + skipped (never dispatched), the sweep
    # continues to the NEXT companion and the phase does not crash — the
    # drifted doc remains, so the residue invariant flags it (rc 1)
    good_expr, good_link, good_nodes = _companion_of(X402_TOP_HANDLE)
    bad_expr, bad_link, bad_nodes = _companion_of(
        X402_TOP_HANDLE, ts="ts:2026-10-23T00:00:00Z")
    for n in bad_nodes:
        if n["name"].startswith('"ts:'):
            n["name"] = 'ts:2026"10-23'  # drifted name: quote glued to a symbol
    mongo = _bench_residue_store(companions=[(bad_expr, bad_link, bad_nodes),
                                             (good_expr, good_link, good_nodes)])
    runner = FakeRunner(mongo)
    captured = {}
    out = io.StringIO()
    with ModPatch(_mongo_eval=mongo.eval, _run=runner.run,
                  _canary_counts=lambda: {"fetch_ai_inheritance": 2},
                  _write_json=lambda p, d: captured.update(path=p, data=d),
                  _container_ip=lambda c: ""):
        with redirect_stdout(out):
            rc = rb.cleanup_das(_cleanup_args())
    assert rc == 1  # the drifted companion remains -> residue invariant fires
    assert "companion" in out.getvalue()
    sweep = captured["data"]["companion_sweep"]
    entries = sweep["cleanup_results"]
    assert len(entries) == 2, entries
    bad = [e for e in entries if "parse_error" in e]
    assert len(bad) == 1, entries
    assert bad[0].get("returncode") is None      # never dispatched
    assert bad[0]["targets"] == bad_link["targets"]
    good = [e for e in entries if e.get("metta") == good_expr]
    assert len(good) == 1 and good[0]["returncode"] == 0
    # only the CLEAN companion was dispatched (plus the expression lane's
    # own dispatch for X402); the drifted rebuild never reached cleanup.py
    cleanups = runner.cleanup_cmds()
    companion_dispatches = [c for c in cleanups
                            if c[c.index("--metta") + 1].startswith("(WriteProvenance")]
    assert len(companion_dispatches) == 1, runner.cmds
    assert companion_dispatches[0][companion_dispatches[0].index("--metta") + 1] == good_expr
    assert all('ts:2026"10-23' not in c[c.index("--metta") + 1] for c in cleanups)
    assert sweep["remaining_count"] == 1
    assert sweep["handle_errors"] == []           # X402 itself parses fine
    # expression residue is clean; the rc-1 comes from the companion branch
    assert captured["data"]["remaining_expressions"] == []


# ---------------------------------------------------------------------------
# residue invariant + dry-run (cleanup_das end-to-end, offline)
# ---------------------------------------------------------------------------

def test_cleanup_das_companion_residue_zero_passes():
    companion = _companion_of(X402_TOP_HANDLE)
    mongo = _bench_residue_store(companions=[companion])
    runner = FakeRunner(mongo)
    captured = {}
    out = io.StringIO()
    with ModPatch(_mongo_eval=mongo.eval, _run=runner.run,
                  _canary_counts=lambda: {"fetch_ai_inheritance": 2},
                  _write_json=lambda p, d: captured.update(path=p, data=d),
                  _container_ip=lambda c: ""):
        with redirect_stdout(out):
            rc = rb.cleanup_das(_cleanup_args())
    assert rc == 0, out.getvalue()
    data = captured["data"]
    assert str(captured["path"]).endswith("cleanup-das.json")
    sweep = data["companion_sweep"]
    assert [d["_id"] for d in sweep["discovered"]] == [companion[1]["_id"]]
    assert sweep["cleanup_results"][0]["returncode"] == 0
    assert sweep["remaining_count"] == 0
    assert data["remaining_expressions"] == []
    assert data["canaries_intact"] is True
    # both lanes dispatched exactly one cleanup.py each (expr + companion)
    assert len(runner.cleanup_cmds()) == 2, runner.cmds
    assert "companions swept=1 remaining=0" in out.getvalue()


def test_cleanup_das_companion_residue_nonzero_warns_and_fails():
    companion = _companion_of(X402_TOP_HANDLE)
    mongo = _bench_residue_store(companions=[companion])
    runner = FakeRunner(mongo, skip_companion=True)  # companion delete lands nowhere
    captured = {}
    out = io.StringIO()
    with ModPatch(_mongo_eval=mongo.eval, _run=runner.run,
                  _canary_counts=lambda: {"fetch_ai_inheritance": 2},
                  _write_json=lambda p, d: captured.update(path=p, data=d),
                  _container_ip=lambda c: ""):
        with redirect_stdout(out):
            rc = rb.cleanup_das(_cleanup_args())
    assert rc == 1
    text = out.getvalue()
    assert "WARNING" in text and "companion" in text
    data = captured["data"]
    # expression residue IS clean — the rc-1 comes from the companion branch
    assert data["remaining_count"] == 0
    sweep = data["companion_sweep"]
    assert len(sweep["discovered"]) == 1
    assert sweep["cleanup_results"][0]["returncode"] == 0  # dispatched, didn't land
    assert sweep["remaining_count"] == 1


def test_cleanup_das_dry_run_mentions_companion_sweep_no_calls():
    mongo = FakeMongo()
    runner = FakeRunner(mongo)
    out = io.StringIO()
    with ModPatch(_mongo_eval=mongo.eval, _run=runner.run,
                  _canary_counts=lambda: {"fetch_ai_inheritance": 2},
                  _container_ip=lambda c: ""):
        with redirect_stdout(out):
            rc = rb.cleanup_das(_cleanup_args(run_id="unit-dry", dry_run=True))
    assert rc == 0
    # NO mongo calls, NO dispatches (the dry-run branch mutates nothing)
    assert mongo.queries == [], mongo.queries
    assert runner.cmds == [], runner.cmds
    msg = out.getvalue()
    assert "companion" in msg
    for phrase in ("compute fact handles", "discover companion links",
                   "cleanup.py each", "verify absence"):
        assert phrase in msg, phrase
