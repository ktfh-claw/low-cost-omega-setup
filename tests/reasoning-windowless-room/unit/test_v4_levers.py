"""Unit tests for the v4 levers (wr3b post-mortem, 2026-10-24 directive):

Lever 3 — per-case serialized-history trim: setup-case archives history.metta
to the pre-case snapshot, then resets it to a comment-only window marker so
every LLM call of the case serializes only that case's episodes (root cause
of the wr3/wr3b timeouts: ~1.6 MB day-history in every request starved the
cycle budget). Run-start backs up the FULL pre-run history; teardown restores
it (no-trace contract). --no-trim-history keeps the v3 behavior.

Lever 4 — 75-minute default per-case window (was 45 m). Harness parameter
only; strict gates unchanged.

Deterministic only — no LLM, no network, no docker. The sudo-callable
helpers are monkeypatched with an in-memory volume.
"""
import os
import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import run_benchmark as rb


# ---------------------------------------------------------------------------
# lever 4 (window default) + lever 3 flag wiring
# ---------------------------------------------------------------------------

def test_full_default_window_75_minutes():
    args = rb.build_parser().parse_args(["full", "--run-id", "t"])
    assert args.timeout_minutes == 75, args.timeout_minutes


def test_setup_case_default_window_75_minutes():
    args = rb.build_parser().parse_args(["setup-case", "--case", "original", "--run-id", "t"])
    assert args.timeout_minutes == 75, args.timeout_minutes


def test_timeout_minutes_overridable():
    args = rb.build_parser().parse_args(["full", "--run-id", "t", "--timeout-minutes", "60"])
    assert args.timeout_minutes == 60
    args = rb.build_parser().parse_args(["agent-case", "--case", "false", "--run-id", "t",
                                         "--timeout-minutes", "90"])
    assert args.timeout_minutes == 90


def test_trim_history_default_on_all_case_phases():
    for phase in ("setup-case", "agent-case", "grade-case"):
        argv = [phase, "--case", "original", "--run-id", "t"]
        args = rb.build_parser().parse_args(argv)
        assert getattr(args, "trim_history", None) is True, phase


def test_no_trim_history_opts_out():
    for argv in (["full", "--run-id", "t", "--no-trim-history"],
                 ["setup-case", "--case", "original", "--run-id", "t", "--no-trim-history"]):
        args = rb.build_parser().parse_args(argv)
        assert args.trim_history is False, argv


def test_grade_case_keeps_trim_flag_out_of_gate_logic():
    # the trim flag exists on grade-case only for CLI symmetry; grading must
    # never consult it
    import grading
    src = Path(grading.__file__).read_text(encoding="utf-8")
    assert "trim_history" not in src


# ---------------------------------------------------------------------------
# lever 3 core: the trim marker itself
# ---------------------------------------------------------------------------

def test_trim_marker_is_comment_only_metta():
    m = rb._trim_marker("wr3c-20261024", "original")
    for ln in m.splitlines():
        assert ln.startswith(";"), ln
    assert m.endswith("\n")


def test_trim_marker_identifies_run_and_case():
    m = rb._trim_marker("wr3c-20261024", "false")
    assert "wr3c-20261024" in m and "false" in m


def test_trim_marker_is_never_parsed_as_an_episode():
    import history_parse
    # the marker must contribute ZERO retrievals / receipts / shas to any
    # window it appears in
    m = rb._trim_marker("r", "c") * 3
    assert history_parse.extract_retrieve_args(m) == []
    assert history_parse.count_placeholder_retrieves(m) == 0
    assert history_parse.extract_persist_receipts(m) == []
    assert history_parse.extract_archive_receipts(m) == []
    assert history_parse.extract_add_atom_shas(m) == []


