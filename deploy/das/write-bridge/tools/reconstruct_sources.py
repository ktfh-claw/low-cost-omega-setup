#!/usr/bin/env python3
"""Standalone provenance reconstruction script (issue #2 Phase 4, spec §7).

Given the agent's REASONING trace, deterministically walks the chain

    trace expression -> re-derived top_handle -> mongo link doc
    -> custom_attributes provenance -> ledger commit -> ledger entry
    -> optional byte-verify against background files

with ZERO LLM calls and ZERO pattern-engine queries — mongo is reached
ONLY via ``docker exec <container> mongosh`` (the script never joins a
DAS bus; spec §0). Normative interface: spec §2.4 (CLI + chain + output
JSON), §2.2 (ledger format), §2.5 (strings), §2.6 (condition codes),
§10 decisions D1/D4/D6.

Mirrored (NOT imported across the tests/ tree) semantics — this script is
self-contained in the bridge dir:

- ``grading.normalize_expression`` (tests/reasoning-windowless-room/grading.py:139-141)
- ``grading.parse_reasoning_trace`` (:266-286 — semicolon-separated; every
  non-empty segment must be a parenthesized s-expr; anything else is prose;
  here prose is a harness error, exit 1);
- ``grading._split_derivation_atoms`` (:447-460) + ``grading._top_level_sexprs``
  (:422-444 — a step containing ``=>`` splits into left+right component
  atoms; a step without ``=>`` is a single atom);
- ``provenance_check._git`` (tests/reasoning-windowless-room/provenance_check.py:58-63
  — sudo default, per-invocation ``-c safe.directory=<repo>``, ``-C repo``,
  ``--no-pager``, timeout) and the LEGACY chain ``provenance_check.resolve_citation``
  (:70-147 — sources/ blob + index.jsonl) used for ``--legacy-repo``.

Imported: ``metta_to_atoms.parse_fact`` (this file inserts its own
parent-parent dir on sys.path so the import works from anywhere).
``hyperon_das`` is optional: on ImportError the script falls back to
mirror Node/Link classes with the EXACT handle formulas of the pinned
client's hasher (md5("type name") for nodes, md5(" ".join([md5(type),
*targets])) for links — deploy/das/write-bridge/tests/conftest.py
``MirrorNode``/``MirrorLink``; handles are identical either way,
live-verified iter16/iter18 on the pinned client and the OVH host, which
has NO hyperon_das installed).

Phase-0b attribute semantics (live-verified, iter18_results.md): re-writing
the same expression with different provenance OVERWRITES the top link's
custom_attributes (last write wins per fact handle), so reconstruction
always sees exactly one provenance per fact.

Exit codes (spec §2.4/§2.6): 0 = all used stored facts' sources resolve
(vacuously 0 for an empty trace); 2 = some used stored fact's source is
missing/unresolvable (blocking conditions, except legacy-informational
cases); 1 = harness error (usage, mongo unreachable, ledger repo
unreadable, trace unparseable, internal errors). H_* cross-check
conditions ride in the JSON and NEVER affect the exit code (decision D4).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

_BRIDGE_DIR = Path(__file__).resolve().parent.parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import metta_to_atoms
from metta_to_atoms import MettaParseError

LEDGER_NAME = "SOURCE-LEDGER.json"
DEFAULT_MONGO_CONTAINER = "omega-das-integration-mongodb-1"
MONGO_BATCH_SIZE = 50
GIT_TIMEOUT = 30.0
MONGO_TIMEOUT = 60.0
ENTRY_KEYS = {"ref", "sha256", "entry_date"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VAR_RE = re.compile(r"\$[A-Za-z0-9_-]")

# Blocking P-gate conditions (spec §2.6); legacy-informational entries never
# contribute to exit 2 (resolution 4 / decision D6).
BLOCKING_CONDITIONS = (
    "NO_PROVENANCE_ATTRS",
    "COMMIT_NOT_IN_REPO",
    "COMMIT_UNREADABLE",
    "COMMIT_NOT_A_LEDGER_COMMIT",
    "COMMIT_TOUCHES_OTHER_FILES",
    "COMMIT_ADDS_NOT_ONE_LINE",
    "ENTRY_PARSE_FAILED",
    "REF_SHA_MISMATCH",
)

DEFAULT_SUDO = True


class UsageError(Exception):
    """CLI usage error -> exit 1 (exit 2 is RESERVED for case-FAIL)."""


class HarnessError(Exception):
    """Harness-side error -> exit 1 (mongo, ledger repo, trace, internal)."""


class MongoError(HarnessError):
    """docker/mongosh invocation failed."""


class _ArgumentParser(argparse.ArgumentParser):
    """argparse whose usage errors exit 1, never 2 (2 = case FAIL)."""

    def error(self, message):
        raise UsageError(message)


# ---------------------------------------------------------------- handles
# Mirror of the pinned client's hasher formulas (conftest.py MirrorNode /
# MirrorLink; identical to hyperon_das.hasher — live-verified iter16).


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class _FallbackNode:
    def __init__(self, type=None, name=None, **_):
        if not type or not name:
            raise ValueError("'type' and 'name' are required")
        self.type = type
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def handle(self):
        return _md5(f"{self.type} {self.name}")


class _FallbackLink:
    def __init__(self, type=None, targets=None, **_):
        if not type or not targets:
            raise ValueError("'type' and 'targets' are required")
        self.type = type
        self._targets = list(targets)

    @property
    def targets(self):
        return self._targets

    @property
    def handle(self):
        return _md5(" ".join([_md5(self.type), *self._targets]))


def _factories() -> tuple[type, type]:
    """The pinned client's Node/Link, or the formula-identical fallback."""
    try:
        return metta_to_atoms._pinned_factories()
    except ImportError:
        return _FallbackNode, _FallbackLink


