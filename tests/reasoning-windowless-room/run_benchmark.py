#!/usr/bin/env python3
"""Orchestrator CLI for the windowless-room GATING TEST (v2).

Runs ON the OVH host (operator: ``ssh -p 9022 ubuntu@100.84.81.96``) from the
synced repo directory (``tests/reasoning-windowless-room/``). Phases:
preflight, setup, agent, grade, report, teardown, full.

This is a strict pass/fail GATE, not a scored benchmark. A case passes only
if ALL gate conditions hold:

  A-gate  the FINAL ANSWER line exists and is substantively correct.
  Q-gate  the case was answered QUERY-FIRST: a real das-retrieve call in the
          benchmark window (history suffix between the pre/post snapshots),
          quoted in the answers file with its DAS_RETRIEVE_OK receipt,
          non-degenerate (has a $variable AND a non-variable literal, no
          $_ placeholder), and re-issued by the harness via the read-proxy
          with a matching count (count=0 for the unsolvable case, proven
          again by re-issue).
  P-gate  every git:<sha> source citation resolves against the provenance
          git repo: commit exists, adds one sources/ blob + index.jsonl,
          index entry at that commit matches the blob path, sha256(blob)
          matches the index entry, and the entry url matches the citation.

Grading is fully deterministic (regex/keyword parsing, string matching, HTTP
re-issue, git reads). NO LLM is used anywhere in the harness.

Exit codes (grade/report/full): 0 = gate PASS, 2 = gate FAIL (the expected
negative signal — the gate did its job), 1 = harness/environment error.

Restart invariant: the agent is restarted via
``sudo systemctl restart omega-curiosity.service`` — NOT ``docker restart`` —
because the unit's ``start.sh`` trap ``rm -f``'s the container (a docker
restart would destroy the container).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"

DEFAULT_MEMORY_VOLUME = "/var/lib/docker/volumes/omega-curiosity-memory/_data"
DEFAULT_PROVENANCE_REPO = "/home/ubuntu/omega-provenance"
DEFAULT_WRITE_BRIDGE = "http://172.20.0.5:8080"
DEFAULT_READ_PROXY = "http://172.20.0.3:8080"

CONTAINER_WRITE_BRIDGE = "omega-das-write-bridge-write-bridge-1"
CONTAINER_READ_PROXY = "omega-das-integration-read-proxy-1"
CONTAINER_AGENT = "omega-curiosity"

GATE_PASS, GATE_FAIL, GATE_ERROR = 0, 2, 1


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
    """Load a JSON file; return None on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data: dict) -> None:
    """Write a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _sudo_read(path: Path, timeout: float = 60.0) -> str | None:
    """Read a (possibly root-owned) file via sudo; None on failure."""
    r = _run(["sudo", "cat", str(path)], timeout=timeout)
    return r.stdout if r.returncode == 0 else None


def _sudo_exists(path: Path) -> bool:
    r = _run(["sudo", "test", "-f", str(path)], timeout=10.0)
    return r.returncode == 0


def _container_ip(container: str) -> str:
    """Resolve a container's IP via docker inspect (do NOT hardcode)."""
    try:
        result = _run([
            "docker", "inspect", "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            container,
        ])
        return result.stdout.strip()
    except Exception:
        return ""


def _resolve_endpoints(args) -> None:
    """Resolve write-bridge / read-proxy URLs dynamically (in-place on args)."""
    wb_ip = _container_ip(CONTAINER_WRITE_BRIDGE)
    rp_ip = _container_ip(CONTAINER_READ_PROXY)
    if wb_ip:
        args.write_bridge = f"http://{wb_ip}:8080"
    if rp_ip:
        args.read_proxy = f"http://{rp_ip}:8080"


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

