#!/usr/bin/env python3
"""Orchestrator CLI for the windowless-room GATING TEST (v3).

Runs ON the OVH host (operator: ``ssh -p 9022 ubuntu@100.84.81.96``) from the
synced repo directory (``tests/reasoning-windowless-room/``).

v3 (2026-10-23, Balazs directive): SEQUENTIAL STANDALONE QUESTION MODE —
one prompt, one question, graded independently, then the next question.
No example queries or per-case guidance in the agent prompt (the query
grammar lives in the das-retrieve skill description), an E-gate on clause
extraction, a DAS-cleanup phase before the run, a harness-side attestation
lane for the lossy history channel, and deterministic source reconstruction
via the Phase-4 ledger-chain script.

Phases: preflight, cleanup-das, setup-case, agent-case, grade-case,
full (sequential; --batch keeps the v2 all-at-once flow), grade, report,
teardown.

This is a strict pass/fail GATE, not a scored benchmark. A case passes only
if ALL gate conditions hold (no relaxation vs v2):

  A-gate  the FINAL ANSWER line exists and is substantively correct.
  Q-gate  the case was answered QUERY-FIRST: a real das-retrieve call in the
          case window, quoted in answers.md with its DAS_RETRIEVE_OK receipt,
          non-degenerate, re-issued by the harness with a matching count.
          If the (known-lossy) history channel collapsed the tuple, the
          harness-side attestation lane (query-engine pattern log +
          read-proxy access log) may attest the call instead — recorded as
          the informational condition Q_ATTESTED_VIA_ACCESS_LOG; the
          evidence standard is unchanged, the channel is not.
  E-gate  extraction: the facts index is non-empty, the first case shows a
          real ingest (a BRIDGE-PERSIST-OK receipt in its window), the
          case's FACTS line resolves against the index, and every quoted
          literal of the query comes from the extracted vocabulary.
  P-gate  deterministic source reconstruction (v17): per case the harness
          runs deploy/das/write-bridge/tools/reconstruct_sources.py (trace
          + FACTS + HANDLES in) and feeds its JSON payload to gate_case,
          which maps it to P_UNRESOLVED:<expr12>:<COND> / P_MISSING / H_*
          conditions; every resolved (ref, sha256) the chain found is
          byte-compared against the repo's background markdown
          (sha256(file) == entry sha256; refs mapping to no background
          file are recorded with byte_match=null — informational).

Grading is deterministic (regex/keyword parsing, string matching, HTTP
re-issue, git reads, docker-log reads) EXCEPT the A-gate answer-substance
judge (v16, directive 2026-10-26): one OpenAI chat-completions-compatible
call (llm_judge.py; default https://api.asi1.ai/v1 model asi1-ultra, the
same API key the Omega agent uses) built from ONE prompt containing the
test question, the agent's FINAL ANSWER line, and the expected correct
answer; the endpoint replies TRUE or FALSE. No other gate uses an LLM; a judge failure
emits A_JUDGE_UNAVAILABLE and fails the case (an ungraded answer can
never pass).

Exit codes (grade*/report/full): 0 = gate PASS, 2 = gate FAIL (the
expected negative signal), 1 = harness/environment error.

Restart invariant: the agent is restarted via
``sudo systemctl restart omega-curiosity.service`` — NOT ``docker restart`` —
because the unit's ``start.sh`` trap ``rm -f``'s the container (a docker
restart would destroy the container).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"

DEFAULT_MEMORY_VOLUME = "/var/lib/docker/volumes/omega-curiosity-memory/_data"
DEFAULT_PROVENANCE_REPO = "/home/ubuntu/omega-provenance"
DEFAULT_WRITE_BRIDGE = "http://172.20.0.5:8080"
DEFAULT_READ_PROXY = "http://172.20.0.3:8080"

CONTAINER_WRITE_BRIDGE = "omega-das-write-bridge-write-bridge-1"
CONTAINER_READ_PROXY = "omega-das-integration-read-proxy-1"
CONTAINER_QUERY_ENGINE = "omega-das-integration-query-engine-1"
CONTAINER_MONGODB = "omega-das-integration-mongodb-1"
CONTAINER_AGENT = "omega-curiosity"

GATE_PASS, GATE_FAIL, GATE_ERROR = 0, 2, 1

# benchmark dir inside the memory volume
BENCH_REL = "benchmark"
ANSWERS_REL = f"{BENCH_REL}/answers.md"
FACTS_INDEX_REL = f"{BENCH_REL}/facts-index.md"
URLS_REL = f"{BENCH_REL}/urls.txt"
# v11 (wr3j evidence): the prompt-rendered artifact paths must be
# MEMORY-VOLUME-RELATIVE, not benchmark-relative. The agent container's
# file tools (append-file/read-file) resolve relative paths against the
# container cwd /PeTTa, and /PeTTa/benchmark does not exist — the volume is
# mounted at /PeTTa/repos/Omega/memory. wr3j burned the case-1 window on
# 34+ APPEND-FAILED "file does not exist" loops before the agent
# self-worked-around via the repos/Omega/memory path. Shell `cat` calls
# resolved the same defect in earlier runs (wr3c "cwd disorientation,
# self-recovered"). The same in-container path works for ALL tools.
BENCH_PROMPT_REL = "repos/Omega/memory/benchmark"
ANSWERS_PROMPT_REL = f"{BENCH_PROMPT_REL}/answers.md"
FACTS_INDEX_PROMPT_REL = f"{BENCH_PROMPT_REL}/facts-index.md"
URLS_PROMPT_REL = f"{BENCH_PROMPT_REL}/urls.txt"

# v4 (lever 3 of the wr3b post-mortem, 2026-10-24): the stock agent appends
# every episode to history.metta and serializes the WHOLE file into every
# LLM request (~1.6 MB / ~32k prompt tokens per call at wr3b time). That
# starved the per-case cycle budget — the root cause of all four wr3/wr3b
# timeouts. The per-case history trim resets history.metta to this
# comment-only marker before each case window, so every LLM call of the
# case serializes only that case's episodes. The pre-case snapshot (taken
# immediately before the trim) archives the trimmed content; grading
# windows fall back to mode "full" (= current file content = this case).
def _trim_marker(run_id: str, case_id: str) -> str:
    """Comment-only MeTTa marker the per-case trim writes to history.metta."""
    return (
        f"; history trimmed by the benchmark harness (per-case window: run {run_id}, case {case_id})\n"
        "; prior episodes are archived in the pre/post-case snapshots under\n"
        "; results/<run-id>/windows/<case>/\n"
    )


def _http_post(url: str, body: dict, timeout: float = 30.0) -> dict:
    """POST a JSON body; return parsed response or raise."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _run(cmd: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
    """Run a subprocess with timeout; return the CompletedProcess."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _load_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sudo_read(path: Path, timeout: float = 60.0) -> str | None:
    """Read a (possibly root-owned) file via sudo; None on failure."""
    r = _run(["sudo", "cat", str(path)], timeout=timeout)
    return r.stdout if r.returncode == 0 else None


def _sudo_write(path: Path, content: str, timeout: float = 60.0) -> bool:
    """Write/replace a (possibly root-owned) file via sudo tee."""
    r = subprocess.run(["sudo", "tee", str(path)], input=content,
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode == 0


def _sudo_run(cmd: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess:
    return _run(["sudo", *cmd], timeout=timeout)


def _pick_agent_ip(ips: list[str], bridge_ip: str) -> str:
    """Pick the ONE agent IP the attestation lane matches against.

    The agent container is multi-network (default bridge + the facade
    client network), so docker inspect enumerates several addresses;
    the facade access logs only ever see the client-network one. Prefer
    the IP sharing the bridge's /24; otherwise fall back to the first.
    (Live defect, wr3i preflight 2026-10-25: "172.17.0.2172.20.0.6" made
    every attestation regex unmatchable — a passing run would have graded
    Q_NOT_IN_HISTORY + E_NO_INGEST false blocking conditions.)
    """
    if not ips:
        return ""
    if len(ips) == 1:
        return ips[0]
    prefix = bridge_ip.rsplit(".", 1)[0] if bridge_ip else ""
    for ip in ips:
        if prefix and ip.rsplit(".", 1)[0] == prefix:
            return ip
    return ips[0]


def _container_ip(container: str) -> str:
    try:
        result = _run([
            "docker", "inspect", "--format",
            "{{range $k, $v := .NetworkSettings.Networks}}{{$v.IPAddress}} {{end}}",
            container,
        ])
        ips = [ip for ip in result.stdout.split() if ip]
        if container == CONTAINER_AGENT:
            return _pick_agent_ip(ips, _container_ip(CONTAINER_WRITE_BRIDGE))
        return ips[0] if ips else ""
    except Exception:
        return ""


def _resolve_endpoints(args) -> None:
    wb_ip = _container_ip(CONTAINER_WRITE_BRIDGE)
    rp_ip = _container_ip(CONTAINER_READ_PROXY)
    if wb_ip:
        args.write_bridge = f"http://{wb_ip}:8080"
    if rp_ip:
        args.read_proxy = f"http://{rp_ip}:8080"


def _facts_mod():
    sys.path.insert(0, str(HERE))
    import facts as facts_mod
    return facts_mod


def _case_by_id(case_id: str) -> dict | None:
    for c in _facts_mod().TEST_CASES:
        if c["id"] == case_id:
            return c
    return None


def _bench_paths(args) -> dict[str, Path]:
    vol = Path(args.memory_volume)
    return {
        "vol": vol,
        "bench": vol / BENCH_REL,
        "answers": vol / ANSWERS_REL,
        "facts_index": vol / FACTS_INDEX_REL,
        "urls": vol / URLS_REL,
        "prompt": vol / "prompt.txt",
        "state": vol / "omega_state.md",
        "history": vol / "history.metta",
    }


# ---------------------------------------------------------------------------
# docker-log attestation lane (harness-side; the history channel is lossy)
# ---------------------------------------------------------------------------

def _docker_logs_since(container: str, since_iso: str, until_iso: str) -> str:
    """Read docker logs in [since, until] (both ISO-8601 UTC)."""
    r = _run(["docker", "logs", "--since", since_iso, "--until", until_iso,
              "--timestamps", container], timeout=60.0)
    return r.stdout + r.stderr


def _agent_query_count_in_window(since_iso: str, until_iso: str, agent_ip: str) -> int:
    """Count real POST /v1/query 200s from the agent IP in the window."""
    logs = _docker_logs_since(CONTAINER_READ_PROXY, since_iso, until_iso)
    return _count_query_posts(logs, agent_ip)


def _count_query_posts(logs: str, agent_ip: str) -> int:
    """Count agent-IP POST /v1/query 2xx lines in read-proxy access logs.

    v10 (wr3i evidence): the previous rf-string pattern was over-escaped
    (``HTTP/1\\\\.1`` and ``2\\\\d\\\\d`` demand literal backslashes in the
    log line), so the attested-retrieve lane read 0 for every window that
    contained real query traffic. Single-escaped form — matches the real
    log line ``... "POST /v1/query HTTP/1.1" 200 -``.
    """
    pat = re.compile(
        rf"http {re.escape(agent_ip)} \"POST /v1/query HTTP/1\.1\" 2\d\d"
    )
    return len(pat.findall(logs))


def _qe_pattern_in_window(since_iso: str, until_iso: str, query: str) -> bool:
    """Did the query-engine log carry this exact pattern in the window?

    QE logs print ``tokens: [(Inheritance (Concept "Fetch.ai") $X)]`` — the
    pattern with normalized spacing. We compare space-stripped forms to be
    robust to spacing differences.
    """
    logs = _docker_logs_since(CONTAINER_QUERY_ENGINE, since_iso, until_iso)
    stripped_query = re.sub(r"\s+", "", query)
    for m in re.finditer(r"tokens: \[([^\]]+)\]", logs):
        if re.sub(r"\s+", "", m.group(1)) == stripped_query:
            return True
    return False


def collect_attestation(args, case_id: str, since_iso: str, until_iso: str,
                        query: str) -> dict:
    """Harness-side attestation for one case window + query.

    QUERY-ONLY (resolution 6): the attestation lane is the read-proxy
    access log + QE pattern log attesting das-retrieve calls
    (Q_ATTESTED_VIA_ACCESS_LOG), covering the known history-channel
    observability gap (PeTTa superpose/collapse collapses tool tuples to
    $_). The write/archive facade-log census is dropped — E_NO_INGEST has
    been receipts-only since item 2 (BRIDGE-PERSIST-OK receipts extracted
    from the history window).
    """
    agent_ip = _container_ip(CONTAINER_AGENT)
    return {
        "case_id": case_id,
        "agent_ip": agent_ip,
        "access_count": _agent_query_count_in_window(since_iso, until_iso, agent_ip),
        "qe_pattern_match": _qe_pattern_in_window(since_iso, until_iso, query),
        "window": [since_iso, until_iso],
    }


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

def preflight(args) -> int:
    """Preflight phase: verify environment is ready for the benchmark."""
    _resolve_endpoints(args)
    print(f"[preflight] write_bridge={args.write_bridge} read_proxy={args.read_proxy}")

    checks: dict[str, str] = {}

    for container in [CONTAINER_WRITE_BRIDGE, CONTAINER_READ_PROXY,
                      CONTAINER_QUERY_ENGINE, CONTAINER_MONGODB, CONTAINER_AGENT]:
        if args.dry_run:
            checks[f"container_{container}"] = "dry-run"
        else:
            try:
                result = _run(["docker", "inspect", container])
                checks[f"container_{container}"] = "running" if result.returncode == 0 else "missing"
            except Exception as e:
                checks[f"container_{container}"] = f"error: {e}"

    ips = {}
    for name, container in [("write_bridge", CONTAINER_WRITE_BRIDGE),
                            ("read_proxy", CONTAINER_READ_PROXY),
                            ("agent", CONTAINER_AGENT)]:
        ips[name] = "dry-run" if args.dry_run else _container_ip(container)
        checks[f"{name}_ip"] = ips.get(name, "")

    if not args.dry_run:
        try:
            smoke = f'(BenchmarkPreflight (Concept "{args.run_id}"))'
            _http_post(args.write_bridge + "/v1/write", {
                "metta": smoke, "verify": True,
            }, timeout=30.0)
            checks["write_bridge_smoke"] = "ok"
            try:
                _run(["docker", "exec", "-w", "/app", CONTAINER_WRITE_BRIDGE,
                      "python", "cleanup.py", "--metta", smoke], timeout=180.0)
                checks["write_bridge_smoke_cleanup"] = "ok"
            except Exception as e:
                checks["write_bridge_smoke_cleanup"] = f"warn: {e}"
        except Exception as e:
            checks["write_bridge_smoke"] = f"error: {e}"

        try:
            resp = _http_post(args.read_proxy + "/v1/query", {
                "metta": "(Inheritance $X $Y)", "max_answers": 10,
            }, timeout=30.0)
            if "count" not in resp:
                raise RuntimeError(f"no count in response: {resp}")
            checks["read_proxy_query"] = "ok"
        except Exception as e:
            checks["read_proxy_query"] = f"error: {e}"

        try:
            result = _sudo_run(["git", "-c", f"safe.directory={args.provenance_repo}",
                                "-C", args.provenance_repo, "rev-parse", "--git-dir"])
            checks["provenance_repo"] = "ok" if result.returncode == 0 else "missing"
        except Exception as e:
            checks["provenance_repo"] = f"error: {e}"

        try:
            r = _sudo_run(["test", "-d", args.memory_volume])
            checks["memory_volume"] = "ok" if r.returncode == 0 else "missing"
        except Exception as e:
            checks["memory_volume"] = f"error: {e}"

        # v3: the per-run prompt backup must not pre-exist (fresh run-id rule)
        bp = Path(args.memory_volume) / f"prompt.txt.bak-pre-benchmark-{args.run_id}"
        checks["prompt_backup_fresh"] = "ok" if not _sudo_run(["test", "-f", str(bp)]).returncode == 0 else "EXISTS"

        # v3: skill-description upgrade deployed? (das-retrieve description
        # in the mounted plugin must carry the WHY/WHEN/HOW contract)
        try:
            plugin_path = "/home/ubuntu/low-cost-omega-setup/deploy/omega/plugins/das-read/das-read.metta"
            r = _run(["grep", "-c", "WHY: DAS is your persistent knowledge store", plugin_path])
            checks["skill_description_upgraded"] = "ok" if r.returncode == 0 and r.stdout.strip() != "0" else "MISSING"
        except Exception as e:
            checks["skill_description_upgraded"] = f"error: {e}"

        # v6: metta-grammar plugin deployed? (scenario-A/A2 lesson,
        # 2026-10-25: NAL/PLN operators are STRICTLY 2-ARGUMENT and the
        # atomspace is ephemeral between calls — the stock metta skill
        # description documents none of it, and the agent burned ~321
        # calls on never-matching 3+-arg forms. Two checks: the repo
        # artifact carries the contract, AND the running agent container
        # actually has the plugin mounted — the 10:04Z A2 launch failed
        # exactly because the live start.sh lacked the mount while the
        # repo file was fine (systemd unit runs /home/ubuntu/omega-
        # curiosity/start.sh, not the repo copy).
        try:
            plugin_path = "/home/ubuntu/low-cost-omega-setup/deploy/omega/plugins/metta-grammar/metta-grammar.metta"
            r = _run(["grep", "-c", "STRICTLY 2-ARGUMENT", plugin_path])
            checks["metta_skill_upgraded"] = "ok" if r.returncode == 0 and r.stdout.strip() != "0" else "MISSING"
        except Exception as e:
            checks["metta_skill_upgraded"] = f"error: {e}"
        try:
            r = _run(["docker", "exec", CONTAINER_AGENT, "test", "-f",
                      "/PeTTa/repos/Omega/plugins/metta-grammar/metta-grammar.metta"])
            checks["metta_plugin_mounted"] = "ok" if r.returncode == 0 else "missing"
        except Exception as e:
            checks["metta_plugin_mounted"] = f"error: {e}"

        # v3: Omega's native embedding memory (remember/query skills) needs
        # the chroma_db target dir to exist in the volume; the image's
        # /PeTTa/chroma_db symlink dangles otherwise and EVERY boot logs
        # Knowledge init failed (live evidence wr3-20261023).
        try:
            chroma_dir = Path(args.memory_volume) / "chroma_db"
            r = _sudo_run(["test", "-d", str(chroma_dir)])
            checks["chroma_memory_dir"] = "ok" if r.returncode == 0 else "missing (create: sudo mkdir -p <vol>/chroma_db && sudo chown 65534:65534 <vol>/chroma_db)"
        except Exception as e:
            checks["chroma_memory_dir"] = f"error: {e}"

        # v3: canary fact must resolve BEFORE the run (campaign atoms intact)
        try:
            resp = _http_post(args.read_proxy + "/v1/query", {
                "metta": '(Inheritance (Concept "Fetch.ai") $X)', "max_answers": 10,
            }, timeout=30.0)
            checks["canary_fetch_ai"] = f"count={resp.get('count', '?')}"
        except Exception as e:
            checks["canary_fetch_ai"] = f"error: {e}"

        # v16: the A-gate judge must be resolvable and answering BEFORE the
        # run starts — a dead judge would burn every 75-minute case window
        # on A_JUDGE_UNAVAILABLE.
        try:
            smoke_judge = _get_judge(args)
            ok_smoke, _ = smoke_judge(
                {"question": "What is 2 + 2?", "expected_answer": "4"}, "4")
            checks["judge_smoke"] = "ok" if ok_smoke else "judge answered FALSE on smoke"
        except Exception as e:
            checks["judge_smoke"] = f"error: {e}"
    else:
        checks["write_bridge_smoke"] = "dry-run"
        checks["read_proxy_query"] = "dry-run"
        checks["provenance_repo"] = "dry-run"
        checks["memory_volume"] = "dry-run"
        checks["prompt_backup_fresh"] = "dry-run"
        checks["skill_description_upgraded"] = "dry-run"
        checks["metta_skill_upgraded"] = "dry-run"
        checks["metta_plugin_mounted"] = "dry-run"
        checks["canary_fetch_ai"] = "dry-run"
        checks["judge_smoke"] = "dry-run"

    ok_values = {"ok", "running", "dry-run"}
    all_ok = all(
        v in ok_values or v.startswith("dry-run")
        or v.startswith("172.") or v.startswith("10.") or v.startswith("192.168.")
        or (v.startswith("count=") and v != "count=0")
        for v in checks.values()
    )

    print(f"[preflight] checks: {json.dumps(checks, indent=2)}")
    _write_json(RESULTS_DIR / args.run_id / "preflight.json", {"checks": checks, "all_ok": all_ok})

    if all_ok:
        print("[preflight] PASS")
        return 0
    print("[preflight] FAIL")
    return 1


# ---------------------------------------------------------------------------
# cleanup-das (v3): remove previous-run predicates from DAS, keep the rest
# ---------------------------------------------------------------------------

def _mongo_eval(js: str, timeout: float = 60.0) -> str:
    """Run a mongosh eval in the mongo container (root creds via container env)."""
    r = _run(["docker", "exec", CONTAINER_MONGODB, "sh", "-c",
              'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
              '--authenticationDatabase admin --quiet das --eval ' + shlex.quote(js)],
             timeout=timeout)
    return r.stdout


def _discover_benchmark_expressions() -> list[str]:
    """Discover benchmark-residue fact expressions in the DAS mongo store.

    Two nets (union), both read-only:
      N1: links whose custom_attributes.provenance_url contains the
          benchmark source URL base — every benchmark add-atom write is
          provenance-decorated by the facade (provenance v2.1), so this
          catches all agent-written benchmark facts, old and new.
      N2: links whose custom_attributes.metta_expression contains a
          high-confidence benchmark-ONLY literal (windowless-room,
          sloped-ceiling, observer-inside-room, ...) — catches undecorated
          residue (e.g. smoke facts or writes that skipped provenance).
          Literals that campaign/canary atoms might also use (generic words
          like room, ceiling, answer, requires) are deliberately NOT in
          this net.
    Campaign atoms, canaries, and x402/fetch facts match NEITHER net.
    """
    facts = _facts_mod()
    url_base = facts.SOURCE_URL_BASE

    js_n1 = (
        'const out = db.links.find({"custom_attributes.provenance_url": '
        '{$regex: ' + json.dumps(url_base) + '}}).toArray();'
        'print(JSON.stringify(out.map(d => d.custom_attributes.metta_expression)));'
    )
    n1_raw = _mongo_eval(js_n1)
    try:
        n1 = json.loads(n1_raw.strip().splitlines()[-1])
    except (ValueError, IndexError):
        n1 = []

    benchmark_only_literals = [
        "windowless-room", "sloped-ceiling", "observer-inside-room",
        "observer-inside-windowless-room", "observer-outdoors",
        "visible-when-looking-up", "blocks-view-of", "has-no-openings",
        "look-up-to-sky-association", "pattern-matching-failure",
        "phrase-association-without-scene-simulation", "scene-simulation",
        "nearest-surface-in-gaze", "room-interior", "room-surfaces",
        "exterior-light", "BenchmarkPreflight",
        # Expanded set (2026-10-23, live-validated against the campaign corpus:
        # a legacy undecorated fact — (Inheritance (Concept "sky") (Concept
        # "look-up-default")) — escaped the narrow net and was only caught by
        # a manual broad sweep. The expansion below matched ZERO campaign
        # atoms on the live DB. Generic meta-reasoning spellings
        # (reasoning-trace, reasoning-step, state-change) are deliberately
        # EXCLUDED: plausible AI-research vocabulary; undecorated future
        # writes are impossible anyway (the facade always decorates).
        "look-up-default", "room-part", "enclosed-space", "opaque-surface",
        "artificial-light-source", "dark-room", "light-source-type",
        "illuminates", "makes-visible", "propagates-through",
        "scene-construction", "visibility-query", "looking-up-inside",
    ]
    alt = "|".join(re.escape(l) for l in benchmark_only_literals)
    js_n2 = (
        'const out = db.links.find({"custom_attributes.metta_expression": '
        '{$regex: ' + json.dumps(alt) + '}}).toArray();'
        'print(JSON.stringify(out.map(d => d.custom_attributes.metta_expression)));'
    )
    n2_raw = _mongo_eval(js_n2)
    try:
        n2 = json.loads(n2_raw.strip().splitlines()[-1])
    except (ValueError, IndexError):
        n2 = []

    exprs = []
    seen = set()
    for e in list(n1) + list(n2):
        e = (e or "").strip()
        if e and e not in seen:
            seen.add(e)
            exprs.append(e)
    return exprs


def _read_proxy_origin() -> str:
    """Resolve the read-proxy origin from the live container IP."""
    ip = _container_ip(CONTAINER_READ_PROXY)
    return f"http://{ip}:8080" if ip else DEFAULT_READ_PROXY


def _canary_counts() -> dict:
    """Resolvable campaign facts that must be untouched by cleanup.

    (Inheritance (Concept "Fetch.ai") $X) is a live campaign atom, queried
    by the curiosity loop today — NOT benchmark vocabulary. Benchmark
    vocabulary like has-part must NOT be used as a canary (the cleanup is
    supposed to change those counts).
    """
    out = {}
    try:
        resp = _http_post(_read_proxy_origin() + "/v1/query",
                          {"metta": '(Inheritance (Concept "Fetch.ai") $X)',
                           "max_answers": 10}, timeout=30.0)
        out["fetch_ai_inheritance"] = resp.get("count", -1)
    except Exception as e:
        out["fetch_ai_inheritance"] = f"error: {e}"
    return out


def cleanup_das(args) -> int:
    """cleanup-das phase: delete previous-run benchmark predicates from DAS.

    Uses the bridge's cleanup.py (links-only deletion, alternate-pattern
    absence oracle, bounded standby — validated tooling) per discovered
    expression. Canaries + campaign atoms must be untouched (verified
    before/after). The delete apply is EVENTUAL; the oracle handles it.
    """
    _resolve_endpoints(args)
    print("[cleanup-das] discovering benchmark-residue expressions in mongo...")

    if args.dry_run:
        print("[cleanup-das] [dry-run] would: discover expressions, cleanup.py each "
              "(links-only), verify absence, verify canaries untouched")
        return 0

    data: dict = {"started": _now_iso()}

    data["mongo_counts_before"] = _mongo_eval(
        'print(JSON.stringify({nodes: db.nodes.countDocuments({}), links: db.links.countDocuments({})}));'
    ).strip()
    data["canaries_before"] = _canary_counts()

    exprs = _discover_benchmark_expressions()
    data["discovered_expressions"] = exprs
    data["discovered_count"] = len(exprs)
    print(f"[cleanup-das] discovered {len(exprs)} expressions")

    results = []
    for i, expr in enumerate(exprs):
        print(f"[cleanup-das] ({i + 1}/{len(exprs)}) cleanup: {expr}")
        r = _run(["docker", "exec", "-w", "/app", CONTAINER_WRITE_BRIDGE,
                  "python", "cleanup.py", "--metta", expr], timeout=600.0)
        entry = {"metta": expr, "returncode": r.returncode,
                 "stdout": r.stdout.strip()[-2000:], "stderr": r.stderr.strip()[-2000:]}
        results.append(entry)
        if r.returncode != 0:
            print(f"[cleanup-das]   FAILED rc={r.returncode}: {r.stderr.strip()[:200]}")

    data["cleanup_results"] = results

    data["mongo_counts_after"] = _mongo_eval(
        'print(JSON.stringify({nodes: db.nodes.countDocuments({}), links: db.links.countDocuments({})}));'
    ).strip()
    data["canaries_after"] = _canary_counts()

    # residue check: the discovery nets must come back empty now
    remaining = _discover_benchmark_expressions()
    data["remaining_expressions"] = remaining
    data["remaining_count"] = len(remaining)

    data["canaries_intact"] = (
        data["canaries_before"] == data["canaries_after"]
        and all(isinstance(v, int) and v >= 1 for v in data["canaries_after"].values())
    )
    data["finished"] = _now_iso()

    _write_json(RESULTS_DIR / args.run_id / "cleanup-das.json", data)
    print(f"[cleanup-das] done: {len(exprs)} cleaned, {len(remaining)} remaining, "
          f"canaries_intact={data['canaries_intact']}")

    if remaining:
        print("[cleanup-das] WARNING: residue still discoverable — inspect cleanup-das.json")
        return 1
    if not data["canaries_intact"]:
        print("[cleanup-das] WARNING: canary counts changed — campaign atoms may be damaged")
        return 1
    return 0


# ---------------------------------------------------------------------------
# setup (batch, v2 semantics) — kept for --batch mode
# ---------------------------------------------------------------------------

def _render_prompts_txt(here: Path) -> str:
    """Build benchmark prompts.txt content from facts.TEST_CASES (batch mode).

    NOTE: case["prompt_file"] is repo-relative ("prompts/<name>.md") and must
    NOT be re-prefixed — the double-join shipped empty bodies live once.
    """
    facts_mod = _facts_mod()
    lines: list[str] = []
    for case in facts_mod.TEST_CASES:
        pf = here / case["prompt_file"]
        text = pf.read_text(encoding="utf-8") if pf.exists() else ""
        if not text.strip():
            raise FileNotFoundError(
                f"prompt file empty or missing: {pf} (case {case['id']})")
        lines.append(f"=== CASE: {case['id']} ===")
        lines.append(text)
        lines.append(f"ANSWER FORMAT: FINAL ANSWER ({case['id']}): <answer>")
        lines.append("")
    return "\n".join(lines)


def _render_case_prompt(args, case: dict) -> str:
    """Render agent_prompt_template.md for ONE standalone case question."""
    paths = _bench_paths(args)
    template = (HERE / "agent_prompt_template.md").read_text(encoding="utf-8")
    return (template
            .replace("{{RUN_ID}}", args.run_id)
            .replace("{{CASE_ID}}", case["id"])
            .replace("{{QUESTION}}", case["question"])
            .replace("{{URL_LIST_PATH}}", URLS_PROMPT_REL)
            .replace("{{ANSWERS_PATH}}", ANSWERS_PROMPT_REL)
            .replace("{{FACTS_INDEX_PATH}}", FACTS_INDEX_PROMPT_REL))


def _agent_restart() -> bool:
    r = _sudo_run(["systemctl", "restart", "omega-curiosity.service"], timeout=180.0)
    return r.returncode == 0


def _prepare_benchmark_dir(args) -> None:
    """Idempotent benchmark dir: background files, urls.txt, answers.md,
    facts-index.md (fresh at run start)."""
    paths = _bench_paths(args)
    facts_mod = _facts_mod()
    _sudo_run(["mkdir", "-p", str(paths["bench"] / "background")])
    for f in sorted((HERE / "background").glob("*.md")):
        _sudo_run(["cp", str(f), str(paths["bench"] / "background" / f.name)])
    _sudo_write(paths["urls"], "\n".join(facts_mod.SOURCE_URLS.values()) + "\n")


# ---------------------------------------------------------------------------
# sequential per-case phases (v3 default)
# ---------------------------------------------------------------------------

def setup_case(args) -> int:
    """Install ONE case's standalone question prompt; restart the agent."""
    case = _case_by_id(args.case)
    if case is None:
        print(f"[setup-case] ERROR: unknown case id {args.case}")
        return GATE_ERROR
    paths = _bench_paths(args)
    facts_mod = _facts_mod()

    if args.dry_run:
        print(f"[setup-case] [dry-run] case {args.case}: prepare benchmark dir, "
              "backup prompt/state/history (run start), snapshot history, "
              "install rendered case prompt, "
              + ("trim history to the per-case window marker"
                 if getattr(args, "trim_history", True) else "keep full history")
              + ", restart agent")
        return 0

    first = args.case == facts_mod.TEST_CASES[0]["id"]
    _prepare_benchmark_dir(args)

    # v4: run-start initialization happens on THIS RUN's first setup-case,
    # whichever case id that is. A continuation run (--cases without
    # `original`, e.g. the remaining five cases after a 2/2 PASS) starts
    # mid-sequence: the backups must still be created — its teardown must be
    # able to restore standby — but answers.md / facts-index.md are NOT
    # re-initialized: the accumulated extraction record is exactly the
    # cross-case carry-over the E-gate checks query literals against.
    # Backups are keyed by run-id; prompt_backup_fresh in preflight enforces
    # a fresh run-id, so a missing backup here means "run start".
    backup_prompt = paths["vol"] / f"prompt.txt.bak-pre-benchmark-{args.run_id}"
    if _sudo_run(["test", "-f", str(backup_prompt)]).returncode != 0:
        _sudo_run(["cp", str(paths["prompt"]),
                   str(backup_prompt)])
        _sudo_run(["cp", str(paths["state"]),
                   str(paths["vol"] / f"omega_state.md.bak-pre-benchmark-{args.run_id}")])
        # v4 (lever 3): one-time backup of the FULL pre-run history so
        # teardown can restore the agent's memory byte-identically after
        # the per-case trims (the trim modifies the agent-owned history
        # file during the run; the benchmark must leave no trace).
        # NOTE: distinct from the batch-mode window snapshot
        # history.pre-benchmark-<run-id>.metta (window boundary semantics).
        if getattr(args, "trim_history", True):
            hist_bak = paths["vol"] / f"history.bak-pre-benchmark-{args.run_id}"
            if not _sudo_run(["cp", str(paths["history"]), str(hist_bak)]).returncode == 0:
                print("[setup-case] ERROR: history backup failed — refusing to trim")
                return GATE_ERROR
        # benchmark dir must be writable by the agent (nobody:nogroup)
        _sudo_run(["chown", "-R", "65534:65534", str(paths["bench"])])

    if first:
        # fresh answers.md + facts-index.md at run start (a run that
        # INCLUDES `original` starts from scratch: cleanup-das enforces a
        # clean store, so extraction must begin anew)
        _sudo_write(paths["answers"],
                    f"# Benchmark answers — {args.run_id} (sequential standalone questions)\n")
        _sudo_write(paths["facts_index"],
                    f"# Extraction record — {args.run_id}\n"
                    "# One persisted predicate expression per line (append after each add-atom).\n")

    # per-case history snapshot (defines this case's window start)
    snap = paths["vol"] / f"history.pre-case-{args.run_id}-{args.case}.metta"
    _sudo_run(["cp", str(paths["history"]), str(snap)])

    # v4 (lever 3): per-case history trim. The snapshot above archives the
    # prior content; resetting history.metta to the comment-only marker means
    # every LLM call of this case serializes ONLY this case's episodes
    # (root cause of the wr3/wr3b timeouts: ~1.6 MB day-history in every
    # request starved the cycle budget). --no-trim-history keeps the v3
    # behavior (full serialized history).
    trimmed = False
    if getattr(args, "trim_history", True):
        if not _sudo_write(paths["history"], _trim_marker(args.run_id, args.case)):
            print(f"[setup-case] ERROR: history trim failed (case {args.case})")
            return GATE_ERROR
        trimmed = True
        print(f"[setup-case] history trimmed to the per-case window marker "
              f"(case {args.case}; prior content archived in {snap.name})")

    rendered = _render_case_prompt(args, case)
    if not _sudo_write(paths["prompt"], rendered):
        print(f"[setup-case] ERROR: could not write prompt for case {args.case}")
        return GATE_ERROR
    if not _sudo_write(paths["state"],
                       f"BENCHMARK MODE ACTIVE — run {args.run_id}, case {args.case}\n"):
        print(f"[setup-case] ERROR: could not write omega_state.md")
        return GATE_ERROR

    if not _agent_restart():
        print(f"[setup-case] ERROR: agent restart failed (case {args.case})")
        return GATE_ERROR

    _write_json(RESULTS_DIR / args.run_id / f"setup-case-{args.case}.json", {
        "case_id": args.case, "prompt_installed": True,
        "window_start_snapshot": str(snap), "restarted_at": _now_iso(),
        "history_trimmed": trimmed,
    })
    print(f"[setup-case] case {args.case} prompt installed; agent restarted")
    return 0


