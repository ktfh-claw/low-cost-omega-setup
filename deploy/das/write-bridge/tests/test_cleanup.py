"""Canary cleanup procedure (fake runner, upstream client stubbed)."""

from __future__ import annotations

import json

import pytest

import cleanup as cleanup_module
from cleanup import cleanup as run_cleanup
from conftest import EXPECTED_HANDLES, TOP_HANDLE, X402_METTA
from metta_to_atoms import MettaParseError, parse_fact
from write_client import WriteFailure

X402 = X402_METTA
# Split by atom arity (NOT by handle order: the x402 fact's bottom-up order
# interleaves nodes and links: Symbol, Symbol, Symbol, LINK, Symbol, LINK,
# LINK).
_FACT = parse_fact(X402)
LINK_HANDLES = _FACT.link_handles
NODE_HANDLES = [
    handle for atom, handle in zip(_FACT.atoms, _FACT.handles) if atom.arity() == 0
]


class FakeCleanupRunner:
    def __init__(self, verify_missing=None, delete_error=None, verify_error=None):
        self.verify_missing = list(verify_missing or [])
        self.delete_error = delete_error
        self.verify_error = verify_error
        self.deletions = []
        self.verify_calls = 0

    def delete_atoms(self, handles, delete_link_targets=False):
        if self.delete_error is not None:
            raise self.delete_error
        self.deletions.append((list(handles), delete_link_targets))

    def verify_handles(self, fact):
        self.verify_calls += 1
        if self.verify_error is not None:
            raise self.verify_error
        return list(self.verify_missing)


class TestCleanup:
    def test_full_canary_cycle(self):
        # Default scope: ONLY the fact's Expression links. Symbol nodes are
        # shared across facts on a live DB (live-measured iteration 3) and
        # must never be deleted by default. Clean read-back on the first
        # check: absent immediately, exactly one verification pass.
        runner = FakeCleanupRunner()
        result = run_cleanup(runner, X402)
        assert runner.deletions == [(LINK_HANDLES, False)]
        assert result == {
            "deleted": LINK_HANDLES,
            "absent": True,
            "still_present": [],
            "attempts": 1,
        }

    def test_delete_nodes_deletes_every_fact_handle(self):
        # Opt-in full wipe: only safe on a scratch DB owned by the caller.
        runner = FakeCleanupRunner()
        run_cleanup(runner, X402, delete_nodes=True)
        assert runner.deletions == [(EXPECTED_HANDLES, False)]

    def test_still_present_links_reported(self):
        runner = FakeCleanupRunner(verify_missing=[TOP_HANDLE])
        result = run_cleanup(runner, X402, grace_seconds=0)
        assert result["absent"] is False
        assert result["still_present"] == [TOP_HANDLE]
        assert result["attempts"] == 1

    def test_explicit_handles_must_belong_to_fact(self):
        runner = FakeCleanupRunner()
        # A subset of the fact's handles (e.g. the canary's unique nodes for
        # zero-residue cleanup) is accepted and verifiable: bare nodes are
        # not covered by the link walk, so absence is reported as null.
        result = run_cleanup(runner, X402, handles=list(NODE_HANDLES))
        assert runner.deletions == [(NODE_HANDLES, False)]
        assert result == {"deleted": NODE_HANDLES, "absent": None, "still_present": [], "attempts": 0}
        with pytest.raises(ValueError, match="do not belong"):
            run_cleanup(runner, X402, handles=["a" * 32])
        # The mismatched call deleted nothing.
        assert runner.deletions == [(NODE_HANDLES, False)]

    def test_delete_link_targets_flag(self):
        runner = FakeCleanupRunner()
        run_cleanup(runner, X402, delete_link_targets=True)
        assert runner.deletions == [(LINK_HANDLES, True)]

    def test_no_verify_reports_absent_null(self):
        runner = FakeCleanupRunner(verify_missing=[TOP_HANDLE])
        result = run_cleanup(runner, X402, verify=False)
        assert result == {"deleted": LINK_HANDLES, "absent": None, "still_present": [], "attempts": 0}
        assert runner.deletions == [(LINK_HANDLES, False)]

    def test_parse_error_propagates_before_delete(self):
        runner = FakeCleanupRunner()
        with pytest.raises(MettaParseError):
            run_cleanup(runner, "(a")
        assert runner.deletions == []

    def test_verification_failure_wraps_handles(self):
        runner = FakeCleanupRunner(verify_error=WriteFailure("read-back query timed out"))
        with pytest.raises(WriteFailure) as excinfo:
            run_cleanup(runner, X402)
        assert "deletion verification failed" in str(excinfo.value)
        assert excinfo.value.handles == LINK_HANDLES

    def test_delete_failure_propagates(self):
        runner = FakeCleanupRunner(delete_error=WriteFailure("atomdb-broker unreachable"))
        with pytest.raises(WriteFailure, match="atomdb-broker unreachable"):
            run_cleanup(runner, X402)


