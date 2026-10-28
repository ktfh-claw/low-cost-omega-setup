#!/usr/bin/env python3
"""v17 item 7 (resolution 5): preflight v4 contract tests (offline).

Transparent provenance (issue #2) rewires the preflight phase:

  write_bridge_smoke   the FULL v4 path, not a suffix-less v1 write:
                       POST /v1/source {ref, sha256} (facade records the
                       pair without fetching; the sha256 of a synthetic
                       payload is the correct citation) → POST /v1/write
                       with provenance {ref, "git:"+commit, sha256}
                       → the 200 MUST carry a non-empty top_handle.
                       The ledger entry is PERMANENT EVIDENCE
                       (clearly-labeled preflight.invalid ref); only the
                       DAS links are cleaned up (cleanup.py --metta).
  ledger_repo_format   REQUIRED, replaces provenance_repo (which only
                       proved a git repo existed): invokes the Phase-3
                       verification helper (tools/migrate_ledger_repo.sh
                       --check) — the committed source of truth; exit 0
                       → "ok", else the helper's first FAIL: line (or
                       "FAIL: <stderr tail>"), which FAILS preflight.
  das_write_grammar_v3 the mounted das-write.metta must carry the v3
                       receipt marker "BRIDGE-PERSIST-OK: verified=<n>
                       top=<handle>" (skill_description_upgraded grep
                       pattern).
  no dasWriteSourceRoots check — D5: the benchmark exercises URL refs
  only; path refs are never used by this flow.

All tests are offline: _http_post / _run / _sudo_run are monkeypatched
module attributes (the established pattern — test_v4_levers.FakeVol,
test_v10_gates); no network, docker or git.
"""
import hashlib
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


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


def _preflight_passes(value: str) -> bool:
    """The preflight ok_values pass-set predicate (run_benchmark)."""
    return (value in {"ok", "running", "dry-run"}
            or value.startswith("dry-run")
            or value.startswith("172.") or value.startswith("10.")
            or value.startswith("192.168.")
            or (value.startswith("count=") and value != "count=0"))


def _fake_post(calls, source=None, write=None):
    """Route fakes by URL suffix; `source`/`write` are dicts (200s) or
    exceptions to raise. Appends (url, body) to `calls`."""
    def post(url, body, timeout=30.0):
        calls.append((url, body))
        if url.endswith("/v1/source"):
            if isinstance(source, Exception):
                raise source
            return dict(source)
        if url.endswith("/v1/write"):
            if isinstance(write, Exception):
                raise write
            return dict(write)
        raise AssertionError(f"unexpected preflight URL: {url}")
    return post


def _capture_run(calls):
    def run(cmd, timeout=30.0):
        calls.append([str(c) for c in cmd])
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


def _smoke_args(run_id="unit-smoke"):
    return SimpleNamespace(run_id=run_id,
                           write_bridge="http://172.20.0.5:8080")


# ---------------------------------------------------------------------------
# (a) write_bridge_smoke: full v4 path
# ---------------------------------------------------------------------------

def test_smoke_v4_happy_path_registers_source_then_writes_with_provenance():
    import run_benchmark as rb
    calls, run_calls = [], []
    commit = "a1b2c3d4" * 5  # bare 40-hex from the facade
    run_id = "smoke-happy"
    source = {"commit": commit, "deduped": False,
              "entry_date": "2026-10-28T00:00:00Z"}
    write = {"handles": ["h1", "h2"], "verified": 2, "missing": [],
             "top_handle": "h2"}
    args = _smoke_args(run_id)
    with ModPatch(_http_post=_fake_post(calls, source=source, write=write),
                  _run=_capture_run(run_calls)):
        smoke, cleanup = rb._write_bridge_smoke_v4(args)
    assert smoke == "ok", smoke
    assert cleanup == "ok", cleanup
    # step 1: /v1/source first, with the deterministic (ref, sha256) pair
    assert len(calls) == 2, calls
    src_url, src_body = calls[0]
    assert src_url.endswith("/v1/source")
    ref = f"https://preflight.invalid/omega-ledger-smoke-{run_id}"
    sha = hashlib.sha256(f"omega-preflight-smoke-v4:{run_id}".encode()).hexdigest()
    assert src_body == {"ref": ref, "sha256": sha}
    # step 2: /v1/write cites the returned BARE commit as "git:"+40hex
    write_url, write_body = calls[1]
    assert write_url.endswith("/v1/write")
    assert write_body["metta"] == f'(BenchmarkPreflight (Concept "{run_id}"))'
    assert write_body["verify"] is True
    assert write_body["provenance"] == {"ref": ref, "git_commit": "git:" + commit,
                                        "blob_sha256": sha}
    # links-only cleanup after the successful write, with the smoke expr,
    # targeting the real write-bridge container
    assert len(run_calls) == 1, run_calls
    assert run_calls[0] == ["docker", "exec", "-w", "/app",
                            rb.CONTAINER_WRITE_BRIDGE,
                            "python", "cleanup.py", "--metta",
                            f'(BenchmarkPreflight (Concept "{run_id}"))']