def agent_case(args) -> int:
    """Wait for THIS case's FINAL ANSWER line in answers.md."""
    case = _case_by_id(args.case)
    if case is None:
        return GATE_ERROR
    paths = _bench_paths(args)
    marker = f"FINAL ANSWER ({args.case}):"
    timeout_s = args.timeout_minutes * 60
    start = time.time()
    print(f"[agent-case] waiting for '{marker}' (timeout {args.timeout_minutes}m)")

    if args.dry_run:
        print(f"[agent-case] [dry-run] would poll answers.md for the marker")
        return 0

    while time.time() - start < timeout_s:
        content = _sudo_read(paths["answers"])
        if content is not None and marker in content:
            # post snapshot bounds this case's window
            post = paths["vol"] / f"history.post-case-{args.run_id}-{args.case}.metta"
            _sudo_run(["cp", str(paths["history"]), str(post)])
            elapsed = int(time.time() - start)
            print(f"[agent-case] case {args.case} answered after {elapsed}s")
            _write_json(RESULTS_DIR / args.run_id / f"agent-case-{args.case}.json", {
                "case_id": args.case, "status": "complete", "elapsed_s": elapsed,
                "post_snapshot": str(post),
            })
            return 0
        time.sleep(30)

    post = paths["vol"] / f"history.post-case-{args.run_id}-{args.case}.metta"
    _sudo_run(["cp", str(paths["history"]), str(post)])
    print(f"[agent-case] TIMEOUT on case {args.case}")
    _write_json(RESULTS_DIR / args.run_id / f"agent-case-{args.case}.json", {
        "case_id": args.case, "status": "timeout", "post_snapshot": str(post),
    })
    return 1