class TestGraceWindow:
    """Bounded retry for the eventual server-side delete apply.

    Live-measured iteration 3: a read-back ~1 s after the delete command
    can still match the deleted links (server-side apply is not
    instantaneous), while ~1 s later the same query returns 0 answers.
    The absence verification therefore re-checks inside a bounded grace
    window instead of false-alarming on the first check.
    """

    class EventualDeleteRunner(FakeCleanupRunner):
        """Server-side delete applies on the Nth read-back check."""

        def __init__(self, absent_after):
            super().__init__(verify_missing=[TOP_HANDLE])
            self.absent_after = absent_after

        def verify_handles(self, fact):
            self.verify_calls += 1
            if self.verify_calls > self.absent_after:
                return []
            return list(self.verify_missing)

    def test_retries_until_absent(self, monkeypatch):
        # Present on the first two checks (delete still applying), gone on
        # the third: absent, three attempts, no early false alarm.
        runner = self.EventualDeleteRunner(absent_after=2)
        sleeps = []
        monkeypatch.setattr(cleanup_module.time, "sleep", lambda s: sleeps.append(s))
        result = run_cleanup(runner, X402, grace_seconds=30, poll_interval=0)
        assert result == {
            "deleted": LINK_HANDLES,
            "absent": True,
            "still_present": [],
            "attempts": 3,
        }
        assert len(sleeps) == 2
        assert runner.verify_calls == 3

    def test_default_window_absorbs_observed_apply_latency(self, monkeypatch):
        # The shipped defaults (300 s grace / 5 s poll, iteration 6) must
        # absorb the live-measured worst case (~90-96 s apply, iteration 5
        # runs C/D; earlier samples 1-33 s): a delete that lands on the third
        # check resolves absent with the DEFAULTS, no flags.
        runner = self.EventualDeleteRunner(absent_after=2)
        sleeps = []
        monkeypatch.setattr(cleanup_module.time, "sleep", lambda s: sleeps.append(s))
        assert cleanup_module.DEFAULT_VERIFY_GRACE_SECONDS == 300.0
        assert cleanup_module.DEFAULT_VERIFY_POLL_INTERVAL == 5.0
        result = run_cleanup(runner, X402)  # default grace/poll
        assert result["absent"] is True
        assert result["attempts"] == 3
        assert runner.verify_calls == 3

    def test_window_expiry_reports_still_present(self, monkeypatch):
        # Delete genuinely stuck: the window closes and the result reports
        # what is still present (never loops forever). Zero and negative
        # windows still perform exactly one check.
        for grace in (0, -5):
            runner = FakeCleanupRunner(verify_missing=LINK_HANDLES)
            sleeps = []
            monkeypatch.setattr(cleanup_module.time, "sleep", lambda s: sleeps.append(s))
            result = run_cleanup(runner, X402, grace_seconds=grace, poll_interval=0)
            assert result["absent"] is False
            assert result["still_present"] == LINK_HANDLES
            assert result["attempts"] == 1
            assert sleeps == []

    def test_verification_failure_fails_fast(self):
        # A bus-level read-back failure is not evidence of eventual deletion:
        # it raises immediately instead of being retried inside the window.
        runner = FakeCleanupRunner(verify_error=WriteFailure("read-back query timed out"))
        with pytest.raises(WriteFailure, match="deletion verification failed"):
            run_cleanup(runner, X402, grace_seconds=30, poll_interval=0)
        assert runner.verify_calls == 1


class TestCli:
    def test_success_exit_code_and_json(self, capsys, monkeypatch):
        runner = FakeCleanupRunner()
        monkeypatch.setattr(cleanup_module, "DasWriteRunner", lambda: runner)
        code = cleanup_module.main(["--metta", X402])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {
            "deleted": LINK_HANDLES,
            "absent": True,
            "still_present": [],
            "attempts": 1,
        }

    def test_grace_flags_accepted(self, capsys, monkeypatch):
        # --grace-seconds / --poll-interval reach cleanup(): a stuck delete
        # reports absent: false after exactly one check with a zero window.
        runner = FakeCleanupRunner(verify_missing=[TOP_HANDLE])
        monkeypatch.setattr(cleanup_module, "DasWriteRunner", lambda: runner)
        code = cleanup_module.main(
            ["--metta", X402, "--grace-seconds", "0", "--poll-interval", "0"]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["absent"] is False
        assert payload["attempts"] == 1

    def test_handle_flags_accepted(self, capsys, monkeypatch):
        runner = FakeCleanupRunner()
        monkeypatch.setattr(cleanup_module, "DasWriteRunner", lambda: runner)
        args = ["--metta", X402, "--no-verify"]
        for handle in EXPECTED_HANDLES:
            args += ["--handle", handle]
        code = cleanup_module.main(args)
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["absent"] is None

    def test_bad_metta_is_usage_error(self, capsys, monkeypatch):
        monkeypatch.setattr(cleanup_module, "DasWriteRunner", lambda: FakeCleanupRunner())
        code = cleanup_module.main(["--metta", "(a"])
        assert code == 2
        assert "error" in json.loads(capsys.readouterr().err)

    def test_bus_failure_exit_code(self, capsys, monkeypatch):
        runner = FakeCleanupRunner(delete_error=WriteFailure("atomdb-broker unreachable"))
        monkeypatch.setattr(cleanup_module, "DasWriteRunner", lambda: runner)
        code = cleanup_module.main(["--metta", X402])
        assert code == 1
        assert "error" in json.loads(capsys.readouterr().err)
