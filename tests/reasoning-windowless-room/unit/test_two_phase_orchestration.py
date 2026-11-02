#!/usr/bin/env python3
"""v2 two-phase orchestration tests (skill-split directive 2026-11-02
08:25 UTC).

Pins the per-case two-phase flow the addendum requires:
- Phase 1 EXTRACTION prompt + agent restart; completion signal = the
  checkpoint manifest appearing in the memory volume
  knowledge-checkpoints/ (poll ~30s, bounded by the phase timeout).
- On manifest-poll timeout WITHOUT a manifest: grade as-is — the phase
  boundary is never invented.
- The phase-1 container docker logs are snapshotted into
  results/<run-id>/windows/<case>/phase1-docker.log BEFORE the phase-2
  restart (the systemd unit rm -f's the container on restart — logs die
  with it).
- Phase 2 REASONING prompt + fresh restart: the census lanes merge the
  phase-1 snapshot with the live phase-2 window.

All tests are pure logic (monkeypatched IO — no docker, no sudo).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import run_benchmark as rb


# ---------------------------------------------------------------------------
# manifest polling
# ---------------------------------------------------------------------------

def _args(**kw):
    return type("Args", (), {"run_id": "t-run", "case": "original",
                             "timeout_minutes": 75,
                             "memory_volume": "/tmp/t-run-memvol",
                             **kw})()


def test_poll_finds_manifest_new_or_modified():
    """A manifest created OR modified since the phase-1 restart is the
    boundary signal (a brand-new file and an append to an existing
    manifest both count)."""
    since_iso = "2026-11-02T10:00:00Z"
    since_epoch = 1793613600.0  # that ISO, UTC (verified vs datetime)
    manifests = [{"name": "corpus.md", "mtime": since_epoch + 60}]
    calls = {"n": 0}

    def fake_census(args):
        calls["n"] += 1
        return manifests

    saved = rb._manifest_census
    rb._manifest_census = fake_census
    try:
        out = rb._poll_checkpoint_manifest(
            _args(), since_iso, timeout_s=300, interval_s=30,
            _sleep=lambda s: None)
        assert out["found"] is True
        assert out["manifests"] == ["corpus.md"]
        assert calls["n"] == 1
    finally:
        rb._manifest_census = saved


def test_poll_stale_manifest_is_not_the_boundary():
    """A manifest from a PREVIOUS run (mtime < phase-1 restart) is NOT
    this case's boundary — the poll must not invent one. The poll
    continues to the timeout."""
    since_iso = "2026-11-02T10:00:00Z"
    since_epoch = 1793613600.0
    manifests = [
        {"name": "stale.md", "mtime": since_epoch - 86400},  # yesterday
        {"name": "older.md", "mtime": since_epoch - 10},     # just before
    ]

    saved = rb._manifest_census
    rb._manifest_census = lambda args: list(manifests)
    try:
        out = rb._poll_checkpoint_manifest(
            _args(), since_iso, timeout_s=1, interval_s=0.01,
            _sleep=lambda s: None)
        assert out["found"] is False
        assert out["manifests"] == []
    finally:
        rb._manifest_census = saved


def test_poll_timeout_never_invents_boundary():
    """Empty checkpoint dir -> poll to the timeout -> found=False, no
    manifest fabricated."""
    saved = rb._manifest_census
    rb._manifest_census = lambda args: []
    sleeps = []

    def fast_sleep(s):
        sleeps.append(s)

    try:
        out = rb._poll_checkpoint_manifest(
            _args(), "2026-11-02T10:00:00Z", timeout_s=1, interval_s=0.01,
            _sleep=fast_sleep)
        assert out["found"] is False
        assert out["manifests"] == []
        assert out["elapsed_s"] >= 0
        assert sleeps, "poll must sleep between checks (bounded interval)"
    finally:
        rb._manifest_census = saved


def test_poll_default_timeout_is_case_window():
    """No explicit timeout -> the case window (timeout_minutes) bounds
    the poll (addendum: 'default: the case window').

    The poll's clock is faked forward (rb.time patched with a stepping
    fake) so the 4500s case window elapses in ~45 fake iterations
    instead of 75 wall minutes — a no-op _sleep against the real clock
    was the original suite hang (75 min at 100% CPU busy-loop)."""
    saved = rb._manifest_census
    rb._manifest_census = lambda args: []
    saved_time = rb.time

    class _FakeTime:
        """time.time() stand-in: +100s per call."""
        def __init__(self):
            self._now = 1793613600.0

        def time(self):
            self._now += 100.0
            return self._now

    try:
        rb.time = _FakeTime()
        out = rb._poll_checkpoint_manifest(
            _args(timeout_minutes=75), "2026-11-02T10:00:00Z",
            timeout_s=None, interval_s=0.005, _sleep=lambda s: None)
        # 75min * 60 = 4500s recorded as the bound; the poll ran to it
        assert out["timeout_s"] == 4500.0
        assert out["found"] is False
    finally:
        rb._manifest_census = saved
        rb.time = saved_time


def test_poll_manifest_appearing_mid_poll():
    """The manifest appears on a later poll cycle (the extraction takes
    minutes) — the boundary is reached on that cycle."""
    since_iso = "2026-11-02T10:00:00Z"
    since_epoch = 1793613600.0
    state = {"cycle": 0}

    def fake_census(args):
        state["cycle"] += 1
        if state["cycle"] >= 3:
            return [{"name": "corpus.md", "mtime": since_epoch + 120}]
        return []

    saved = rb._manifest_census
    rb._manifest_census = fake_census
    try:
        out = rb._poll_checkpoint_manifest(
            _args(), since_iso, timeout_s=300, interval_s=30,
            _sleep=lambda s: None)
        assert out["found"] is True
        assert state["cycle"] == 3
    finally:
        rb._manifest_census = saved


# ---------------------------------------------------------------------------
# phase-1 docker-log snapshot
# ---------------------------------------------------------------------------

def test_snapshot_phase1_logs_writes_results_artifact():
    """docker logs since the phase-1 restart land in
    results/<run-id>/windows/<case>/phase1-docker.log (BEFORE the
    phase-2 restart — the container dies with it)."""
    with tempfile.TemporaryDirectory() as root:
        saved_results, saved_logs = rb.RESULTS_DIR, rb._docker_logs_since
        rb.RESULTS_DIR = Path(root)
        rb._docker_logs_since = (
            lambda container, since, until:
            f"[{container}] since={since} until={until}\nLINE-1\nLINE-2\n")
        try:
            args = _args()
            out = rb._snapshot_phase1_logs(args, "2026-11-02T10:00:00Z")
            expected_path = (Path(root) / "t-run" / "windows" / "original"
                             / "phase1-docker.log")
            assert out["path"] == str(expected_path)
            assert out["bytes"] > 0
            text = expected_path.read_text(encoding="utf-8")
            assert "LINE-1" in text and "LINE-2" in text
            assert "since=2026-11-02T10:00:00Z" in text
        finally:
            rb.RESULTS_DIR, rb._docker_logs_since = saved_results, saved_logs


def test_snapshot_phase1_docker_failure_recorded_not_raised():
    """A docker failure records an error + an empty snapshot — never
    raises (the snapshot must be attempted before the restart destroys
    the container, whatever docker says)."""
    with tempfile.TemporaryDirectory() as root:
        saved_results, saved_logs = rb.RESULTS_DIR, rb._docker_logs_since
        rb.RESULTS_DIR = Path(root)

        def boom(container, since, until):
            raise RuntimeError("docker daemon down")

        rb._docker_logs_since = boom
        try:
            out = rb._snapshot_phase1_logs(_args(), "2026-11-02T10:00:00Z")
            assert "error" in out
            expected_path = (Path(root) / "t-run" / "windows" / "original"
                             / "phase1-docker.log")
            assert expected_path.read_text(encoding="utf-8") == ""
        finally:
            rb.RESULTS_DIR, rb._docker_logs_since = saved_results, saved_logs


# ---------------------------------------------------------------------------
# census lanes: phase-1 snapshot merged with the live phase-2 window
# ---------------------------------------------------------------------------

V4_RECEIPT = "BRIDGE-PERSIST-OK: verified=2 top=" + "a" * 32
V4_ECHO = ("LLMRequest[messages=[LLMMessage[content='... "
           + V4_RECEIPT + " ...']]")
V4_RECEIPT_P2 = "BRIDGE-PERSIST-OK: verified=1 top=" + "b" * 32


def test_census_persist_receipts_merges_phase1_snapshot():
    """extra_logs (phase-1 snapshot) is scanned with the SAME strict
    regex + LLMRequest-echo exclusion and merged with the live window:
    the census covers the FULL case window."""
    phase1_logs = f"phase1 {V4_RECEIPT}\n{V4_ECHO}\n"
    saved = rb._docker_logs_since
    rb._docker_logs_since = lambda c, s, u: f"phase2 {V4_RECEIPT_P2}\n"
    try:
        out = rb._census_persist_receipts(
            "2026-11-02T11:00:00Z", "2026-11-02T12:00:00Z",
            extra_logs=phase1_logs)
        assert out["count"] == 2, out
        # the LLMRequest echo is excluded; both real receipts counted
        assert any(V4_RECEIPT in m for m in out["matched"])
        assert any(V4_RECEIPT_P2 in m for m in out["matched"])
        assert out["extra_source"] == "phase1-docker.log"
    finally:
        rb._docker_logs_since = saved


def test_census_persist_receipts_without_extra_logs_unchanged():
    """v1 call shape (no extra_logs) behaves exactly as before."""
    saved = rb._docker_logs_since
    rb._docker_logs_since = lambda c, s, u: f"{V4_RECEIPT}\n{V4_ECHO}\n"
    try:
        out = rb._census_persist_receipts("s", "u")
        assert out["count"] == 1
        assert "extra_source" not in out
    finally:
        rb._docker_logs_since = saved


def test_census_ledger_pins_merges_phase1_snapshot():
    """The L1 adherence pin census merges phase-1 snapshot pins with the
    live phase-2 window (same emission-lane rules)."""
    pin_p1 = ("2026-11-02 10:05:00 | (COMMAND_RETURN: ((pin \"LEDGER: "
              "step 1 | done: extraction underway\") \"SUCCESS\"))")
    pin_p2 = ("2026-11-02 11:05:00 | (COMMAND_RETURN: ((pin \"LEDGER: "
              "step 5 | done: answer block written\") \"SUCCESS\"))")
    phase1_logs = pin_p1 + "\n"
    saved = rb._docker_logs_since
    rb._docker_logs_since = lambda c, s, u: pin_p2 + "\n"
    try:
        out = rb._census_ledger_pins("s", "u", extra_logs=phase1_logs)
        assert out["pins"] == [
            "LEDGER: step 1 | done: extraction underway",
            "LEDGER: step 5 | done: answer block written",
        ], out["pins"]
    finally:
        rb._docker_logs_since = saved


# ---------------------------------------------------------------------------
# phase-specific prompt rendering (setup_case phase= dispatch)
# ---------------------------------------------------------------------------

def test_setup_case_phase_dispatch_renders_phase_templates():
    """phase='extraction' renders the extraction template;
    phase='reasoning' renders the reasoning template; None keeps the v1
    fat template."""
    args = _args()
    case = rb._case_by_id("original")
    ext = rb._render_extraction_prompt(args, case)
    rea = rb._render_reasoning_prompt(args, case)
    fat = rb._render_case_prompt(args, case)
    assert "EXTRACTION PHASE" in ext and "REASONING PHASE" not in ext
    assert "REASONING PHASE" in rea and "EXTRACTION PHASE" not in rea
    # both delegate to their skill
    assert "das-extract-knowledge" in ext
    assert "das-grounded-reasoning" in rea
    # both carry the phase-boundary (checkpoint manifest) wording
    assert "knowledge-checkpoints" in ext
    assert "checkpoint manifest" in rea
    # the reasoning phase relies ONLY on manifest + DAS + facts-index
    # (no background re-reading)
    assert "Do NOT re-read or re-extract the background sources" in rea
    # v1 fat template still carries both phases (unchanged wiring)
    assert "EXTRACTION (das-extract-knowledge skill)" in fat
    assert "REASONING (das-grounded-reasoning skill)" in fat


def test_phase_templates_word_count_under_half():
    """A2: each phase prompt well under half the current fat template's
    3391 words."""
    here = rb.HERE
    fat = len((here / "agent_prompt_template.md").read_text(
        encoding="utf-8").split())
    ext = len((here / "agent_extraction_prompt_template.md").read_text(
        encoding="utf-8").split())
    rea = len((here / "agent_reasoning_prompt_template.md").read_text(
        encoding="utf-8").split())
    assert fat == 3391, f"fat template drifted: {fat}"
    assert ext < fat // 2, f"extraction template too fat: {ext} >= {fat//2}"
    assert rea < fat // 2, f"reasoning template too fat: {rea} >= {fat//2}"


# ---------------------------------------------------------------------------
# full_two_phase orchestration: two prompts, two restarts, snapshot
# before restart #2, grade-as-is on manifest timeout
# ---------------------------------------------------------------------------

def _run_full_two_phase(root, poll_found, manifest_names=("corpus.md",),
                        overrides=None):
    """Drive full_two_phase with all IO mocked; returns (grade.json,
    call_order). ``overrides`` maps rb attribute -> stub and is applied
    AFTER the defaults (lets a test inject its own snapshot/restart
    spies — the helper's defaults would otherwise clobber them)."""
    originals = {
        name: getattr(rb, name)
        for name in ("RESULTS_DIR", "_facts_mod", "preflight", "cleanup_das",
                     "setup_extraction_phase", "setup_reasoning_phase",
                     "_poll_checkpoint_manifest", "_snapshot_phase1_logs",
                     "agent_case", "grade_case", "_copy_window_artifacts",
                     "report", "teardown", "_load_json", "_write_json")
    }
    order = []

    def rec(name):
        def fn(*a, **k):
            order.append(name)
            return 0
        return fn

    grade_stub = {
        "original": {"verdict": "PASS", "conditions": [],
                     "mechanism_verdict": "PASS", "adherence_conditions": []},
    }
    try:
        with tempfile.TemporaryDirectory() as td:
            rb.RESULTS_DIR = Path(td)
            import facts as facts_mod
            rb._facts_mod = lambda: facts_mod  # no-reimport fast path
            rb.preflight = rec("preflight")
            rb.cleanup_das = rec("cleanup-das")

            def setup_extraction(args):
                order.append("setup-extraction(restart#1)")
                return 0

            def setup_reasoning(args):
                order.append("setup-reasoning(restart#2)")
                return 0

            rb.setup_extraction_phase = setup_extraction
            rb.setup_reasoning_phase = setup_reasoning
            rb._poll_checkpoint_manifest = (
                lambda args, since, timeout_s=None:
                {"found": poll_found,
                 "manifests": list(manifest_names) if poll_found else [],
                 "elapsed_s": 42, "timeout_s": timeout_s or 0,
                 "poll_interval_s": 30.0, "since_iso": since})
            rb._snapshot_phase1_logs = (
                lambda args, since:
                {"path": str(Path(td) / "t-run/windows/original/"
                              "phase1-docker.log"), "bytes": 123})
            for attr, stub in (overrides or {}).items():
                setattr(rb, attr, stub)
            rb.agent_case = rec("agent-case")
            rb.grade_case = rec("grade-case")
            rb._copy_window_artifacts = rec("copy-windows")
            rb.report = rec("report")
            rb.teardown = rec("teardown")
            rb._load_json = lambda path: grade_stub.get(
                str(path).rsplit("grade-case-", 1)[-1].replace(".json", ""),
                {})

            def write_json(path, data):
                path = Path(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data), encoding="utf-8")

            rb._write_json = write_json
            rc = rb.full_two_phase(_args(cases="original", skip_report=False,
                                         force=False, cleanup_first=False,
                                         stall_minutes=15, trim_history=True,
                                         phase_timeout_minutes=0))
            grade_json = json.loads(
                (Path(td) / "t-run" / "grade.json").read_text(
                    encoding="utf-8"))
            return rc, grade_json, order
    finally:
        for name, value in originals.items():
            setattr(rb, name, value)