def _read_facts_index(args) -> str:
    paths = _bench_paths(args)
    override = getattr(args, "facts_index_override", "") or ""
    if override:
        try:
            return Path(override).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return _sudo_read(Path(override)) or ""
    return _sudo_read(paths["facts_index"]) or ""


# ---------------------------------------------------------------------------
# P-gate reconstruction lane (v17 item 4): the Phase-4 script, per case
# ---------------------------------------------------------------------------

RECONSTRUCT_SCRIPT = (Path(__file__).resolve().parents[2]
                      / "deploy" / "das" / "write-bridge" / "tools"
                      / "reconstruct_sources.py")
RECONSTRUCTION_TIMEOUT = 300.0


def _case_source_refs(case_id: str) -> set[str]:
    """The case's allowed source refs: the background SOURCE_URLS of the
    canonical facts the case requires (gate_case compares the
    reconstruction's stored refs against this set for the informational
    P_SOURCE_SET_MISMATCH)."""
    facts_mod = _facts_mod()
    return {facts_mod.SOURCE_URLS[f["source_file"]]
            for f in facts_mod.CANONICAL_FACTS
            if case_id in f.get("requires", [])}


def _run_reconstruction(args, case_id: str, block, artifacts_dir: Path) -> dict | None:
    """Run the Phase-4 reconstruction script for one case; return its JSON
    payload (script exit 0 or 2 — the coarse source verdict; the exact
    conditions ride in the payload) or None when the case block is
    missing (the gate's missing-block shorthand already emits P_MISSING).

    Script exit 1 / subprocess error / unreadable payload is a HARNESS
    ERROR: raised as RuntimeError so the grade command aborts through
    its existing error path (exit 1) — no gate condition is invented
    for it. The --json / --source-paths-out artifacts stay in the run
    dir as evidence. The legacy fallback repo is never passed
    (resolution 4: optional-informational only, never in the default
    grade path).
    """
    if block is None:
        return None
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    json_out = artifacts_dir / f"reconstruction-{case_id}.json"
    paths_out = artifacts_dir / f"reconstruction-{case_id}.paths"
    cmd = [
        sys.executable, str(RECONSTRUCT_SCRIPT),
        "--trace", block.reasoning_raw,
        "--facts", block.facts_raw,
        "--handles", block.handles_raw,
        "--ledger-repo", args.provenance_repo,
        "--case", case_id,
        "--json", str(json_out),
        "--source-paths-out", str(paths_out),
        "--background-dir", str(HERE / "background"),
        "--mongo-container", CONTAINER_MONGODB,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=RECONSTRUCTION_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as e:
        raise RuntimeError(f"reconstruction script failed to run: {e}") from e
    if proc.returncode not in (0, 2):
        detail = (proc.stderr or proc.stdout).strip()[:500]
        raise RuntimeError(
            f"reconstruction harness error (rc {proc.returncode}): {detail}")
    payload = _load_json(json_out)
    if payload is None:
        raise RuntimeError(f"reconstruction payload unreadable: {json_out}")
    return payload


def _byte_compare_rows(payload: dict,
                       background_dir: Path | None = None) -> list[dict]:
    """Byte-compare lane rows: for each unique (commit, ref, sha256) among
    the payload's stored-atom source entries (stored_fact rows plus
    derivation rows, whose sources are their stored components'; query/
    exec rows carry none), hash the repo background file the ref names and
    compare it to the entry's sha256 (sha256(background file) ==
    entry sha256 — spec §8 item 4). Refs mapping to no background file
    record byte_match=None (recorded, informational only). The script's
    source_paths (payload["source_paths"] + the .paths artifact kept in
    the run dir) record which local files the chain itself used.
    """
    if background_dir is None:
        background_dir = HERE / "background"
    rows: list[dict] = []
    seen: set[tuple] = set()
    for row in payload.get("per_expression") or []:
        for src in row.get("sources") or []:
            key = (src.get("commit"), src.get("ref"), src.get("sha256"))
            if key in seen:
                continue
            seen.add(key)
            ref = src.get("ref") or ""
            fname = ref.rsplit("/", 1)[-1] if ref else ""
            bg = background_dir / fname if fname else None
            entry = {
                "ref": ref,
                "sha256": src.get("sha256"),
                "commit": src.get("commit"),
                "entry_date": src.get("entry_date"),
                "resolved": src.get("resolved"),
                "conditions": src.get("conditions") or [],
                "byte_match": None,
            }
            if bg is not None and bg.is_file():
                entry["byte_match"] = (
                    hashlib.sha256(bg.read_bytes()).hexdigest() == src.get("sha256")
                )
            rows.append(entry)
    return rows


def _reconstruction_lane(payload: dict | None) -> dict | None:
    """grade_data["reconstruction"] view (None when the case block was
    missing). script_exit mirrors the script's own exit rule
    (reconstruct_sources.py: 2 iff any blocking condition, else 0; H_*
    never affect it — D4)."""
    if payload is None:
        return None
    return {
        "script_exit": 2 if payload.get("conditions") else 0,
        "payload": payload,
        "byte_compare": _byte_compare_rows(payload),
    }


# ---------------------------------------------------------------------------
# A-gate LLM judge (v15b): one chat-completions call per graded case
# ---------------------------------------------------------------------------

_BUILT_JUDGE: dict[str, object] = {}


def _get_judge(args):
    """A-gate judge callable; None in dry-run. Built lazily on the first
    graded case so a missing/unresolvable key surfaces per-case as
    A_JUDGE_UNAVAILABLE (grade_answer catches), never as a crash."""
    if getattr(args, "dry_run", False):
        return None

    def _lazy_judge(case: dict, final_answer: str):
        if "judge" not in _BUILT_JUDGE:
            import llm_judge
            _BUILT_JUDGE["judge"] = llm_judge.make_judge(
                base_url=(getattr(args, "judge_base_url", "")
                          or llm_judge.DEFAULT_BASE_URL),
                model=(getattr(args, "judge_model", "")
                       or llm_judge.DEFAULT_MODEL),
                api_key=getattr(args, "judge_api_key", ""),
                timeout=(float(getattr(args, "judge_timeout", 0) or 0)
                         or llm_judge.DEFAULT_TIMEOUT),
            )
        return _BUILT_JUDGE["judge"](case, final_answer)

    return _lazy_judge


def grade_case(args) -> int:
    """Grade ONE case independently (A/Q/E/R/P gate; A-substance via the
    LLM judge, everything else deterministic; P from the Phase-4
    reconstruction script's JSON payload)."""
    sys.path.insert(0, str(HERE))
    import grading as grading_mod
    import history_parse

    case = _case_by_id(args.case)
    if case is None:
        return GATE_ERROR
    _resolve_endpoints(args)
    paths = _bench_paths(args)
    rd = RESULTS_DIR / args.run_id

    if args.dry_run:
        print(f"[grade-case] [dry-run] would gate case {args.case} (A/Q/E/R/P)")
        return 0

    answers = _sudo_read(paths["answers"]) or ""
    history = _sudo_read(paths["history"]) or ""
    pre_snap = _sudo_read(paths["vol"] / f"history.pre-case-{args.run_id}-{args.case}.metta")
    post_snap = _sudo_read(paths["vol"] / f"history.post-case-{args.run_id}-{args.case}.metta")
    if pre_snap is None:
        print(f"[grade-case] ERROR: no pre-case snapshot for {args.case}")
        _write_json(rd / f"grade-case-{args.case}.json", {"error": "no pre-case snapshot"})
        return GATE_ERROR

    window_text, window_mode = history_parse.window_from_texts(history, pre_snap, post_snap)
    history_queries = history_parse.extract_retrieve_args(window_text)
    placeholder_calls = history_parse.count_placeholder_retrieves(window_text)
    persist_receipts = history_parse.extract_persist_receipts(window_text)
    archive_receipts = history_parse.extract_archive_receipts(window_text)
    add_atom_shas = history_parse.extract_add_atom_shas(window_text)

    facts_index_text = _read_facts_index(args)
    facts_index = grading_mod.parse_facts_index(facts_index_text)

    # parse this case's block from answers.md
    blocks = grading_mod.parse_answers_v2(answers)
    block = blocks.get(args.case)

    # P-gate input: the Phase-4 reconstruction script's JSON payload for
    # this case (trace + FACTS + HANDLES in; conditions out). Harness
    # error (rc 1 / unreadable payload) aborts the grade command.
    try:
        recon_payload = _run_reconstruction(args, args.case, block, rd)
    except RuntimeError as e:
        print(f"[grade-case] ERROR: {e}")
        _write_json(rd / f"grade-case-{args.case}.json", {"error": str(e)})
        return GATE_ERROR

    def reissue(query: str) -> dict:
        try:
            resp = _http_post(args.read_proxy + "/v1/query",
                              {"metta": query, "max_answers": 10}, timeout=30.0)
            return {"count": int(resp.get("count", 0))}
        except Exception as e:
            return {"error": str(e)}

    # attestation lane: window = [setup restart, now]. v9: ALWAYS
    # collected — the history channel collapses tool calls to $_ (wr3h:
    # 100% placeholder tuples), so the attestation lane is QUERY-ONLY
    # (read-proxy access log + QE pattern log ->
    # Q_ATTESTED_VIA_ACCESS_LOG; the write/archive facade-log census is
    # dropped, resolution 6 — E_NO_INGEST is receipts-only). The
    # query-specific qe_pattern_match stays conditional on the block
    # naming a query (empty query -> False, so Q_NOT_IN_HISTORY semantics
    # are unchanged).
    since_iso = None
    setup_json = _load_json(rd / f"setup-case-{args.case}.json") or {}
    since_iso = setup_json.get("restarted_at") or _now_iso()
    att_query = (history_parse.normalize_query(block.queries[0])
                 if (block is not None and block.queries) else "")
    attestation = collect_attestation(
        args, args.case, since_iso, _now_iso(), att_query)

    r = grading_mod.gate_case(
        case, block, history_queries, placeholder_calls, reissue,
        reconstruction=recon_payload,
        case_source_refs=_case_source_refs(args.case),
        facts_index=facts_index,
        window_persist_receipts=len(persist_receipts),
        attestation=attestation,
        facts_index_raw=facts_index_text,
        presence_fn=reissue,
        judge_fn=_get_judge(args),
    )

    # byte-compare lane: for each unique (commit, ref, sha256) the
    # reconstruction chain found, hash the background file the ref names
    # and compare it to the entry's sha256 (evidence, not a condition —
    # a failed resolution already blocks via P_UNRESOLVED)
    reconstruction_lane = _reconstruction_lane(recon_payload)

    grade_data = {
        "run_id": args.run_id,
        "case_id": args.case,
        "verdict": r.verdict,
        "conditions": r.conditions,
        "detail": r.detail,
        "history_window": {
            "mode": window_mode,
            "retrieve_calls": len(history_queries),
            "retrieve_args": history_queries[:20],
            "placeholder_calls": placeholder_calls,
            "persist_receipts": len(persist_receipts),
            "archive_receipts": len(archive_receipts),
            "add_atom_shas": add_atom_shas[:20],
            "attested_retrieve_calls": attestation["access_count"],
        },
        "facts_index_size": len(facts_index),
        "attestation": attestation,
        "reconstruction": reconstruction_lane,
        "timestamp": _now_iso(),
    }
    _write_json(rd / f"grade-case-{args.case}.json", grade_data)
    conds = ", ".join(r.conditions) or "-"
    print(f"[grade-case] {args.case}: {r.verdict} ({conds})")
    return GATE_PASS if r.verdict == "PASS" else GATE_FAIL


def teardown(args) -> int:
    """Teardown phase: restore agent to standby (contamination guard kept)."""
    paths = _bench_paths(args)
    if args.dry_run:
        print(f"[teardown] [dry-run] contamination guard, restore prompt/state, "
              "restore history from the pre-benchmark backup (v4 trim), "
              "restart, optionally remove per-case volume snapshots")
        return 0

    try:
        backup_prompt = paths["vol"] / f"prompt.txt.bak-pre-benchmark-{args.run_id}"
        # no backup => benchmark mode was never installed (early harness
        # failure): nothing to restore, agent is still on standby
        if _sudo_run(["test", "-f", str(backup_prompt)]).returncode != 0:
            print("[teardown] no backup prompt (setup never ran) — nothing to restore")
            _write_json(RESULTS_DIR / args.run_id / "teardown.json", {
                "restored": False, "skipped_reason": "no backup (setup never ran)",
                "timestamp": _now_iso(),
            })
            return 0
        backup_text = _sudo_read(backup_prompt) or ""
        if "BENCHMARK MODE" in backup_text and not getattr(args, "allow_dirty_backup", False):
            print("[teardown] ABORT: backup prompt contaminated — refusing to restore it")
            _write_json(RESULTS_DIR / args.run_id / "teardown.json", {
                "error": "backup prompt contaminated with benchmark content",
                "aborted": True,
            })
            return 1

        _sudo_run(["cp", str(backup_prompt), str(paths["prompt"])])
        _sudo_run(["cp", str(paths["vol"] / f"omega_state.md.bak-pre-benchmark-{args.run_id}"),
                   str(paths["state"])])
        subprocess.run(
            ["sudo", "tee", "-a", str(paths["state"])],
            input=f"\nbenchmark complete ({args.run_id}), returned to standby\n",
            capture_output=True, text=True, timeout=30.0,
        )
        # v4 (lever 3): restore the pre-run history the per-case trims
        # replaced. The full pre-run history is archived to results/ first
        # (forensic evidence: the trimmed-away episodes), then restored to
        # the volume and the backup removed. Absent backup (no-trim run,
        # or run failed before the first setup-case) = nothing to restore.
        hist_bak = paths["vol"] / f"history.bak-pre-benchmark-{args.run_id}"
        if _sudo_run(["test", "-f", str(hist_bak)]).returncode == 0:
            rd = RESULTS_DIR / args.run_id
            rd.mkdir(parents=True, exist_ok=True)
            # archive via read+write (results/ is harness-owned; _sudo_run cp
            # would also work but read+write keeps the archive in the same
            # code path as _write_json and is unit-testable without sudo)
            pre_run = _sudo_read(hist_bak) or ""
            (rd / "history.pre-run.metta").write_text(pre_run, encoding="utf-8")
            _sudo_run(["cp", str(hist_bak), str(paths["history"])])
            _sudo_run(["rm", "-f", str(hist_bak)])
            print("[teardown] history restored from the pre-benchmark backup "
                  "(per-case trim reverted)")
        if not _agent_restart():
            print("[teardown] ERROR: agent restart failed")
            return 1

        # per-case snapshots were copied into results at grade time; remove
        # the volume copies to keep the memory volume bounded. NOTE: the
        # volume dir is root-owned (drwx-----x) — glob as ubuntu fails with
        # EACCES (live wr3-20261023), so list via sudo instead.
        if not getattr(args, "keep_snapshots", False):
            r = _sudo_run(["sh", "-c",
                           rf"ls -1 '{paths['vol']}' | grep -E '^history\.(pre|post)-case-{re.escape(args.run_id)}-'"],
                          timeout=30.0)
            for name in (r.stdout or "").split():
                _sudo_run(["rm", "-f", str(paths["vol"] / name)])
    except Exception as e:
        print(f"[teardown] ERROR: {e}")
        _write_json(RESULTS_DIR / args.run_id / "teardown.json", {"error": str(e)})
        return 1

    _write_json(RESULTS_DIR / args.run_id / "teardown.json", {
        "restored": True, "timestamp": _now_iso(),
    })
    print("[teardown] agent restored to standby")
    return 0


# ---------------------------------------------------------------------------
# full (v3 sequential default; --batch keeps the v2 all-at-once flow)
# ---------------------------------------------------------------------------

def _copy_window_artifacts(args, case_id: str) -> None:
    """Copy the per-case volume snapshots into results/ before teardown
    removes them (grade_case reads them live; report reads the copies)."""
    paths = _bench_paths(args)
    rd = RESULTS_DIR / args.run_id / "windows" / case_id
    rd.mkdir(parents=True, exist_ok=True)
    for kind in ("pre", "post"):
        src = paths["vol"] / f"history.{kind}-case-{args.run_id}-{case_id}.metta"
        if _sudo_run(["test", "-f", str(src)]).returncode == 0:
            _sudo_run(["cp", str(src), str(rd / f"{kind}.metta")])


def full_sequential(args) -> int:
    """v3 default: preflight -> cleanup-das -> per case (setup/agent/grade,
    independent) -> report -> teardown (always).

    --cases limits the sequence to a subset (e.g. "original,false") —
    the iteration mode: relaunch only the cases under test.
    """
    facts_mod = _facts_mod()
    all_ids = [c["id"] for c in facts_mod.TEST_CASES]
    if getattr(args, "cases", ""):
        wanted = [c.strip() for c in args.cases.split(",") if c.strip()]
        unknown = [c for c in wanted if c not in all_ids]
        if unknown:
            print(f"[full] ERROR: unknown case ids in --cases: {unknown} (valid: {all_ids})")
            return GATE_ERROR
        case_ids = [c for c in all_ids if c in set(wanted)]
        print(f"[full] --cases filter active: running {case_ids}")
    else:
        case_ids = list(all_ids)
    gate_exit = GATE_PASS
    harness_error = False

    phases = [("preflight", preflight), ("cleanup-das", cleanup_das)]
    for name, fn in phases:
        print(f"\n[full] === {name} ===")
        out = RESULTS_DIR / args.run_id / f"{name}.json"
        if out.exists() and not args.force:
            print(f"[full] {name}.json exists — skipping (--force re-runs)")
            continue
        rc = fn(args)
        if rc != 0:
            print(f"[full] {name} FAILED (exit {rc})")
            harness_error = True
            break

    per_case = {}
    if not harness_error:
        for case_id in case_ids:
            print(f"\n[full] === CASE {case_id} ===")
            args.case = case_id  # per-case phases read args.case
            rc = setup_case(args)
            if rc != 0:
                harness_error = True
                per_case[case_id] = {"verdict": "ERROR", "phase": "setup"}
                continue
            rc = agent_case(args)
            if rc != 0:
                # timeout is a case failure, not a harness error
                print(f"[full] case {case_id}: agent timeout — grading anyway")
            rc = grade_case(args)
            _copy_window_artifacts(args, case_id)
            g = _load_json(RESULTS_DIR / args.run_id / f"grade-case-{case_id}.json") or {}
            per_case[case_id] = {
                "verdict": g.get("verdict", "FAIL"),
                "conditions": g.get("conditions", []),
            }
            if rc == GATE_ERROR:
                harness_error = True
            elif rc == GATE_FAIL:
                gate_exit = GATE_FAIL
            # every case graded independently; continue to the next regardless

    cases_passed = sum(1 for v in per_case.values() if v.get("verdict") == "PASS")
    summary = {
        "run_id": args.run_id,
        "mode": "sequential",
        "gate_verdict": "PASS" if (cases_passed == len(case_ids) and not harness_error) else "FAIL",
        "cases_passed": cases_passed,
        "cases_total": len(case_ids),
        "per_case": per_case,
        "timestamp": _now_iso(),
    }
    _write_json(RESULTS_DIR / args.run_id / "grade.json", summary)

    if not args.skip_report:
        print("\n[full] === report ===")
        report(args)

    print("\n[full] === teardown ===")
    td_rc = teardown(args)
    if td_rc != 0:
        harness_error = True

    if harness_error:
        print("\n[full] HARNESS ERROR — see logs above")
        return GATE_ERROR
    print(f"\n[full] GATE SIGNAL: {'PASS (0)' if gate_exit == GATE_PASS else 'FAIL (2)'}")
    return gate_exit


# ---------------------------------------------------------------------------
# batch grade (offline re-grade of a whole answers.md; v2 semantics + E/P)
# ---------------------------------------------------------------------------

def grade(args) -> int:
    """Batch grade: gate every case in answers.md (offline re-grades OK)."""
    sys.path.insert(0, str(HERE))
    import grading as grading_mod
    import history_parse

    if args.dry_run:
        print("[grade] [dry-run] would apply the strict gate (A/Q/E/R/P) to answers.md")
        return 0

    _resolve_endpoints(args)
    facts_mod = _facts_mod()
    paths = _bench_paths(args)

    def _read_input(explicit: str | None, default: Path) -> str | None:
        if explicit:
            try:
                return Path(explicit).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return _sudo_read(Path(explicit))
        return _sudo_read(default)

    content = _read_input(getattr(args, "answers_override", "") or None,
                          paths["answers"])
    if content is None:
        print("[grade] ERROR: answers file not readable")
        _write_json(RESULTS_DIR / args.run_id / "grade.json",
                    {"error": "answers file not readable"})
        return GATE_ERROR

    history = _read_input(getattr(args, "history_override", "") or None,
                          paths["history"]) or ""
    pre_snap = _read_input(getattr(args, "pre_snapshot_override", "") or None,
                           paths["vol"] / f"history.pre-benchmark-{args.run_id}.metta")
    post_snap = _read_input(getattr(args, "post_snapshot_override", "") or None,
                            paths["vol"] / f"history.post-benchmark-{args.run_id}.metta")
    window_text, window_mode = history_parse.window_from_texts(history, pre_snap, post_snap)

    history_queries = history_parse.extract_retrieve_args(window_text)
    placeholder_calls = history_parse.count_placeholder_retrieves(window_text)
    persist_receipts = history_parse.extract_persist_receipts(window_text)
    archive_receipts = history_parse.extract_archive_receipts(window_text)
    add_atom_shas = history_parse.extract_add_atom_shas(window_text)

    facts_index_text = _read_facts_index(args)
    facts_index = grading_mod.parse_facts_index(facts_index_text)

    blocks = grading_mod.parse_answers_v2(content)

    def reissue(query: str) -> dict:
        try:
            resp = _http_post(args.read_proxy + "/v1/query",
                              {"metta": query, "max_answers": 10}, timeout=30.0)
            return {"count": int(resp.get("count", 0))}
        except Exception as e:
            return {"error": str(e)}

    rd = RESULTS_DIR / args.run_id
    results = []
    reconstruction_by_case: dict[str, dict] = {}
    for case in facts_mod.TEST_CASES:
        case_id = case["id"]
        block = blocks.get(case_id)
        # P-gate input: per-case reconstruction payload (artifacts land
        # next to the batch grade outputs). Harness error aborts.
        try:
            recon_payload = _run_reconstruction(args, case_id, block, rd)
        except RuntimeError as e:
            print(f"[grade] ERROR: {e}")
            _write_json(rd / "grade.json", {"error": str(e)})
            return GATE_ERROR
        if recon_payload is not None:
            reconstruction_by_case[case_id] = _reconstruction_lane(recon_payload)
        r = grading_mod.gate_case(
            case, block, history_queries, placeholder_calls,
            reissue,
            reconstruction=recon_payload,
            case_source_refs=_case_source_refs(case_id),
            facts_index=facts_index,
            window_persist_receipts=len(persist_receipts),
            facts_index_raw=facts_index_text,
            judge_fn=_get_judge(args),
        )
        results.append(r)

    summary = grading_mod.gate_summary(results)

    grade_data = {
        "run_id": args.run_id,
        "mode": "batch",
        "gate_verdict": summary["gate_verdict"],
        "cases_passed": summary["cases_passed"],
        "cases_total": summary["cases_total"],
        "per_case": {
            r.case_id: {"verdict": r.verdict, "conditions": r.conditions,
                        "detail": r.detail}
            for r in results
        },
        "history_window": {
            "mode": window_mode,
            "retrieve_calls": len(history_queries),
            "retrieve_args": history_queries[:20],
            "placeholder_calls": placeholder_calls,
            "persist_receipts": len(persist_receipts),
            "archive_receipts": len(archive_receipts),
            "add_atom_shas": add_atom_shas[:20],
        },
        "facts_index_size": len(facts_index),
        "reconstruction": reconstruction_by_case,
        "timestamp": _now_iso(),
    }
    _write_json(RESULTS_DIR / args.run_id / "grade.json", grade_data)

    print(f"[grade] GATE {summary['gate_verdict']} — "
          f"{summary['cases_passed']}/{summary['cases_total']} cases passed")
    for r in results:
        conds = ", ".join(r.conditions) if r.conditions else "-"
        print(f"[grade]   {r.case_id}: {r.verdict} ({conds})")

    return GATE_PASS if summary["gate_verdict"] == "PASS" else GATE_FAIL


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def report(args) -> int:
    """Assemble report.json + report.md from grade*.json; signal verdict."""
    if args.dry_run:
        print(f"[report] [dry-run] would assemble results/{args.run_id}/report.*")
        return 0
    rd = RESULTS_DIR / args.run_id
    grade = _load_json(rd / "grade.json") or {}

    if not grade or "gate_verdict" not in grade:
        print(f"[report] ERROR: no gate verdict in {rd / 'grade.json'}")
        return GATE_ERROR

    # collect per-case grade-case files (sequential mode) for rich detail
    case_files = {}
    for p in sorted(rd.glob("grade-case-*.json")):
        g = _load_json(p) or {}
        cid = g.get("case_id") or p.stem.replace("grade-case-", "")
        case_files[cid] = g

    report = {
        "run_id": args.run_id,
        "grade": grade,
        "cases": case_files,
        "cleanup": _load_json(rd / "cleanup-das.json") or {},
        "timestamp": _now_iso(),
    }
    _write_json(rd / "report.json", report)

    lines = [f"# Windowless Room Gating Test Report — {args.run_id}", ""]
    verdict = grade.get("gate_verdict", "FAIL")
    lines.append(f"## GATE {verdict} — {grade.get('cases_passed', 0)}/{grade.get('cases_total', 0)} cases passed")
    lines.append("")
    lines.append("| Case | Verdict | Conditions | Attested | Reconstruction |")
    lines.append("|------|---------|------------|----------|----------------|")
    for cid, r in (grade.get("per_case") or {}).items():
        conds = ", ".join(r.get("conditions", [])) or "-"
        cf = case_files.get(cid, {})
        att = cf.get("attestation") or {}
        att_str = (f"QE+access ({att.get('access_count', '?')} posts)"
                    if att.get("qe_pattern_match") else "-")
        recon = cf.get("reconstruction") or {}
        recon_rows = (recon.get("byte_compare") or []
                      if isinstance(recon, dict) else [])
        recon_str = (f"{sum(1 for x in recon_rows if x.get('byte_match'))}/{len(recon_rows)} byte-match background"
                     if recon_rows else "-")
        lines.append(f"| {cid} | {r.get('verdict', '?')} | {conds} | {att_str} | {recon_str} |")
    lines.append("")

    cleanup = report["cleanup"]
    if cleanup:
        lines.append(f"DAS cleanup before run: {cleanup.get('discovered_count', '?')} expressions removed, "
                     f"canaries intact: {cleanup.get('canaries_intact', '?')}")

    lines.append("")
    lines.append("Condition codes: A_* answer, Q_* query-first (Q_ATTESTED_VIA_ACCESS_LOG "
                 "is informational), E_* extraction, R_* reasoning trace, P_* provenance.")
    report_md = "\n".join(lines)
    (rd / "report.md").write_text(report_md, encoding="utf-8")
    print(report_md)

    return GATE_PASS if verdict == "PASS" else GATE_FAIL


# ---------------------------------------------------------------------------
# batch setup/agent/full (v2 flow, kept via --batch)
# ---------------------------------------------------------------------------

def setup(args) -> int:
    """Batch setup: archive sources, prompts.txt (all cases), install, restart."""
    print("[setup] batch setup (v2 flow)...")
    paths = _bench_paths(args)
    facts_mod = _facts_mod()

    setup_data: dict = {"run_id": args.run_id, "archived": {}}

    bg_dir = HERE / "background"
    for fname in sorted(bg_dir.glob("*.md")):
        url = facts_mod.SOURCE_URLS.get(fname.name)
        if not url:
            continue
        if args.dry_run:
            setup_data["archived"][fname.name] = "dry-run"
        else:
            try:
                content = fname.read_text(encoding="utf-8")
                resp = _http_post(args.write_bridge + "/v1/archive", {
                    "url": url, "content": content, "content_type": "text/markdown",
                }, timeout=60.0)
                setup_data["archived"][fname.name] = {
                    "commit": resp.get("commit", ""), "deduped": resp.get("deduped", False),
                }
            except Exception as e:
                setup_data["archived"][fname.name] = f"error: {e}"

    if args.dry_run:
        print("[setup] [dry-run] would write benchmark files + install prompt + restart")
        setup_data["prompt_installed"] = "dry-run"
        _write_json(RESULTS_DIR / args.run_id / "setup.json", setup_data)
        return 0

    _prepare_benchmark_dir(args)
    prompts_content = _render_prompts_txt(HERE)
    _sudo_write(paths["vol"] / f"{BENCH_REL}/prompts.txt", prompts_content)

    # fresh answers.md + facts-index.md (E-gate inputs)
    _sudo_write(paths["answers"],
                f"# Benchmark answers — {args.run_id} (batch)\n")
    _sudo_write(paths["facts_index"],
                f"# Extraction record — {args.run_id}\n")

    _sudo_run(["cp", str(paths["prompt"]),
               str(paths["vol"] / f"prompt.txt.bak-pre-benchmark-{args.run_id}")])
    _sudo_run(["cp", str(paths["state"]),
               str(paths["vol"] / f"omega_state.md.bak-pre-benchmark-{args.run_id}")])

    # batch prompt: render the template once per case, all cases listed
    template = (HERE / "agent_prompt_template.md").read_text(encoding="utf-8")
    rendered = template.replace("{{RUN_ID}}", args.run_id)
    if not _sudo_write(paths["prompt"], rendered):
        print("[setup] ERROR: prompt install failed")
        return 1
    _sudo_write(paths["state"], f"BENCHMARK MODE ACTIVE — run {args.run_id} (batch)\n")
    _sudo_write(paths["vol"] / f"history.pre-benchmark-{args.run_id}.metta",
                _sudo_read(paths["history"]) or "")
    _sudo_run(["chown", "-R", "65534:65534", str(paths["bench"])])
    if not _agent_restart():
        print("[setup] ERROR: restart failed")
        return 1

    setup_data["prompt_installed"] = True
    setup_data["timestamp"] = _now_iso()
    _write_json(RESULTS_DIR / args.run_id / "setup.json", setup_data)
    return 0


def agent(args) -> int:
    """Batch agent phase: wait for ALL case answers."""
    facts_mod = _facts_mod()
    case_ids = [c["id"] for c in facts_mod.TEST_CASES]
    paths = _bench_paths(args)
    timeout_s = args.timeout_minutes * 60
    start = time.time()

    if args.dry_run:
        print(f"[agent] [dry-run] would poll for all {len(case_ids)} answers")
        return 0

    while time.time() - start < timeout_s:
        content = _sudo_read(paths["answers"])
        if content is not None:
            found = sum(1 for cid in case_ids if f"FINAL ANSWER ({cid}):" in content)
            print(f"[agent] {found}/{len(case_ids)} answers ({int((time.time()-start)/60)}m)")
            if found == len(case_ids):
                _sudo_run(["cp", str(paths["history"]),
                           str(paths["vol"] / f"history.post-benchmark-{args.run_id}.metta")])
                _write_json(RESULTS_DIR / args.run_id / "agent.json",
                            {"status": "complete", "answers_found": found})
                return 0
        time.sleep(60)

    _sudo_run(["cp", str(paths["history"]),
               str(paths["vol"] / f"history.post-benchmark-{args.run_id}.metta")])
    _write_json(RESULTS_DIR / args.run_id / "agent.json", {"status": "timeout"})
    return 1


def full_batch(args) -> int:
    """v2 all-at-once flow: setup -> agent -> grade -> report -> teardown."""
    phases = [("preflight", preflight), ("setup", setup), ("agent", agent),
              ("grade", grade), ("report", report)]
    gate_exit = GATE_PASS
    harness_error = False

    for name, fn in phases:
        print(f"\n[full-batch] === {name} ===")
        rc = fn(args)
        if name in ("grade", "report"):
            if rc == GATE_ERROR:
                harness_error = True
            else:
                gate_exit = rc
        elif rc != 0:
            harness_error = True
            break

    print("\n[full-batch] === teardown ===")
    if teardown(args) != 0:
        harness_error = True

    if harness_error:
        return GATE_ERROR
    return gate_exit


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Windowless-room GATING TEST v4 orchestrator "
                    "(sequential standalone questions; per-case history trim; "
                    "deterministic; no LLM)"
    )
    subparsers = parser.add_subparsers(dest="phase")

    def add_common(p):
        p.add_argument("--run-id", default=_run_id())
        p.add_argument("--repo-remote", default="https://github.com/ktfh-claw/low-cost-omega-setup.git")
        p.add_argument("--origin-main-sha", default="")
        p.add_argument("--memory-volume", default=DEFAULT_MEMORY_VOLUME)
        p.add_argument("--provenance-repo", default=DEFAULT_PROVENANCE_REPO)
        p.add_argument("--write-bridge", default=DEFAULT_WRITE_BRIDGE)
        p.add_argument("--read-proxy", default=DEFAULT_READ_PROXY)
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--json", action="store_true")
        p.add_argument("--force", action="store_true")
        # v15b: A-gate LLM judge (chat-completions compatible)
        p.add_argument("--judge-base-url", default="https://api.asi1.ai/v1")
        p.add_argument("--judge-model", default="asi1-ultra")
        p.add_argument("--judge-api-key", default="",
                       help="judge API key; default: ASIONE_API_KEY/OPENAI_API_KEY "
                            "env or the Omega deployment runtime.env (never logged)")
        p.add_argument("--judge-timeout", type=float, default=60.0)
        return p

    add_common(subparsers.add_parser("preflight"))
    add_common(subparsers.add_parser("cleanup-das"))

    def add_case_args(p):
        p.add_argument("--case", required=True,
                       help="case id (one of: " + ", ".join(c["id"] for c in _facts_mod().TEST_CASES) + ")")
        # v4 (lever 4 of the wr3b post-mortem): 75-minute default per-case
        # window. The wr3b evidence: the agent pipeline works (queries,
        # extraction, persistence, verification all landed) but the cycle
        # budget of a 45-minute window was insufficient even with clean DAS
        # behavior — the terminal answer-block write never landed. 75 m
        # gives the ingest+verify+answer arc realistic room. Strict gates
        # are unchanged.
        p.add_argument("--timeout-minutes", type=int, default=75)
        # v4 (lever 3): per-case history trim (see setup_case); default ON.
        p.add_argument("--no-trim-history", dest="trim_history",
                       action="store_false", default=True,
                       help="keep the full serialized history (v3 behavior); "
                            "default trims history.metta to the per-case "
                            "window marker before each case")

    add_case_args(add_common(subparsers.add_parser("setup-case")))
    add_case_args(add_common(subparsers.add_parser("agent-case")))
    gp = add_common(subparsers.add_parser("grade-case"))
    add_case_args(gp)
    gp.add_argument("--facts-index-override", default="")

    g = add_common(subparsers.add_parser("grade"))
    for opt in ["--answers-override", "--history-override",
                "--pre-snapshot-override", "--post-snapshot-override",
                "--facts-index-override"]:
        g.add_argument(opt, default="")

    add_common(subparsers.add_parser("report"))
    tp = add_common(subparsers.add_parser("teardown"))
    tp.add_argument("--allow-dirty-backup", action="store_true")
    tp.add_argument("--keep-snapshots", action="store_true")

    fp = add_common(subparsers.add_parser("full"))
    fp.add_argument("--batch", action="store_true",
                    help="v2 all-at-once flow (single prompt with all 7 questions)")
    fp.add_argument("--cases", default="",
                    help="comma-separated subset of case ids to run (iteration mode; "
                         "default: all cases sequentially)")
    fp.add_argument("--cleanup-first", action="store_true", default=True,
                    help="run cleanup-das before the sequential run (default)")
    fp.add_argument("--no-cleanup", dest="cleanup_first", action="store_false")
    fp.add_argument("--timeout-minutes", type=int, default=75)
    fp.add_argument("--no-trim-history", dest="trim_history",
                    action="store_false", default=True,
                    help="keep the full serialized history (v3 behavior); "
                         "default trims history.metta to the per-case window "
                         "marker before each case (v4)")
    fp.add_argument("--skip-report", action="store_true")
    fp.add_argument("--allow-dirty-backup", action="store_true")
    fp.add_argument("--keep-snapshots", action="store_true")
    fp.add_argument("--seed-canonical", action="store_true")
    fp.add_argument("--cleanup", action="store_true")

    sp = add_common(subparsers.add_parser("setup"))
    sp.add_argument("--seed-canonical", action="store_true")
    ap = add_common(subparsers.add_parser("agent"))
    ap.add_argument("--timeout-minutes", type=int, default=60)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.phase:
        parser.print_help()
        return 1

    dispatch = {
        "preflight": preflight, "cleanup-das": cleanup_das,
        "setup-case": setup_case, "agent-case": agent_case,
        "grade-case": grade_case, "grade": grade, "report": report,
        "teardown": teardown, "setup": setup, "agent": agent,
    }

    if args.phase == "full":
        if getattr(args, "batch", False):
            return full_batch(args)
        if not args.cleanup_first:
            # skip cleanup-das by pre-creating its result marker
            (RESULTS_DIR / args.run_id / "cleanup-das.json").parent.mkdir(
                parents=True, exist_ok=True)
            (RESULTS_DIR / args.run_id / "cleanup-das.json").write_text(
                json.dumps({"skipped": True}))
        return full_sequential(args)

    return dispatch[args.phase](args)


if __name__ == "__main__":
    sys.exit(main())