def _parse_fact(expr: str, node_cls, link_cls) -> metta_to_atoms.ParsedFact:
    return metta_to_atoms.parse_fact(expr, node_factory=node_cls, link_factory=link_cls)


# ------------------------------------------------------- grading.py mirrors


def normalize_expression(expr: str) -> str:
    """Whitespace-normalize a MeTTa expression (grading.py:139-141)."""
    return " ".join(expr.split())


def _top_level_sexprs(text: str) -> list[str]:
    """The top-level balanced quote-aware s-expressions (grading.py:422-444)."""
    out: list[str] = []
    depth = 0
    in_str = False
    start = 0
    for i, ch in enumerate(text):
        if in_str:
            if ch == '"' and (i == 0 or text[i - 1] != "\\"):
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    out.append(normalize_expression(text[start:i + 1]))
    return out


def _split_derivation_atoms(step: str) -> list[str]:
    """Split an executed-derivation step into component atoms (grading.py:447-460)."""
    if "=>" not in step:
        return [step]
    left, right = step.split("=>", 1)
    return _top_level_sexprs(left) + _top_level_sexprs(right)


def _is_variable_bearing(expr: str) -> bool:
    """True iff the expression carries a $variable token (outside strings)."""
    body = re.sub(r'"[^"]*"', "", expr)
    return _VAR_RE.search(body) is not None


# ------------------------------------------------------------------- git
# Mirror of provenance_check._git (:58-63): sudo default, safe.directory,
# -C repo, --no-pager, per-invocation timeout.