def test_smoke_v4_empty_top_handle_is_error():
    import run_benchmark as rb
    calls, run_calls = [], []
    source = {"commit": "b" * 40, "deduped": True, "entry_date": "x"}
    for write in ({"handles": ["h"], "verified": 1, "missing": [],
                   "top_handle": ""},
                  {"handles": ["h"], "verified": 1, "missing": []},
                  {"handles": ["h"], "verified": 1, "missing": [],
                   "top_handle": None}):
        calls.clear(), run_calls.clear()
        with ModPatch(_http_post=_fake_post(calls, source=source, write=write),
                      _run=_capture_run(run_calls)):
            smoke, cleanup = rb._write_bridge_smoke_v4(_smoke_args())
        assert smoke.startswith("error:"), smoke
        assert smoke != "ok"
        assert not _preflight_passes(smoke)
        # the write DID persist atoms (200) — cleanup still attempted
        assert cleanup == "ok"


def test_smoke_v4_source_failure_skips_write_and_cleanup():
    calls, run_calls = [], []
    with ModPatch(_http_post=_fake_post(
            calls, source=RuntimeError("HTTP 503: ledger unavailable")),
            _run=_capture_run(run_calls)):
        import run_benchmark as rb
        smoke, cleanup = rb._write_bridge_smoke_v4(_smoke_args())
    assert smoke.startswith("error:"), smoke
    assert "ledger unavailable" in smoke
    # /v1/write was never called and no cleanup ran (nothing written)
    assert len(calls) == 1 and calls[0][0].endswith("/v1/source")
    assert run_calls == []


def test_smoke_v4_write_http_failure_is_error():
    calls, run_calls = [], []
    source = {"commit": "c" * 40, "deduped": False, "entry_date": "x"}
    with ModPatch(_http_post=_fake_post(
            calls, source=source, write=RuntimeError("HTTP 502: write failed")),
            _run=_capture_run(run_calls)):
        import run_benchmark as rb
        smoke, cleanup = rb._write_bridge_smoke_v4(_smoke_args())
    assert smoke.startswith("error:"), smoke
    assert "502" in smoke
    assert cleanup == ""
    assert run_calls == []


# ---------------------------------------------------------------------------
# (b) ledger_repo_format: the Phase-3 helper via sudo
# ---------------------------------------------------------------------------

def _ledger_args():
    return SimpleNamespace(provenance_repo="/home/ubuntu/omega-provenance")


def test_ledger_repo_format_ok_invokes_helper():
    seen = []

    def sudo_run(cmd, timeout=60.0):
        seen.append([str(c) for c in cmd])
        return SimpleNamespace(returncode=0, stdout="PASS: all checks\n", stderr="")

    import run_benchmark as rb
    with ModPatch(_sudo_run=sudo_run):
        value = rb._ledger_repo_format(_ledger_args())
    assert value == "ok"
    assert seen == [["bash", str(rb.LEDGER_HELPER), "--check",
                    "--repo", "/home/ubuntu/omega-provenance"]]


def test_ledger_repo_format_fail_line_from_stdout():
    def sudo_run(cmd, timeout=60.0):
        return SimpleNamespace(
            returncode=1,
            stdout="FAIL: HEAD touches non-ledger paths (README.md)\n",
            stderr="")

    import run_benchmark as rb
    with ModPatch(_sudo_run=sudo_run):
        value = rb._ledger_repo_format(_ledger_args())
    assert value == "FAIL: HEAD touches non-ledger paths (README.md)"
    assert value.startswith("FAIL:")
    # the FAIL value must actually fail preflight (ok_values pass-set)
    assert not _preflight_passes(value)


def test_ledger_repo_format_fail_stderr_tail():
    def sudo_run(cmd, timeout=60.0):
        return SimpleNamespace(
            returncode=1, stdout="",
            stderr="migrate_ledger_repo.sh: line 9: git: command not found\n"
                   "final stderr line\n")

    import run_benchmark as rb
    with ModPatch(_sudo_run=sudo_run):
        value = rb._ledger_repo_format(_ledger_args())
    assert value == "FAIL: final stderr line"
    assert not _preflight_passes(value)