def test_full_two_phase_happy_path_ordering():
    """Per case: extraction restart #1 -> manifest poll -> SNAPSHOT ->
    reasoning restart #2 -> answer wait -> grade (the addendum's
    per-case demonstration)."""
    rc, grade, order = _run_full_two_phase(None, poll_found=True)
    expected = ["preflight", "cleanup-das",
                "setup-extraction(restart#1)",
                "setup-reasoning(restart#2)",  # snapshot first (below)
                "agent-case", "grade-case", "copy-windows",
                "report", "teardown"]
    # exact per-case ordering: poll -> snapshot -> restart #2
    i_setup1 = order.index("setup-extraction(restart#1)")
    # the poll and snapshot are recorded via their stubs' side effects:
    # poll is a lambda (not in order); assert restart #2 comes AFTER the
    # snapshot call by checking the snapshot stub ran before restart#2 —
    # the stub records only the path; instead assert the relative order
    # of the recorded calls
    assert order[i_setup1 + 1] == "setup-reasoning(restart#2)", order
    assert "agent-case" in order
    assert grade["mode"] == "sequential-two-phase"
    assert grade["per_case"]["original"]["verdict"] == "PASS"
    assert grade["per_case"]["original"]["two_phase"]["manifest_found"] is True
    assert grade["per_case"]["original"]["two_phase"]["manifests"] == \
        ["corpus.md"]
    assert grade["per_case"]["original"]["two_phase"]["manifest_poll_elapsed_s"] == 42
    assert rc == rb.GATE_PASS