def _git(repo: str, *args: str, sudo: bool = True,
         timeout: float = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    cmd = (["sudo"] if sudo else []) + [
        "git", "-c", f"safe.directory={repo}", "-C", repo, "--no-pager",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _run_ok(result: subprocess.CompletedProcess) -> bool:
    return result.returncode == 0


def _commit_sha(commit_attr: str) -> str:
    """Normalize a provenance_git_commit attr ("git:<sha>" or bare sha)."""
    if isinstance(commit_attr, str) and commit_attr.startswith("git:"):
        return commit_attr[4:]
    return commit_attr


# ------------------------------------------------------------------ mongo


def _mongo_find_links(container: str, handles: list[str]) -> dict[str, dict | None]:
    """One logical mongo query for ALL handles, in bounded batches.

    Seam function: tests monkeypatch this. Returns ``{handle: custom_attributes
    or None}`` for FOUND link docs only (a found doc with no/empty
    custom_attributes maps to None — NO_PROVENANCE_ATTRS). Raises
    :class:`MongoError` on docker/mongosh failure.
    """
    found: dict[str, dict | None] = {}
    for i in range(0, len(handles), MONGO_BATCH_SIZE):
        batch = handles[i:i + MONGO_BATCH_SIZE]
        js = (
            "const hs=%s; const r=db.links.find({_id:{$in:hs}},"
            "{_id:1,custom_attributes:1}).toArray(); print(JSON.stringify(r));"
            % json.dumps(batch)
        )
        cmd = [
            "docker", "exec", container, "sh", "-c",
            'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
            "--authenticationDatabase admin --quiet das --eval " + shlex.quote(js),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=MONGO_TIMEOUT)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise MongoError(f"mongo unreachable: {exc}")
        if proc.returncode != 0:
            raise MongoError(
                "mongo unreachable: "
                + (proc.stderr.strip()[:200] or f"docker exec exited {proc.returncode}")
            )
        try:
            docs = json.loads(proc.stdout)
        except ValueError as exc:
            raise MongoError(f"mongo unreachable: unparseable mongosh output: {exc}")
        if not isinstance(docs, list):
            raise MongoError("mongo unreachable: mongosh output is not a JSON array")
        for doc in docs:
            if isinstance(doc, dict) and "_id" in doc:
                attrs = doc.get("custom_attributes")
                found[doc["_id"]] = attrs if isinstance(attrs, dict) and attrs else None
    return found


# ----------------------------------------------------------- ledger chain


def _background_candidate(background_dir: str, ref: str) -> str | None:
    """The background file candidate for a ref, or None (check skipped)."""
    if ref.startswith(("http://", "https://")):
        return os.path.join(background_dir, ref.rsplit("/", 1)[-1])
    if ref.startswith("/"):
        return os.path.join(background_dir, ref.lstrip("/"))
    return None


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry_is_shaped(obj: object) -> bool:
    return (
        isinstance(obj, dict)
        and set(obj) == ENTRY_KEYS
        and isinstance(obj.get("ref"), str)
        and bool(obj.get("ref"))
        and isinstance(obj.get("sha256"), str)
        and _SHA256_RE.match(obj["sha256"]) is not None
        and isinstance(obj.get("entry_date"), str)
        and bool(obj.get("entry_date"))
    )


def _ledger_resolve(repo: str, commit: str, ref: str, sha256: str, *,
                    sudo: bool = True, background_dir: str | None = None) -> dict:
    """The ledger chain for one (commit, ref, sha256) triple.

    Returns a source-entry dict (JSON shape per spec §2.4). Blocking
    conditions leave ``resolved`` False; a clean chain sets it True and
    runs the optional --background-dir byte-hash check.
    """
    entry = {
        "commit": commit,
        "ref": ref,
        "sha256": sha256,
        "entry_date": None,
        "resolved": False,
        "legacy": False,
        "conditions": [],
        "background_file": None,
        "background_match": None,
    }
    if not _run_ok(_git(repo, "cat-file", "-e", f"{commit}^{{commit}}", sudo=sudo)):
        entry["conditions"].append("COMMIT_NOT_IN_REPO")
        return entry
    show = _git(repo, "show", "--name-only", "--format=", commit, sudo=sudo)
    if not _run_ok(show):
        entry["conditions"].append("COMMIT_UNREADABLE")
        return entry
    files = [f for f in show.stdout.split("\n") if f.strip()]
    if LEDGER_NAME not in files:
        entry["conditions"].append("COMMIT_NOT_A_LEDGER_COMMIT")
        return entry
    if files != [LEDGER_NAME]:
        entry["conditions"].append("COMMIT_TOUCHES_OTHER_FILES")
        return entry
    diff = _git(repo, "show", "--format=", "--unified=0", commit,
                "--", LEDGER_NAME, sudo=sudo)
    if not _run_ok(diff):
        entry["conditions"].append("COMMIT_UNREADABLE")
        return entry
    added = [line[1:] for line in diff.stdout.splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    candidates: list[str] = []
    for line in added:
        text = line[1:] if line.startswith(",") else line
        if text.startswith("{"):
            candidates.append(text)
    if len(candidates) != 1:
        entry["conditions"].append("COMMIT_ADDS_NOT_ONE_LINE")
        return entry
    try:
        obj = json.loads(candidates[0])
    except ValueError:
        entry["conditions"].append("ENTRY_PARSE_FAILED")
        return entry
    if not _entry_is_shaped(obj):
        entry["conditions"].append("ENTRY_PARSE_FAILED")
        return entry
    if (obj["ref"], obj["sha256"]) != (ref, sha256):
        entry["conditions"].append("REF_SHA_MISMATCH")
        return entry
    entry["entry_date"] = obj["entry_date"]
    entry["resolved"] = True
    if background_dir:
        candidate = _background_candidate(background_dir, ref)
        if candidate is not None and os.path.isfile(candidate):
            entry["background_file"] = candidate
            entry["background_match"] = _file_sha256(candidate) == sha256
            if not entry["background_match"]:
                # Content drift: the ledger's hash does not match the actual
                # source bytes (blocking, exit 2 path).
                entry["resolved"] = False
                entry["conditions"].append("REF_SHA_MISMATCH")
        # else: check skipped — no condition, background fields stay null.
    return entry


# -------------------------------------------------- legacy chain (D6, res. 4)
# Mirror of provenance_check.resolve_citation (:70-147): the OLD
# sources/-blob + index.jsonl format, for --legacy-repo INFORMATIONAL
# resolution only — never blocking, never in the default grade path.


def _legacy_resolve(repo: str, citation: str, *, sudo: bool = True) -> dict | None:
    """Resolve a pre-migration citation against a legacy-format repo.

    Returns the entry metadata dict on success, None on any failure.
    """
    short = citation[4:] if citation.startswith("git:") else citation
    if not _run_ok(_git(repo, "cat-file", "-e", f"{short}^{{commit}}", sudo=sudo)):
        return None
    show = _git(repo, "show", "--name-only", "--format=", short, sudo=sudo)
    if not _run_ok(show):
        return None
    files = [f for f in show.stdout.split("\n") if f.strip()]
    src_files = [f for f in files if f.startswith("sources/")]
    if len(src_files) != 1:
        return None
    blob_path = src_files[0]
    idx = _git(repo, "show", f"{short}:index.jsonl", sudo=sudo)
    if not _run_ok(idx):
        return None
    entry = None
    for line in idx.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            cand = json.loads(line)
        except ValueError:
            continue
        if isinstance(cand, dict) and cand.get("path") == blob_path:
            entry = cand
            break
    if entry is None:
        return None
    blob = _git(repo, "show", f"{short}:{blob_path}", sudo=sudo)
    if not _run_ok(blob):
        return None
    blob_sha = hashlib.sha256(blob.stdout.encode("utf-8")).hexdigest()
    if blob_sha != entry.get("blob_sha256"):
        return None
    return {
        "commit": short,
        "ref": entry.get("url", ""),
        "sha256": blob_sha,
        "entry_date": entry.get("archived_at", ""),
    }


# --------------------------------------------------------------- H cross-check


def _handles_check(facts_raw: str | None, handles_raw: str | None,
                   node_cls, link_cls) -> dict:
    """The D4 HANDLES cross-check — rides in the JSON, NEVER the exit code."""
    facts = [s.strip() for s in (facts_raw or "").split(";") if s.strip()]
    claimed = (handles_raw or "").split()
    derived: list[str | None] = []
    conditions: list[str] = []
    for fact in facts:
        try:
            derived.append(_parse_fact(fact, node_cls, link_cls).top_handle)
        except (MettaParseError, ValueError):
            derived.append(None)  # unparseable facts expression derives null
    if facts and not claimed:
        conditions.append("H_MISSING")
    elif facts and len(claimed) != len(derived):
        conditions.append("H_COUNT_MISMATCH")
    for i in range(min(len(claimed), len(derived))):
        if claimed[i] != derived[i]:
            conditions.append("H_MISMATCH")
    return {"claimed": claimed, "derived": derived, "conditions": conditions}


# ------------------------------------------------------------- trace pipeline


def _plan_step(step: str, index: int, node_cls, link_cls) -> dict:
    """Classify one trace step and pre-derive its ground atoms' handles.

    Classification (spec §2.4/§7): (b) query clause = variable-bearing
    FIRST step, exempt; (c) derivation = any step containing ``=>``, split
    into component atoms (grading._split_derivation_atoms); (a) every other
    ground step (and ground derivation components) = stored-fact candidate.
    """
    if index == 0 and _is_variable_bearing(step):
        return {"kind": "query_clause", "step": step, "atoms": []}
    if "=>" in step:
        atoms: list[dict] = []
        for atom_expr in _split_derivation_atoms(step):
            if _is_variable_bearing(atom_expr):
                continue  # variable-bearing component atoms are exempt
            try:
                handle = _parse_fact(atom_expr, node_cls, link_cls).top_handle
            except MettaParseError as exc:
                raise HarnessError(
                    f"trace unparseable: step {index + 1} component "
                    f"{atom_expr[:80]!r}: {exc}"
                )
            atoms.append({"expr": atom_expr, "handle": handle})
        return {"kind": "derivation", "step": step, "atoms": atoms}
    if _is_variable_bearing(step):
        return {"kind": "variable", "step": step, "atoms": []}
    try:
        handle = _parse_fact(step, node_cls, link_cls).top_handle
    except MettaParseError as exc:
        raise HarnessError(
            f"trace unparseable: step {index + 1} {step[:80]!r}: {exc}"
        )
    return {"kind": "fact", "step": step, "atoms": [{"expr": step, "handle": handle}]}


def _no_attrs_source(legacy_repo: str | None) -> dict:
    """Source entry for a stored link with NO provenance attributes.

    Blocking by default (NO_PROVENANCE_ATTRS -> exit 2); under
    --legacy-repo the entry is legacy-informational (never blocking —
    pre-migration atoms carried provenance in companion atoms, not
    custom_attributes; resolution 4).
    """
    return {
        "commit": None, "ref": None, "sha256": None, "entry_date": None,
        "resolved": False, "legacy": bool(legacy_repo),
        "conditions": ["NO_PROVENANCE_ATTRS"],
        "background_file": None, "background_match": None,
    }


def _resolve_atom(attrs: dict | None, ledger_repo: str, legacy_repo: str | None,
                  *, sudo: bool, background_dir: str | None,
                  cache: dict) -> tuple[dict, list[str]]:
    """Ledger-chain one stored atom's attribute set.

    Returns ``(source_entry, blocking_conditions)``. Blocking conditions
    are the entry's conditions unless the entry is legacy-informational
    (``legacy: true`` — never blocking, resolution 4).
    """
    if not attrs or not all(
        key in attrs for key in
        ("provenance_git_commit", "provenance_ref", "provenance_blob_sha256")
    ):
        entry = _no_attrs_source(legacy_repo)
        return entry, ([] if entry["legacy"] else entry["conditions"])
    commit = _commit_sha(attrs["provenance_git_commit"])
    ref = attrs["provenance_ref"]
    sha256 = attrs["provenance_blob_sha256"]
    key = (commit, ref, sha256, bool(background_dir))
    if key not in cache:
        entry = _ledger_resolve(ledger_repo, commit, ref, sha256,
                                sudo=sudo, background_dir=background_dir)
        if (not entry["resolved"]
                and "COMMIT_NOT_IN_REPO" in entry["conditions"]
                and legacy_repo):
            legacy = _legacy_resolve(legacy_repo, attrs["provenance_git_commit"],
                                     sudo=sudo)
            if legacy is not None:
                entry = dict(legacy)
                entry.update({
                    "resolved": True, "legacy": True, "conditions": [],
                    "background_file": None, "background_match": None,
                })
        cache[key] = entry
    entry = cache[key]
    blocking = [] if entry["legacy"] else entry["conditions"]
    return entry, blocking


def _source_path(entry: dict, background_dir: str | None) -> str:
    """The path a resolved source maps to (background file if present)."""
    if background_dir:
        candidate = _background_candidate(background_dir, entry["ref"])
        if candidate is not None and os.path.isfile(candidate):
            return candidate
    return entry["ref"]


def _shorten(expr: str, limit: int = 96) -> str:
    return expr if len(expr) <= limit else expr[: limit - 3] + "..."


def _print_summary(payload: dict) -> None:
    """Concise human summary: per-expression verdicts + handles + verdict."""
    for row in payload["per_expression"]:
        expr = _shorten(row["expr"])
        if row["classification"] in ("query_clause", "variable", "unstored"):
            print(f"step: {row['classification']} (exempt): {expr}")
        elif row["classification"] == "derivation":
            resolved = sum(1 for s in row["sources"] if s["resolved"])
            state = "OK" if not row["conditions"] else f"FAIL {row['conditions']}"
            print(f"step: derivation ({resolved}/{len(row['sources'])} sources resolved) {state}: {expr}")
        elif row["conditions"]:
            print(f"step: stored_fact FAIL {row['conditions']}: {expr}")
        elif not row["sources"][0]["resolved"]:
            src = row["sources"][0]
            print(f"step: stored_fact FAIL {src['conditions']}: {expr}")
        else:
            print(f"step: stored_fact OK: {expr}")
    hc = payload["handles_check"]
    print(f"handles_check: claimed={hc['claimed']} derived={hc['derived']} conditions={hc['conditions']}")
    if payload["per_predicate"]:
        summary = ", ".join(
            f"{sym}={len(bucket['expressions'])}"
            for sym, bucket in payload["per_predicate"].items()
        )
        print(f"per_predicate: {summary}")
    if payload["source_paths"]:
        print("source_paths:")
        for path in payload["source_paths"]:
            print(f"  {path}")
    if payload["conditions"]:
        print(f"missing ({len(payload['missing'])}):")
        for expr in payload["missing"]:
            print(f"  {_shorten(expr)}")
        print(f"verdict: FAIL (exit 2: some used stored fact's source is missing/unresolvable)")
    else:
        print("verdict: PASS (exit 0: all used stored facts' sources resolve)")


def _run(argv: list[str], sudo: bool) -> int:
    parser = _ArgumentParser(prog="reconstruct_sources.py")
    parser.add_argument("--trace-file")
    parser.add_argument("--trace")
    parser.add_argument("--ledger-repo", required=True)
    parser.add_argument("--facts")
    parser.add_argument("--handles")
    parser.add_argument("--mongo-container", default=DEFAULT_MONGO_CONTAINER)
    parser.add_argument("--case")
    parser.add_argument("--json")
    parser.add_argument("--source-paths-out")
    parser.add_argument("--background-dir")
    parser.add_argument("--legacy-repo")
    args = parser.parse_args(argv)

    if (args.trace_file is not None) == (args.trace is not None):
        raise UsageError(
            "exactly one of --trace-file <path> or --trace \"<s-exprs>\" is required"
        )
    if args.trace_file is not None:
        try:
            with open(args.trace_file, "r", encoding="utf-8") as f:
                trace_raw = f.read()
        except OSError as exc:
            raise HarnessError(f"trace unreadable: {exc}")
    else:
        trace_raw = args.trace

    ledger_repo = args.ledger_repo
    if not os.path.isdir(ledger_repo):
        raise HarnessError(f"ledger unreadable: {ledger_repo} is not a directory")
    probe = _git(ledger_repo, "rev-parse", "--git-dir", sudo=sudo)
    if not _run_ok(probe):
        raise HarnessError(
            "ledger unreadable: " + (probe.stderr.strip()[:200] or "not a git repo")
        )

    node_cls, link_cls = _factories()

    # Steps 1-2: split/validate the trace, classify steps, derive handles.
    steps: list[str] = []
    for position, segment in enumerate(trace_raw.split(";")):
        part = segment.strip()
        if not part:
            continue
        if not (part.startswith("(") and part.endswith(")")):
            raise HarnessError(
                "trace unparseable: segment "
                f"{position + 1} is not a parenthesized s-expression: {part[:120]!r}"
            )
        steps.append(normalize_expression(part))
    plans = [_plan_step(step, i, node_cls, link_cls) for i, step in enumerate(steps)]

    # Step 3: ONE logical mongo query for ALL distinct handles.
    distinct: list[str] = []
    seen_handles: set[str] = set()
    for plan in plans:
        for atom in plan["atoms"]:
            if atom["handle"] not in seen_handles:
                seen_handles.add(atom["handle"])
                distinct.append(atom["handle"])
    mongo_docs = _mongo_find_links(args.mongo_container, distinct) if distinct else {}

    # Steps 4-6: ledger chain (optional legacy/background) per stored atom.
    cache: dict = {}
    atom_results: dict[str, tuple[dict, list[str]]] = {}
    for handle in distinct:
        atom_results[handle] = _resolve_atom(
            mongo_docs.get(handle), ledger_repo, args.legacy_repo,
            sudo=sudo, background_dir=args.background_dir, cache=cache,
        )

    # Steps 9-10: per-expression / per-predicate aggregation, in trace order.
    per_expression: list[dict] = []
    per_predicate: dict[str, dict] = {}
    missing: list[str] = []
    blocking_all: list[str] = []
    source_paths: list[str] = []
    path_seen: set[str] = set()

    def record_path(entry: dict) -> None:
        if entry.get("resolved"):
            path = _source_path(entry, args.background_dir)
            if path not in path_seen:
                path_seen.add(path)
                source_paths.append(path)

    def predicate_symbol(expr: str) -> str:
        tree = metta_to_atoms.parse_expression(expr)
        return tree.elements[0].name

    def add_to_predicate(expr: str, entry: dict) -> None:
        symbol = predicate_symbol(expr)
        bucket = per_predicate.setdefault(symbol, {"expressions": [], "sources": []})
        if expr not in bucket["expressions"]:
            bucket["expressions"].append(expr)
        key = json.dumps(entry, sort_keys=True)
        if key not in {json.dumps(s, sort_keys=True) for s in bucket["sources"]}:
            bucket["sources"].append(entry)

    def note_blocking(expr: str, blocking: list[str]) -> None:
        if blocking:
            missing.append(expr)
            for cond in blocking:
                if cond not in blocking_all:
                    blocking_all.append(cond)

    for plan in plans:
        kind = plan["kind"]
        if kind in ("query_clause", "variable"):
            per_expression.append({
                "expr": plan["step"],
                "top_handle": None,
                "stored": False,
                "classification": kind,
                "sources": [],
                "conditions": [],
            })
            continue
        if kind == "fact":
            atom = plan["atoms"][0]
            handle = atom["handle"]
            if handle not in mongo_docs:
                per_expression.append({
                    "expr": plan["step"],
                    "top_handle": handle,
                    "stored": False,
                    "classification": "unstored",
                    "sources": [],
                    "conditions": [],
                })
                continue
            entry, blocking = atom_results[handle]
            per_expression.append({
                "expr": plan["step"],
                "top_handle": handle,
                "stored": True,
                "classification": "stored_fact",
                "sources": [entry],
                "conditions": blocking,
            })
            add_to_predicate(plan["step"], entry)
            record_path(entry)
            note_blocking(plan["step"], blocking)
            continue
        # derivation: sources = union of its stored components' sources;
        # variable-bearing components are exempt; unstored components
        # (exec/=> outputs are typically not written) carry no requirement.
        sources: list[dict] = []
        source_keys: set[str] = set()
        blocking: list[str] = []
        any_stored = False
        for atom in plan["atoms"]:
            handle = atom["handle"]
            if handle not in mongo_docs:
                continue
            any_stored = True
            entry, atom_blocking = atom_results[handle]
            key = json.dumps(entry, sort_keys=True)
            if key not in source_keys:
                source_keys.add(key)
                sources.append(entry)
            add_to_predicate(atom["expr"], entry)
            record_path(entry)
            for cond in atom_blocking:
                if cond not in blocking:
                    blocking.append(cond)
        per_expression.append({
            "expr": plan["step"],
            "top_handle": None,
            "stored": any_stored,
            "classification": "derivation",
            "sources": sources,
            "conditions": blocking,
        })
        note_blocking(plan["step"], blocking)

    handles_check = _handles_check(args.facts, args.handles, node_cls, link_cls)

    payload = {
        "per_expression": per_expression,
        "per_predicate": per_predicate,
        "handles_check": handles_check,
        "missing": missing,
        "conditions": blocking_all,
        "source_paths": source_paths,
    }
    if args.case:
        payload["case"] = args.case

    # Step 10: human summary always; JSON / source-paths files when asked.
    _print_summary(payload)
    if args.json:
        try:
            with open(args.json, "w", encoding="utf-8") as f:
                f.write(json.dumps(payload, indent=2) + "\n")
        except OSError as exc:
            raise HarnessError(f"cannot write --json output: {exc}")
    if args.source_paths_out:
        try:
            with open(args.source_paths_out, "w", encoding="utf-8") as f:
                f.write("".join(path + "\n" for path in source_paths))
        except OSError as exc:
            raise HarnessError(f"cannot write --source-paths-out output: {exc}")
    return 2 if blocking_all else 0


def run(argv: list[str] | None = None, sudo: bool | None = None) -> int:
    """Entry point returning the exit code (0/2/1); never calls sys.exit."""
    sudo = DEFAULT_SUDO if sudo is None else sudo
    try:
        return _run(list(sys.argv[1:] if argv is None else argv), sudo)
    except UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 1
    except HarnessError as exc:
        print(f"harness error: {exc}", file=sys.stderr)
        return 1
    except MettaParseError as exc:
        print(f"harness error: trace unparseable: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # internal error — never crash the harness
        print(f"internal error: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