def preflight(args) -> int:
    """Preflight phase: verify environment is ready for the benchmark."""
    _resolve_endpoints(args)
    print(f"[preflight] write_bridge={args.write_bridge} read_proxy={args.read_proxy}")

    print("[preflight] checking environment...")
    checks: dict[str, str] = {}

    # 1. Docker containers running
    for container in [CONTAINER_WRITE_BRIDGE, CONTAINER_READ_PROXY, CONTAINER_AGENT]:
        if args.dry_run:
            checks[f"container_{container}"] = "dry-run"
        else:
            try:
                result = _run(["docker", "inspect", container])
                checks[f"container_{container}"] = "running" if result.returncode == 0 else "missing"
            except Exception as e:
                checks[f"container_{container}"] = f"error: {e}"

    # 2. Resolve container IPs dynamically
    ips = {}
    for name, container in [("write_bridge", CONTAINER_WRITE_BRIDGE), ("read_proxy", CONTAINER_READ_PROXY)]:
        if args.dry_run:
            ips[name] = "dry-run"
        else:
            ips[name] = _container_ip(container)
    checks["write_bridge_ip"] = ips.get("write_bridge", "")
    checks["read_proxy_ip"] = ips.get("read_proxy", "")

    # 3. Write-bridge smoke test (POST /v1/write with verify:true)
    if not args.dry_run:
        try:
            smoke = f'(BenchmarkPreflight (Concept "{args.run_id}"))'
            _http_post(args.write_bridge + "/v1/write", {
                "metta": smoke, "verify": True,
            }, timeout=30.0)
            checks["write_bridge_smoke"] = "ok"
            # Smoke fact is benchmark residue: remove it (links-only) so the
            # KB stays clean before the run starts.
            try:
                _run(["docker", "exec", "-w", "/app", CONTAINER_WRITE_BRIDGE,
                      "python", "cleanup.py", "--metta", smoke], timeout=180.0)
                checks["write_bridge_smoke_cleanup"] = "ok"
            except Exception as e:
                checks["write_bridge_smoke_cleanup"] = f"warn: {e}"
        except Exception as e:
            checks["write_bridge_smoke"] = f"error: {e}"
    else:
        checks["write_bridge_smoke"] = "dry-run (planned: POST /v1/write smoke fact)"

    # 4. Read-proxy metta query test
    if not args.dry_run:
        try:
            resp = _http_post(args.read_proxy + "/v1/query", {
                "metta": "(Inheritance $X $Y)", "max_answers": 10,
            }, timeout=30.0)
            if "count" not in resp:
                raise RuntimeError(f"no count in response: {resp}")
            checks["read_proxy_query"] = "ok"
        except Exception as e:
            checks["read_proxy_query"] = f"error: {e}"
    else:
        checks["read_proxy_query"] = "dry-run (planned: POST /v1/query variable-form test)"

    # 5. Provenance repo exists and is a git repo
    if args.dry_run:
        checks["provenance_repo"] = "dry-run"
    else:
        try:
            # Repo is owned by container uid 65532 with restrictive perms —
            # git as ubuntu cannot even enter the dir; check via sudo root.
            result = _run(["sudo", "git", "-c", f"safe.directory={args.provenance_repo}",
                           "-C", args.provenance_repo, "rev-parse", "--git-dir"])
            checks["provenance_repo"] = "ok" if result.returncode == 0 else "missing"
        except Exception as e:
            checks["provenance_repo"] = f"error: {e}"

    # 6. Agent memory volume exists (root-owned: check via sudo)
    if args.dry_run:
        checks["memory_volume"] = "dry-run"
    else:
        try:
            r = _run(["sudo", "test", "-d", args.memory_volume], timeout=10.0)
            checks["memory_volume"] = "ok" if r.returncode == 0 else "missing"
        except Exception as e:
            checks["memory_volume"] = f"error: {e}"

    # Report
    ok_values = {"ok", "running", "dry-run"}
    all_ok = all(
        v in ok_values or v.startswith("dry-run")
        or v.startswith("172.") or v.startswith("10.") or v.startswith("192.168.")
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
# setup
# ---------------------------------------------------------------------------

def _render_prompts_txt(here: Path) -> str:
    """Build benchmark prompts.txt content from facts.TEST_CASES.

    Each case block: header, full prompt text, FINAL ANSWER format line.
    NOTE: case["prompt_file"] is already repo-relative ("prompts/<name>.md")
    and must NOT be re-prefixed with here/"prompts" — that double-join
    shipped prompts.txt with EMPTY case bodies in live run
    wr-20261021-2355 (agent ran the benchmark blind for ~95 min).
    Fails fast (FileNotFoundError) on a missing/empty prompt file instead
    of silently rendering a blank benchmark.
    """
    sys.path.insert(0, str(here))
    import facts as facts_mod
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


def setup(args) -> int:
    """Setup phase: archive sources, write benchmark files, install prompt, restart agent."""
    print("[setup] starting setup...")
    sys.path.insert(0, str(HERE))
    import facts as facts_mod

    setup_data: dict = {"run_id": args.run_id, "archived": {}, "files": {}}

    # 1. Archive the background sources
    bg_dir = HERE / "background"
    for fname in sorted(bg_dir.glob("*.md")):
        url = facts_mod.SOURCE_URLS.get(fname.name)
        if not url:
            continue
        if args.dry_run:
            print(f"[setup] [dry-run] would archive {fname.name} -> {url}")
            setup_data["archived"][fname.name] = "dry-run"
        else:
            try:
                content = fname.read_text(encoding="utf-8")
                resp = _http_post(args.write_bridge + "/v1/archive", {
                    "url": url, "content": content, "content_type": "text/markdown",
                }, timeout=60.0)
                setup_data["archived"][fname.name] = {
                    "commit": resp.get("commit", ""),
                    "deduped": resp.get("deduped", False),
                }
                print(f"[setup] archived {fname.name} -> {resp.get('commit', '???')}")
            except Exception as e:
                print(f"[setup] ERROR archiving {fname.name}: {e}")
                setup_data["archived"][fname.name] = f"error: {e}"

    # 2. Write benchmark files to memory volume (needs sudo)
    vol = Path(args.memory_volume)
    bench = vol / "benchmark"
    bg_files = sorted((HERE / "background").glob("*.md"))
    actions = [
        ["sudo", "mkdir", "-p", str(bench / "background")],
    ]
    for f in bg_files:
        actions.append(["sudo", "cp", str(f), str(bench / "background" / f.name)])
    # urls.txt
    urls_content = "\n".join(facts_mod.SOURCE_URLS.values()) + "\n"
    # prompts.txt (7 cases with the answer-format contract)
    prompts_content = _render_prompts_txt(HERE)

    # 3. Render agent_prompt_template.md -> prompt.txt
    template = (HERE / "agent_prompt_template.md").read_text(encoding="utf-8")
    rendered = (template
                .replace("{{RUN_ID}}", args.run_id)
                .replace("{{URL_LIST_PATH}}", "benchmark/urls.txt")
                .replace("{{PROMPTS_PATH}}", "benchmark/prompts.txt")
                .replace("{{ANSWERS_PATH}}", "benchmark/answers.md"))

    if args.dry_run:
        print(f"[setup] [dry-run] planned actions:")
        for a in actions:
            print(f"  - {a}")
        print(f"  - write {bench}/urls.txt")
        print(f"  - write {bench}/prompts.txt")
        print(f"  - install prompt.txt (backup existing)")
        print(f"  - write benchmark omega_state.md (backup existing)")
        print(f"  - copy history.metta -> history.pre-benchmark-{args.run_id}.metta")
        print(f"  - chown -R 65534:65534 benchmark/ (agent runs as nobody:nogroup)")
        print(f"  - sudo systemctl restart omega-curiosity.service")
    else:
        try:
            for a in actions:
                _run(a, timeout=60.0)
            # urls.txt + prompts.txt via sudo tee (single live subprocess each)
            for rel, content in [("urls.txt", urls_content), ("prompts.txt", prompts_content)]:
                subprocess.run(
                    ["sudo", "tee", str(bench / rel)],
                    input=content, capture_output=True, text=True, timeout=30.0,
                )
            # Install prompt.txt (backup existing)
            _run(["sudo", "cp", str(vol / "prompt.txt"),
                  str(vol / f"prompt.txt.bak-pre-benchmark-{args.run_id}")], timeout=30.0)
            subprocess.run(
                ["sudo", "tee", str(vol / "prompt.txt")],
                input=rendered, capture_output=True, text=True, timeout=30.0,
            )
            # Backup + write omega_state.md
            _run(["sudo", "cp", str(vol / "omega_state.md"),
                  str(vol / f"omega_state.md.bak-pre-benchmark-{args.run_id}")], timeout=30.0)
            state = f"BENCHMARK MODE ACTIVE — run {args.run_id}\n"
            subprocess.run(
                ["sudo", "tee", str(vol / "omega_state.md")],
                input=state, capture_output=True, text=True, timeout=30.0,
            )
            # 4. Copy history.metta (pre-run snapshot: defines the window start)
            _run(["sudo", "cp", str(vol / "history.metta"),
                  str(vol / f"history.pre-benchmark-{args.run_id}.metta")], timeout=60.0)
            # 4b. The agent container runs as nobody:nogroup (uid/gid 65534);
            # without this it cannot create answers.md inside the root-owned
            # benchmark dir (EACCES observed live on 2026-10-21).
            _run(["sudo", "chown", "-R", "65534:65534", str(bench)], timeout=30.0)
            # 5. Restart agent (systemd, NOT docker — start.sh trap rm -f's the container)
            _run(["sudo", "systemctl", "restart", "omega-curiosity.service"], timeout=120.0)
            print("[setup] agent restarted via systemctl")
        except Exception as e:
            print(f"[setup] ERROR: {e}")
            _write_json(RESULTS_DIR / args.run_id / "setup.json", {**setup_data, "error": str(e)})
            return 1

    if args.seed_canonical:
        print("[setup] --seed-canonical: seeding canonical facts (grading-oracle mode; NOT the default test mode)")
        for fact in facts_mod.CANONICAL_FACTS:
            try:
                _http_post(args.write_bridge + "/v1/write", {
                    "metta": fact["metta"], "verify": True,
                    "tv": {"strength": fact["stv"][0], "confidence": fact["stv"][1]},
                }, timeout=30.0)
            except Exception as e:
                print(f"[setup] seed ERROR {fact['id']}: {e}")
                return 1
        print(f"[setup] seeded {len(facts_mod.CANONICAL_FACTS)} canonical facts")

    setup_data["prompt_installed"] = True
    setup_data["timestamp"] = datetime.now().isoformat()
    _write_json(RESULTS_DIR / args.run_id / "setup.json", setup_data)
    print(f"[setup] setup.json written to results/{args.run_id}/setup.json")
    return 0


# ---------------------------------------------------------------------------
# agent
# ---------------------------------------------------------------------------

def agent(args) -> int:
    """Agent phase: poll for completion (answers file with all 7 FINAL ANSWER lines)."""
    sys.path.insert(0, str(HERE))
    import facts as facts_mod
    case_ids = [c["id"] for c in facts_mod.TEST_CASES]

    answers_path = Path(args.memory_volume) / "benchmark" / "answers.md"
    timeout_s = args.timeout_minutes * 60
    start = time.time()
    print(f"[agent] polling for {answers_path} (timeout {args.timeout_minutes}m)...")

    if args.dry_run:
        print(f"[agent] [dry-run] would poll for {answers_path} with all 7 FINAL ANSWER lines")
        return 0

    def _snapshot_post(vol: Path) -> bool:
        snap = _run(["sudo", "cp", str(vol / "history.metta"),
                     str(vol / f"history.post-benchmark-{args.run_id}.metta")], timeout=60.0)
        return snap.returncode == 0

    while time.time() - start < timeout_s:
        content = _sudo_read(answers_path)
        if content is not None:
            found = sum(1 for cid in case_ids if f"FINAL ANSWER ({cid}):" in content)
            elapsed = int((time.time() - start) / 60)
            print(f"[agent] {found}/{len(case_ids)} answers present ({elapsed}m elapsed)")
            if found == len(case_ids):
                print("[agent] COMPLETE — all answers present")
                ok = _snapshot_post(Path(args.memory_volume))
                _write_json(RESULTS_DIR / args.run_id / "agent.json", {
                    "status": "complete", "answers_found": found,
                    "post_snapshot": ok,
                })
                return 0
        time.sleep(60)

    print("[agent] TIMEOUT — recording partial state")
    ok = _snapshot_post(Path(args.memory_volume))
    _write_json(RESULTS_DIR / args.run_id / "agent.json", {
        "status": "timeout", "post_snapshot": ok,
    })
    return 1


# ---------------------------------------------------------------------------
# grade (v2: strict deterministic gate)
# ---------------------------------------------------------------------------

def grade(args) -> int:
    """Grade phase: apply the strict gate (answer + query-first + provenance).

    Deterministic only — no LLM. Exit 0 = gate PASS, 2 = gate FAIL,
    1 = harness error.
    """
    sys.path.insert(0, str(HERE))
    import facts as facts_mod
    import grading as grading_mod
    import history_parse
    import provenance_check

    if args.dry_run:
        print("[grade] [dry-run] would apply the strict gate (A/Q/P) to answers.md")
        return 0

    _resolve_endpoints(args)

    def _read_input(explicit: str | None, default: Path) -> str | None:
        """Read an input file: explicit path (plain read, sudo fallback) or default (sudo)."""
        if explicit:
            try:
                return Path(explicit).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return _sudo_read(Path(explicit))
        return _sudo_read(default)

    vol = Path(args.memory_volume)
    answers_path = Path(getattr(args, "answers_override", "") or (vol / "benchmark" / "answers.md"))
    content = _read_input(getattr(args, "answers_override", "") or None,
                          vol / "benchmark" / "answers.md")
    if content is None:
        print(f"[grade] ERROR: answers file not readable at {answers_path}")
        _write_json(RESULTS_DIR / args.run_id / "grade.json",
                    {"error": "answers file not readable"})
        return GATE_ERROR

    # --- benchmark window from snapshots ---
    history = _read_input(getattr(args, "history_override", "") or None,
                          vol / "history.metta") or ""
    pre_snap = _read_input(getattr(args, "pre_snapshot_override", "") or None,
                           vol / f"history.pre-benchmark-{args.run_id}.metta")
    post_snap = _read_input(getattr(args, "post_snapshot_override", "") or None,
                            vol / f"history.post-benchmark-{args.run_id}.metta")
    window_text, window_mode = history_parse.window_from_texts(history, pre_snap, post_snap)

    if window_mode == "full":
        print("[grade] ERROR: no usable pre-benchmark history snapshot — cannot define")
        print("[grade]        the benchmark window; refusing to grade (pass --pre-snapshot-override")
        print("[grade]        for offline re-grades)")
        _write_json(RESULTS_DIR / args.run_id / "grade.json",
                    {"error": "no pre-benchmark history snapshot; window undefined"})
        return GATE_ERROR

    history_queries = history_parse.extract_retrieve_args(window_text)
    placeholder_calls = history_parse.count_placeholder_retrieves(window_text)
    persist_receipts = history_parse.extract_persist_receipts(window_text)
    archive_receipts = history_parse.extract_archive_receipts(window_text)
    add_atom_shas = history_parse.extract_add_atom_shas(window_text)

    # --- parse answers into per-case blocks ---
    blocks = grading_mod.parse_answers_v2(content)

    # --- resolve every cited source against the provenance repo ---
    citation_inputs: list[provenance_check.Citation] = []
    seen: set[tuple[str, str]] = set()
    for case in facts_mod.TEST_CASES:
        block = blocks.get(case["id"])
        if block is None:
            continue
        for sha, url in grading_mod.parse_citations(block.sources_raw):
            if (sha, url) not in seen:
                seen.add((sha, url))
                citation_inputs.append(provenance_check.Citation(sha=sha, url=url))
    # also resolve shas the agent persisted via add-atom (window evidence)
    for sha in add_atom_shas:
        if (sha, "") not in seen:
            seen.add((sha, ""))
            citation_inputs.append(provenance_check.Citation(sha=sha, url=""))

    citation_checks: list[tuple[str, str, list[str]]] = []
    for c in citation_inputs:
        check = provenance_check.resolve_citation(
            args.provenance_repo, c.sha, c.url, sudo=True)
        citation_checks.append((c.sha, c.url, check.conditions))

    # --- re-issue closure (deterministic HTTP re-query) ---
    def reissue(query: str) -> dict:
        try:
            resp = _http_post(args.read_proxy + "/v1/query", {
                "metta": query, "max_answers": 10,
            }, timeout=30.0)
            return {"count": int(resp.get("count", 0))}
        except Exception as e:
            return {"error": str(e)}

    # --- gate every case ---
    results = []
    for case in facts_mod.TEST_CASES:
        r = grading_mod.gate_case(
            case,
            blocks.get(case["id"]),
            history_queries,
            placeholder_calls,
            reissue,
            citation_checks,
        )
        results.append(r)

    summary = grading_mod.gate_summary(results)

    grade_data = {
        "run_id": args.run_id,
        "gate_verdict": summary["gate_verdict"],
        "cases_passed": summary["cases_passed"],
        "cases_total": summary["cases_total"],
        "per_case": {
            r.case_id: {
                "verdict": r.verdict,
                "conditions": r.conditions,
                "detail": r.detail,
            } for r in results
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
        "citation_checks": [
            {"sha": s, "url": u, "conditions": conds}
            for s, u, conds in citation_checks
        ],
        "timestamp": datetime.now().isoformat(),
    }
    _write_json(RESULTS_DIR / args.run_id / "grade.json", grade_data)

    print(f"[grade] GATE {summary['gate_verdict']} — "
          f"{summary['cases_passed']}/{summary['cases_total']} cases passed")
    for r in results:
        conds = ", ".join(r.conditions) if r.conditions else "-"
        print(f"[grade]   {r.case_id}: {r.verdict} ({conds})")

    return GATE_PASS if summary["gate_verdict"] == "PASS" else GATE_FAIL


# ---------------------------------------------------------------------------
# report (v2: gate report + signal)
# ---------------------------------------------------------------------------

def report(args) -> int:
    """Report phase: assemble report.json + report.md from grade.json; signal verdict."""
    if args.dry_run:
        print(f"[report] [dry-run] would assemble results/{args.run_id}/report.json + report.md")
        return 0
    rd = RESULTS_DIR / args.run_id
    setup = _load_json(rd / "setup.json") or {}
    grade = _load_json(rd / "grade.json") or {}
    agent_data = _load_json(rd / "agent.json") or {}

    if not grade or "gate_verdict" not in grade:
        print(f"[report] ERROR: no gate verdict in {rd/'grade.json'} — run grade first")
        return GATE_ERROR

    report = {
        "run_id": args.run_id,
        "setup": setup,
        "agent": agent_data,
        "grade": grade,
        "timestamp": datetime.now().isoformat(),
    }
    _write_json(rd / "report.json", report)

    # Human-readable gate report
    lines = [f"# Windowless Room Gating Test Report — {args.run_id}", ""]
    verdict = grade.get("gate_verdict", "FAIL")
    lines.append(f"## GATE {verdict} — {grade.get('cases_passed', 0)}/{grade.get('cases_total', 0)} cases passed")
    lines.append("")
    lines.append("| Case | Verdict | Conditions |")
    lines.append("|------|---------|------------|")
    for cid, r in (grade.get("per_case") or {}).items():
        conds = ", ".join(r.get("conditions", [])) or "-"
        lines.append(f"| {cid} | {r.get('verdict', '?')} | {conds} |")
    lines.append("")
    hw = grade.get("history_window") or {}
    lines.append(f"History window mode: {hw.get('mode', '?')} — "
                 f"das-retrieve calls in window: {hw.get('retrieve_calls', 0)} "
                 f"(placeholder calls: {hw.get('placeholder_calls', 0)})")
    lines.append("")
    lines.append("Condition code reference:")
    lines.append("")
    lines.append("- `A_*` — answer gate (missing / wrong / sky pattern-match / fabricated)")
    lines.append("- `Q_*` — query-first gate (no query, no receipt, not in history,")
    lines.append("  placeholder arg, degenerate pattern, reissue mismatch, absence unproven)")
    lines.append("- `P_*` — provenance gate (citation missing / unresolved vs git repo)")
    lines.append("")
    report_md = "\n".join(lines)
    (rd / "report.md").write_text(report_md, encoding="utf-8")
    print(report_md)

    return GATE_PASS if verdict == "PASS" else GATE_FAIL


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------

def teardown(args) -> int:
    """Teardown phase: restore agent to standby (with backup contamination guard)."""
    vol = Path(args.memory_volume)
    if args.dry_run:
        print(f"[teardown] [dry-run] planned actions:")
        print(f"  - verify backup prompt is NOT a benchmark prompt (contamination guard)")
        print(f"  - restore prompt.txt from backup")
        print(f"  - restore omega_state.md from backup")
        print(f"  - append 'benchmark complete' line")
        print(f"  - sudo systemctl restart omega-curiosity.service")
        if getattr(args, "cleanup", False):
            print(f"  - [cleanup] remove benchmark DAS atoms via cleanup.py (links-only)")
        return 0

    try:
        # Contamination guard: the standby backup must not itself be a
        # benchmark prompt (this exact failure shipped with the wr-20261021
        # run: the *.bak-pre-benchmark* copies had captured run-1 content).
        backup_prompt = vol / f"prompt.txt.bak-pre-benchmark-{args.run_id}"
        backup_text = _sudo_read(backup_prompt) or ""
        if "BENCHMARK MODE" in backup_text and not getattr(args, "allow_dirty_backup", False):
            print("[teardown] ABORT: backup prompt still contains BENCHMARK MODE content —")
            print(f"[teardown]         {backup_prompt} is contaminated; refusing to restore it.")
            print("[teardown]         Fix the standby backup first or pass --allow-dirty-backup.")
            _write_json(RESULTS_DIR / args.run_id / "teardown.json", {
                "error": "backup prompt contaminated with benchmark content",
                "aborted": True,
            })
            return 1

        # Restore original prompt + omega_state.md
        _run(["sudo", "cp", str(backup_prompt),
              str(vol / "prompt.txt")], timeout=30.0)
        _run(["sudo", "cp", str(vol / f"omega_state.md.bak-pre-benchmark-{args.run_id}"),
              str(vol / "omega_state.md")], timeout=30.0)
        # Append truthful line
        subprocess.run(
            ["sudo", "tee", "-a", str(vol / "omega_state.md")],
            input=f"\nbenchmark complete ({args.run_id}), returned to standby\n",
            capture_output=True, text=True, timeout=30.0,
        )
        # Restart service (systemd, NOT docker)
        _run(["sudo", "systemctl", "restart", "omega-curiosity.service"], timeout=120.0)
        # Optional cleanup (links-only; NEVER --delete-nodes)
        if getattr(args, "cleanup", False):
            print("[teardown] cleanup requested — removing benchmark DAS atoms (links-only)")
            sys.path.insert(0, str(HERE))
            import facts as facts_mod
            for fact in facts_mod.CANONICAL_FACTS:
                try:
                    _run(["docker", "exec", "-w", "/app", CONTAINER_WRITE_BRIDGE,
                          "python", "cleanup.py", "--metta", fact["metta"]], timeout=300.0)
                except Exception as e:
                    print(f"[teardown] cleanup skip {fact['id']}: {e}")
    except Exception as e:
        print(f"[teardown] ERROR: {e}")
        _write_json(RESULTS_DIR / args.run_id / "teardown.json", {"error": str(e)})
        return 1

    _write_json(RESULTS_DIR / args.run_id / "teardown.json", {
        "restored": True, "timestamp": datetime.now().isoformat(),
    })
    print("[teardown] agent restored to standby")
    return 0


# ---------------------------------------------------------------------------
# full
# ---------------------------------------------------------------------------

def full(args) -> int:
    """Full: preflight -> setup -> agent -> grade -> report -> teardown.

    Teardown ALWAYS runs (even when the gate FAILs) so the agent returns to
    standby. Exit code = gate verdict: 0 PASS, 2 FAIL, 1 harness error.
    """
    phases = [
        ("preflight", preflight),
        ("setup", setup),
        ("agent", agent),
        ("grade", grade),
        ("report", report),
    ]
    gate_exit = GATE_PASS
    harness_error = False

    for name, fn in phases:
        print(f"\n[full] === {name} ===")
        # Crash-resumable: skip if output JSON exists unless --force
        out = RESULTS_DIR / args.run_id / f"{name}.json"
        if out.exists() and not getattr(args, "force", False):
            print(f"[full] {name}.json exists — skipping (use --force to re-run)")
            if name == "grade":
                g = _load_json(out) or {}
                gate_exit = GATE_PASS if g.get("gate_verdict") == "PASS" else GATE_FAIL
            continue
        rc = fn(args)
        if name in ("grade", "report"):
            if rc == GATE_ERROR:
                harness_error = True
            else:
                gate_exit = rc
        elif rc != 0:
            print(f"[full] {name} FAILED (exit {rc})")
            harness_error = True
            break

    # Teardown included in full — ALWAYS runs (even on gate FAIL)
    print(f"\n[full] === teardown ===")
    td_rc = teardown(args)
    if td_rc != 0:
        print(f"[full] teardown FAILED (exit {td_rc}) — agent may still be in benchmark mode")
        harness_error = True

    if harness_error:
        print("\n[full] HARNESS ERROR — see logs above")
        return GATE_ERROR
    print(f"\n[full] GATE SIGNAL: {'PASS (0)' if gate_exit == GATE_PASS else 'FAIL (2)'}")
    return gate_exit


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Windowless-room GATING TEST orchestrator (strict, deterministic, no LLM)"
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
        return p

    add_common(subparsers.add_parser("preflight"))
    sp = add_common(subparsers.add_parser("setup"))
    sp.add_argument("--seed-canonical", action="store_true")
    ap = add_common(subparsers.add_parser("agent"))
    ap.add_argument("--timeout-minutes", type=int, default=60)
    add_common(subparsers.add_parser("grade"))
    gp = subparsers.choices["grade"]
    for opt, help_ in [
        ("--answers-override", "read answers from this path instead of the volume"),
        ("--history-override", "read history.metta from this path"),
        ("--pre-snapshot-override", "use this file as the pre-benchmark snapshot"),
        ("--post-snapshot-override", "use this file as the post-benchmark snapshot"),
    ]:
        gp.add_argument(opt, default="", help=help_)
    add_common(subparsers.add_parser("report"))
    tp = add_common(subparsers.add_parser("teardown"))
    tp.add_argument("--cleanup", action="store_true")
    tp.add_argument("--allow-dirty-backup", action="store_true",
                    help="restore standby prompt even if the backup is contaminated")
    fp = add_common(subparsers.add_parser("full"))
    fp.add_argument("--seed-canonical", action="store_true")
    fp.add_argument("--cleanup", action="store_true")
    fp.add_argument("--timeout-minutes", type=int, default=60)
    fp.add_argument("--allow-dirty-backup", action="store_true")

    args = parser.parse_args()

    if not args.phase:
        parser.print_help()
        return 1

    dispatch = {
        "preflight": preflight, "setup": setup, "agent": agent,
        "grade": grade, "report": report, "teardown": teardown, "full": full,
    }
    return dispatch[args.phase](args)


if __name__ == "__main__":
    sys.exit(main())