def test_window_from_texts_with_trimmed_history_falls_back_to_full():
    import history_parse
    marker = rb._trim_marker("r", "c")
    # post-trim: pre-snapshot is the OLD full history; the live file starts
    # with the marker, not with the pre-snapshot -> fallback mode "full",
    # window = current content = this case only
    old = '(("2026-10-23 20:00:00" ((shell "old")))\n'
    case_episodes = '(("2026-10-24 07:00:00" ((query "(Inheritance (Concept "ceiling") $X)")))\n'
    window, mode = history_parse.window_from_texts(marker + case_episodes, old, None)
    assert mode == "full"
    assert "old" not in window
    assert "ceiling" in window


# ---------------------------------------------------------------------------
# lever 3 live-path: setup_case / teardown against a fake volume
# ---------------------------------------------------------------------------

class FakeVol:
    """In-memory replacement for the sudo-callable volume helpers."""

    def __init__(self, files: dict):
        self.files = dict(files)

    def install(self):
        self._orig = {
            "read": rb._sudo_read, "write": rb._sudo_write, "run": rb._sudo_run,
            "restart": rb._agent_restart, "subprocess_run": rb.subprocess.run,
        }
        rb._sudo_read = self._read
        rb._sudo_write = self._write
        rb._sudo_run = self._run
        rb._agent_restart = lambda: True
        rb.subprocess.run = self._subprocess_run

    def restore(self):
        rb._sudo_read, rb._sudo_write, rb._sudo_run = (
            self._orig["read"], self._orig["write"], self._orig["run"])
        rb._agent_restart = self._orig["restart"]
        rb.subprocess.run = self._orig["subprocess_run"]

    def _read(self, path, timeout=60.0):
        p = str(path)
        return self.files.get(p) if p in self.files else None

    def _subprocess_run(self, cmd, *args, **kwargs):
        # teardown's direct subprocess.run(["sudo", "tee", ...]) append
        cmd = [str(c) for c in cmd]
        if cmd[:2] == ["sudo", "tee"]:
            self.files[cmd[2]] = self.files.get(cmd[2], "") + (kwargs.get("input") or "")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["sudo", "test"]:
            p = cmd[3] if len(cmd) > 3 else ""
            returncode = 0 if p in self.files else 1
            return SimpleNamespace(returncode=returncode, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess.run call: {cmd}")

    def _write(self, path, content, timeout=60.0):
        self.files[str(path)] = content
        return True

    def _run(self, cmd, timeout=60.0):
        # NOTE: this fakes rb._sudo_run, which receives the command WITHOUT
        # the 'sudo' prefix (the real _sudo_run adds it)
        cmd = [str(c) for c in cmd]
        out = SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["test", "-f"]:
            p = cmd[2]
            out.returncode = 0 if p in self.files else 1
            return out
        if cmd[:2] == ["test", "-d"]:
            out.returncode = 0  # permissive: not exercised by these tests
            return out
        if cmd[0] == "test":
            raise AssertionError(f"unexpected test form: {cmd}")
        if cmd[0] == "cp":
            src, dst = cmd[1], cmd[2]
            if src not in self.files:
                out.returncode = 1
                return out
            self.files[dst] = self.files.get(src)
            return out
        if cmd[0] == "rm":
            # 'rm -f <path>' (and multi-path forms): remove every non-flag
            # argument that exists in the fake volume
            for a in cmd[1:]:
                if not a.startswith("-"):
                    self.files.pop(a, None)
            return out
        if cmd[0] == "mkdir":
            return out
        if cmd[0] == "chown":
            return out
        if cmd[0] == "systemctl":
            return out  # restart: no-op (also patched via _agent_restart)
        if cmd[0] == "sh":
            # teardown snapshot globbing / rm list: no stdout -> no-op
            return out
        # default: record the call (unexpected sudo commands fail loudly)
        raise AssertionError(f"unexpected sudo call: {cmd}")


def _fake_args(run_id="t-run", case="original", trim=True):
    return SimpleNamespace(
        run_id=run_id, case=case, dry_run=False,
        memory_volume="/fake/vol", trim_history=trim,
        timeout_minutes=75,
    )


def _seed_files(run_id):
    vol = "/fake/vol"
    return {
        f"{vol}/prompt.txt": "STANDBY PROMPT",
        f"{vol}/omega_state.md": "standby state",
        f"{vol}/history.metta": '(("2026-10-23 20:00:00" ((shell "day history")))\n',
        f"{vol}/benchmark/answers.md": "old",
        f"{vol}/benchmark/facts-index.md": "old",
    }


def test_setup_case_trims_history_on_run_start():
    fv = FakeVol(_seed_files("t-run"))
    fv.install()
    try:
        # first setup of the run: backups created, THEN trim
        rc = rb.setup_case(_fake_args("t-run", "original"))
        assert rc == 0, rc
        f = fv.files
        # 1. full pre-run history archived (no-trace contract evidence)
        assert "day history" in f["/fake/vol/history.bak-pre-benchmark-t-run"]
        # 2. standby prompt + state backed up
        assert f["/fake/vol/prompt.txt.bak-pre-benchmark-t-run"] == "STANDBY PROMPT"
        # 3. pre-case snapshot archived the pre-trim history
        pre = f["/fake/vol/history.pre-case-t-run-original.metta"]
        assert "day history" in pre
        # 4. live history replaced by the comment-only marker
        assert f["/fake/vol/history.metta"] == rb._trim_marker("t-run", "original")
        # 5. fresh answers.md / facts-index.md on run start
        assert f["/fake/vol/benchmark/answers.md"].startswith("# Benchmark answers")
        # 6. setup JSON records the trim
        import json
        sj = json.loads((rb.RESULTS_DIR / "t-run" / "setup-case-original.json").read_text())
        assert sj["history_trimmed"] is True
    finally:
        fv.restore()
        _cleanup_results("t-run")


def test_setup_case_trim_is_per_case_not_per_run():
    fv = FakeVol(_seed_files("t-run"))
    fv.install()
    try:
        assert rb.setup_case(_fake_args("t-run", "original")) == 0
        # case 1 writes episodes into history (simulated)
        fv.files["/fake/vol/history.metta"] = (
            rb._trim_marker("t-run", "original") + '(("2026-10-24 07:10:00" ((query "q1")))\n')
        rc = rb.setup_case(_fake_args("t-run", "false"))
        assert rc == 0, rc
        # the SECOND case must ALSO be trimmed (marker of case 2, not case 1)
        assert fv.files["/fake/vol/history.metta"] == rb._trim_marker("t-run", "false")
        # and the case-1 episodes must be archived in the case-2 pre-snapshot
        pre2 = fv.files["/fake/vol/history.pre-case-t-run-false.metta"]
        assert "q1" in pre2
        # answers.md NOT re-initialized on later cases (cross-case carry-over)
        assert "Benchmark answers" in fv.files["/fake/vol/benchmark/answers.md"]
    finally:
        fv.restore()
        _cleanup_results("t-run")


def test_setup_case_no_trim_keeps_v3_behavior():
    fv = FakeVol(_seed_files("t-run"))
    fv.install()
    try:
        rc = rb.setup_case(_fake_args("t-run", "original", trim=False))
        assert rc == 0, rc
        # history untouched; backup NOT created (nothing to restore)
        assert "day history" in fv.files["/fake/vol/history.metta"]
        assert "/fake/vol/history.bak-pre-benchmark-t-run" not in fv.files
        import json
        sj = json.loads((rb.RESULTS_DIR / "t-run" / "setup-case-original.json").read_text())
        assert sj["history_trimmed"] is False
    finally:
        fv.restore()
        _cleanup_results("t-run")


def test_setup_case_continuation_run_still_backs_up_without_reinit():
    """--cases without `original`: backups created, answers.md NOT reset."""
    fv = FakeVol(_seed_files("t-run"))
    fv.install()
    try:
        fv.files["/fake/vol/benchmark/answers.md"] = "### CASE original\n...accumulated\n"
        fv.files["/fake/vol/benchmark/facts-index.md"] = "(Inheritance (Concept \"room\") (Concept \"enclosed-space\"))\n"
        rc = rb.setup_case(_fake_args("t-run", "false"))
        assert rc == 0, rc
        assert fv.files["/fake/vol/prompt.txt.bak-pre-benchmark-t-run"] == "STANDBY PROMPT"
        assert any(k.endswith("history.bak-pre-benchmark-t-run") for k in fv.files)
        # accumulated record preserved
        assert "accumulated" in fv.files["/fake/vol/benchmark/answers.md"]
        assert "enclosed-space" in fv.files["/fake/vol/benchmark/facts-index.md"]
    finally:
        fv.restore()
        _cleanup_results("t-run")


def test_teardown_restores_pre_run_history():
    fv = FakeVol(_seed_files("t-run"))
    fv.install()
    try:
        assert rb.setup_case(_fake_args("t-run", "original")) == 0
        # simulate the case: agent appends episodes to the trimmed history
        fv.files["/fake/vol/history.metta"] = (
            rb._trim_marker("t-run", "original") + '(("2026-10-24 07:20:00" ((query "case-ep")))\n')
        # teardown must restore prompt + state + history
        rc = rb.teardown(SimpleNamespace(
            run_id="t-run", dry_run=False, memory_volume="/fake/vol",
            keep_snapshots=False, allow_dirty_backup=False))
        assert rc == 0, rc
        assert fv.files["/fake/vol/prompt.txt"] == "STANDBY PROMPT"
        assert "day history" in fv.files["/fake/vol/history.metta"]
        assert "case-ep" not in fv.files["/fake/vol/history.metta"]
        # backup removed from the volume
        assert "/fake/vol/history.bak-pre-benchmark-t-run" not in fv.files
        # pre-run history archived to results (forensic evidence)
        pre = (rb.RESULTS_DIR / "t-run" / "history.pre-run.metta").read_text()
        assert "day history" in pre
    finally:
        fv.restore()
        _cleanup_results("t-run")


def test_teardown_without_trim_run_is_noop_for_history():
    fv = FakeVol(_seed_files("t-run"))
    fv.install()
    try:
        assert rb.setup_case(_fake_args("t-run", "original", trim=False)) == 0
        rc = rb.teardown(SimpleNamespace(
            run_id="t-run", dry_run=False, memory_volume="/fake/vol",
            keep_snapshots=False, allow_dirty_backup=False))
        assert rc == 0, rc
        # no history backup existed -> nothing restored, history untouched
        assert "day history" in fv.files["/fake/vol/history.metta"]
    finally:
        fv.restore()
        _cleanup_results("t-run")


def test_setup_case_trim_failure_aborts():
    fv = FakeVol(_seed_files("t-run"))
    fv.install()
    try:
        def failing_write(path, content, timeout=60.0):
            if str(path).endswith("history.metta") and content.startswith(";"):
                return False  # trim write fails
            return fv._write(path, content, timeout)
        rb._sudo_write = failing_write
        rc = rb.setup_case(_fake_args("t-run", "original"))
        assert rc == rb.GATE_ERROR
        # pre-case snapshot still archived; history NOT marked
        assert "day history" in fv.files["/fake/vol/history.metta"]
    finally:
        fv.restore()
        _cleanup_results("t-run")


def _cleanup_results(run_id):
    import shutil
    rd = rb.RESULTS_DIR / run_id
    if rd.exists():
        shutil.rmtree(rd)


# ---------------------------------------------------------------------------
# dry-run wording (operator visibility of the active lever configuration)
# ---------------------------------------------------------------------------

def test_setup_case_dry_run_mentions_trim_when_on():
    import io, contextlib
    args = _fake_args("t-run", "original", trim=True)
    args.dry_run = True
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rb.setup_case(args)
    assert rc == 0
    assert "trim history to the per-case window marker" in buf.getvalue()


def test_setup_case_dry_run_mentions_keep_when_off():
    import io, contextlib
    args = _fake_args("t-run", "original", trim=False)
    args.dry_run = True
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rb.setup_case(args)
    assert "keep full history" in buf.getvalue()