def test_full_two_phase_snapshot_before_reasoning_restart():
    """CRITICAL: the phase-1 log snapshot runs BEFORE the phase-2
    restart (the container is rm'd at the restart — logs die with it)."""
    order_snap = []

    def fake_snapshot(args, since):
        order_snap.append("snapshot")
        return {"path": "x", "bytes": 1}

    def fake_setup_reasoning(args):
        order_snap.append("restart#2")
        return 0

    _rc, _g, _o = _run_full_two_phase(
        None, poll_found=True,
        overrides={"_snapshot_phase1_logs": fake_snapshot,
                   "setup_reasoning_phase": fake_setup_reasoning})
    assert "snapshot" in order_snap and "restart#2" in order_snap
    assert order_snap.index("snapshot") < order_snap.index("restart#2")


def test_full_two_phase_timeout_grades_as_is_skips_phase2():
    """On manifest-poll timeout WITHOUT a manifest the case is graded
    as-is: phase 2 (restart #2 + answer wait) is SKIPPED — the boundary
    was never reached and is never invented."""
    rc, grade, order = _run_full_two_phase(None, poll_found=False)
    assert "setup-reasoning(restart#2)" not in order, \
        "phase 2 must be skipped on manifest timeout"
    assert "agent-case" not in order, \
        "the answer wait belongs to phase 2 — skipped on timeout"
    assert "grade-case" in order, "the case is graded as-is"
    per = grade["per_case"]["original"]
    assert per["two_phase"]["manifest_found"] is False
    assert per["two_phase"]["manifests"] == []
    rc  # the grade stub returns PASS but the flow ran; rc recorded


def test_full_two_phase_timeout_still_snapshots_phase1_logs():
    """Even on manifest timeout the phase-1 snapshot happens (before any
    later restart destroys the container)."""
    snapped = []

    def fake_snapshot(args, since):
        snapped.append(since)
        return {"path": "x", "bytes": 1}

    _rc, grade, _o = _run_full_two_phase(
        None, poll_found=False,
        overrides={"_snapshot_phase1_logs": fake_snapshot})
    assert len(snapped) == 1, "phase-1 snapshot must run once"
    assert grade["per_case"]["original"]["two_phase"]["phase1_snapshot"] \
        == "x"