def test_ledger_repo_format_subprocess_exception_is_error():
    def sudo_run(cmd, timeout=60.0):
        raise FileNotFoundError("sudo: no docker host")

    import run_benchmark as rb
    with ModPatch(_sudo_run=sudo_run):
        value = rb._ledger_repo_format(_ledger_args())
    assert value.startswith("error:")
    assert not _preflight_passes(value)


def test_ledger_helper_path_resolves_to_committed_helper():
    # the wiring cannot silently point at a stale/missing helper path
    import run_benchmark as rb
    here = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.abspath(os.path.join(
        here, "..", "..", "..", "deploy", "das", "write-bridge", "tools",
        "migrate_ledger_repo.sh"))
    assert str(rb.LEDGER_HELPER) == expected
    assert os.path.isfile(expected)


# ---------------------------------------------------------------------------
# (c) das_write_grammar_v3: the v3 receipt marker in the mounted plugin
# ---------------------------------------------------------------------------

def test_das_write_grammar_v3_ok():
    seen = []

    def run(cmd, timeout=30.0):
        seen.append([str(c) for c in cmd])
        return SimpleNamespace(returncode=0, stdout="1\n", stderr="")

    import run_benchmark as rb
    with ModPatch(_run=run):
        value = rb._das_write_grammar_v3()
    assert value == "ok"
    assert seen[0][:2] == ["grep", "-c"]
    assert seen[0][2] == "BRIDGE-PERSIST-OK: verified=<n> top=<handle>"
    assert seen[0][3].endswith("deploy/omega/plugins/das-write/das-write.metta")


def test_das_write_grammar_v3_missing_on_zero_count():
    import run_benchmark as rb
    for stdout, rc in (("0\n", 0), ("", 2)):
        def run(cmd, timeout=30.0, stdout=stdout, rc=rc):
            return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
        with ModPatch(_run=run):
            value = rb._das_write_grammar_v3()
        assert value == "MISSING", value
        assert not _preflight_passes(value)


def test_das_write_grammar_v3_marker_in_repo_artifact():
    # the grep pattern must match the COMMITTED plugin (guards pattern
    # rot: if the repo artifact loses the marker, the check is MISSING
    # and this test fails with a clear signal)
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "..", "..", "deploy", "omega", "plugins",
                        "das-write", "das-write.metta")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "BRIDGE-PERSIST-OK: verified=<n> top=<handle>" in content


# ---------------------------------------------------------------------------
# dry-run integration + the retired-key contract
# ---------------------------------------------------------------------------

def test_preflight_dry_run_v4_check_names():
    captured = {}

    def fake_write_json(path, data):
        captured["path"] = path
        captured["data"] = data

    args = SimpleNamespace(
        dry_run=True, run_id="unit-dryrun",
        write_bridge="http://172.20.0.5:8080",
        read_proxy="http://172.20.0.3:8080",
        provenance_repo="/home/ubuntu/omega-provenance",
        memory_volume="/fake/vol",
    )
    with ModPatch(_container_ip=lambda container: "",
                  _write_json=fake_write_json):
        import run_benchmark as rb
        rc = rb.preflight(args)
    assert rc == 0
    checks = captured["data"]["checks"]
    assert captured["data"]["all_ok"] is True
    # the v4 keys are present as dry-run
    assert checks["write_bridge_smoke"] == "dry-run"
    assert checks["ledger_repo_format"] == "dry-run"
    assert checks["das_write_grammar_v3"] == "dry-run"
    # the retired v1-era key is GONE
    assert "provenance_repo" not in checks
    # unchanged checks keep their dry-run entries
    for name in ("read_proxy_query", "memory_volume", "prompt_backup_fresh",
                 "skill_description_upgraded", "metta_skill_upgraded",
                 "metta_plugin_mounted", "canary_fetch_ai", "judge_smoke"):
        assert checks[name] == "dry-run", name


def test_preflight_source_has_no_archive_references():
    # item 7 (d): the v4 preflight must not reference the retired
    # archive lane anywhere in the preflight function
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "run_benchmark.py"),
              encoding="utf-8") as f:
        src = f.read()
    start = src.index("def preflight(args)")
    end = src.find("\ndef ", start + 1)
    body = src[start:end]
    assert "/v1/archive" not in body
    assert "ARCHIVE-OK" not in body
    # and the smoke helper (the new smoke) is archive-free too
    hstart = src.index("def _write_bridge_smoke_v4")
    hend = src.find("\ndef ", hstart + 1)
    hbody = src[hstart:hend]
    assert "/v1/archive" not in hbody
    assert "ARCHIVE-OK" not in hbody
