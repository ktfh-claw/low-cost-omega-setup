#!/usr/bin/env python3
"""Orchestrator CLI for the windowless-room reasoning benchmark.

Runs ON the OVH host (operator: ``ssh -p 9022 ubuntu@100.84.81.96``) from the
synced repo directory (``tests/reasoning-windowless-room/``). Phases:
preflight, setup, agent, grade, report, teardown, full.

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


def preflight(args) -> int:
    """Preflight phase: verify environment is ready for the benchmark."""
    # Resolve write-bridge / read-proxy IPs dynamically at run start;
    # the CLI defaults are fallbacks only.
    wb_ip = _container_ip(CONTAINER_WRITE_BRIDGE)
    rp_ip = _container_ip(CONTAINER_READ_PROXY)
    if wb_ip:
        args.write_bridge = f"http://{wb_ip}:8080"
    if rp_ip:
        args.read_proxy = f"http://{rp_ip}:8080"
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
            result = _run(["git", "-C", args.provenance_repo, "rev-parse", "--git-dir"])
            checks["provenance_repo"] = "ok" if result.returncode == 0 else "missing"
        except Exception as e:
            checks["provenance_repo"] = f"error: {e}"

    # 6. Agent memory volume exists
    if args.dry_run:
        checks["memory_volume"] = "dry-run"
    else:
        checks["memory_volume"] = "ok" if Path(args.memory_volume).exists() else "missing"

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


def setup(args) -> int:
    """Setup phase: archive sources, write benchmark files, install prompt, restart agent."""
    print("[setup] starting setup...")
    facts_mod = None
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
    prompts_lines = []
    for case in facts_mod.TEST_CASES:
        pf = HERE / "prompts" / case["prompt_file"]
        text = pf.read_text(encoding="utf-8") if pf.exists() else ""
        prompts_lines.append(f"=== CASE: {case['id']} ===")
        prompts_lines.append(text)
        prompts_lines.append(f"ANSWER FORMAT: FINAL ANSWER ({case['id']}): <answer>")
        prompts_lines.append("")
    prompts_content = "\n".join(prompts_lines)

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
            # 4. Copy history.metta
            _run(["sudo", "cp", str(vol / "history.metta"),
                  str(vol / f"history.pre-benchmark-{args.run_id}.metta")], timeout=60.0)
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

    def _sudo_read(path: Path) -> str | None:
        try:
            r = _run(["sudo", "cat", str(path)], timeout=30.0)
            if r.returncode == 0:
                return r.stdout
        except Exception:
            pass
        return None

    while time.time() - start < timeout_s:
        content = _sudo_read(answers_path)
        if content is not None:
            found = sum(1 for cid in case_ids if f"FINAL ANSWER ({cid}):" in content)
            elapsed = int((time.time() - start) / 60)
            print(f"[agent] {found}/{len(case_ids)} answers present ({elapsed}m elapsed)")
            if found == len(case_ids):
                print("[agent] COMPLETE — all answers present")
                _write_json(RESULTS_DIR / args.run_id / "agent.json", {
                    "status": "complete", "answers_found": found,
                })
                return 0
        time.sleep(60)

    print("[agent] TIMEOUT — recording partial state")
    _write_json(RESULTS_DIR / args.run_id / "agent.json", {"status": "timeout"})
    return 1


def grade(args) -> int:
    """Grade phase: parse answers, grade each case, verify traces + provenance."""
    sys.path.insert(0, str(HERE))
    import facts as facts_mod
    import grading as grading_mod

    answers_path = Path(args.memory_volume) / "benchmark" / "answers.md"
    if args.dry_run:
        print(f"[grade] [dry-run] would grade answers from {answers_path}")
        return 0
    read_r = _run(["sudo", "cat", str(answers_path)], timeout=30.0)
    if read_r.returncode != 0:
        print(f"[grade] ERROR: answers file not readable at {answers_path}")
        return 1
    content = read_r.stdout

    # Per-case trace check: the agent must quote real das-retrieve evidence
    # in the answers file (DAS_RETRIEVE_OK ... count=<digits>). Absence of
    # quoted evidence fails every case that requires a trace.
    has_retrieve_evidence = re.search(
        r"DAS_RETRIEVE_OK.*?count=\d+", content) is not None

    results = {}
    for case in facts_mod.TEST_CASES:
        das_queries = []
        if has_retrieve_evidence:
            das_queries = [{"query": "(present in answers)", "count": 1}]
        result = grading_mod.grade_case(case, content, das_queries)
        results[case["id"]] = {
            "verdict": result.verdict, "reason": result.reason, "evidence": result.evidence,
        }

    # Two-layer verification (simplified — re-issue queries via read-proxy)
    trace_verification = None
    if not args.dry_run:
        try:
            reissue = {}
            for case in facts_mod.TEST_CASES:
                q = "(Inheritance $X $Y)"
                resp = _http_post(args.read_proxy + "/v1/query", {
                    "metta": q, "max_answers": 10,
                }, timeout=30.0)
                reissue[q] = {"count": resp.get("count", 0), "results": resp.get("answers", [])}
            tv = grading_mod.verify_trace(
                [{"query": "(Inheritance $X $Y)", "count": 1, "results": []}],
                reissue, [], {},
            )
            trace_verification = {
                "trace_ok": tv.trace_ok, "provenance_ok": tv.provenance_ok,
            }
        except Exception as e:
            trace_verification = {"error": str(e)}

    grade_data = {
        "run_id": args.run_id,
        "per_case": results,
        "trace_evidence_present": has_retrieve_evidence,
        "trace_verification": trace_verification,
        "timestamp": datetime.now().isoformat(),
    }
    _write_json(RESULTS_DIR / args.run_id / "grade.json", grade_data)
    print(f"[grade] grade.json written to results/{args.run_id}/grade.json")
    return 0


def report(args) -> int:
    """Report phase: assemble report.json + report.md, print to stdout."""
    if args.dry_run:
        print(f"[report] [dry-run] would assemble results/{args.run_id}/report.json + report.md")
        return 0
    rd = RESULTS_DIR / args.run_id
    setup = _load_json(rd / "setup.json") or {}
    grade = _load_json(rd / "grade.json") or {}

    report = {
        "run_id": args.run_id,
        "setup": setup,
        "grade": grade,
        "timestamp": datetime.now().isoformat(),
    }
    _write_json(rd / "report.json", report)

    # Human-readable report.md
    lines = [f"# Windowless Room Benchmark Report — {args.run_id}", ""]
    lines.append("## Per-case results")
    lines.append("")
    lines.append("| Case | Verdict | Reason |")
    lines.append("|------|---------|--------|")
    for cid, r in (grade.get("per_case") or {}).items():
        lines.append(f"| {cid} | {r.get('verdict', '?')} | {r.get('reason', '')} |")
    lines.append("")
    report_md = "\n".join(lines)
    (rd / "report.md").write_text(report_md, encoding="utf-8")
    print(report_md)
    return 0


def teardown(args) -> int:
    """Teardown phase: restore agent to standby."""
    vol = Path(args.memory_volume)
    actions = []
    if args.dry_run:
        print(f"[teardown] [dry-run] planned actions:")
        print(f"  - restore prompt.txt from backup")
        print(f"  - restore omega_state.md from backup")
        print(f"  - append 'benchmark complete' line")
        print(f"  - sudo systemctl restart omega-curiosity.service")
        if getattr(args, "cleanup", False):
            print(f"  - [cleanup] remove benchmark DAS atoms via cleanup.py (links-only)")
        return 0

    try:
        # Restore original prompt + omega_state.md
        _run(["sudo", "cp", str(vol / f"prompt.txt.bak-pre-benchmark-{args.run_id}"),
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
            # Each fact via cleanup.py --metta "<expr>" links-only default
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


def full(args) -> int:
    """Full: preflight -> setup -> agent -> grade -> report (teardown included)."""
    phases = [
        ("preflight", preflight),
        ("setup", setup),
        ("agent", agent),
        ("grade", grade),
        ("report", report),
    ]
    for name, fn in phases:
        print(f"\n[full] === {name} ===")
        # Crash-resumable: skip if output JSON exists unless --force
        out = RESULTS_DIR / args.run_id / f"{name}.json"
        if out.exists() and not getattr(args, "force", False):
            print(f"[full] {name}.json exists — skipping (use --force to re-run)")
            continue
        rc = fn(args)
        if rc != 0:
            print(f"[full] {name} FAILED (exit {rc})")
            return rc
    # Teardown included in full
    print(f"\n[full] === teardown ===")
    rc = teardown(args)
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Windowless-room reasoning benchmark orchestrator"
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
    add_common(subparsers.add_parser("report"))
    tp = add_common(subparsers.add_parser("teardown"))
    tp.add_argument("--cleanup", action="store_true")
    fp = add_common(subparsers.add_parser("full"))
    fp.add_argument("--seed-canonical", action="store_true")
    fp.add_argument("--cleanup", action="store_true")
    fp.add_argument("--timeout-minutes", type=int, default=60)

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
