"""Canary cleanup procedure (fake runner, upstream client stubbed)."""

from __future__ import annotations

import json

import pytest

import cleanup as cleanup_module
from cleanup import cleanup as run_cleanup
from conftest import EXPECTED_HANDLES, TOP_HANDLE, X402_METTA
from metta_to_atoms import MettaParseError
from write_client import WriteFailure

X402 = X402_METTA


class FakeCleanupRunner:
    def __init__(self, verify_missing=None, delete_error=None, verify_error=None):
        self.verify_missing = list(verify_missing or [])
        self.delete_error = delete_error
        self.verify_error = verify_error
        self.deletions = []

    def delete_atoms(self, handles, delete_link_targets=False):
        if self.delete_error is not None:
            raise self.delete_error
        self.deletions.append((list(handles), delete_link_targets))

    def verify_handles(self, fact):
        if self.verify_error is not None:
            raise self.verify_error
        return list(self.verify_missing)


class TestCleanup:
    def test_full_canary_cycle(self):
        runner = FakeCleanupRunner()
        result = run_cleanup(runner, X402)
        assert runner.deletions == [(EXPECTED_HANDLES, False)]
        assert result == {
            "deleted": EXPECTED_HANDLES,
            "absent": True,
            "still_present": [],
        }

    def test_still_present_links_reported(self):
        runner = FakeCleanupRunner(verify_missing=[TOP_HANDLE])
        result = run_cleanup(runner, X402)
        assert result["absent"] is False
        assert result["still_present"] == [TOP_HANDLE]

    def test_explicit_handles_must_match(self):
        runner = FakeCleanupRunner()
        result = run_cleanup(runner, X402, handles=list(EXPECTED_HANDLES))
        assert result["absent"] is True
        with pytest.raises(ValueError, match="does not match"):
            run_cleanup(runner, X402, handles=["a" * 32])
        # The mismatched call deleted nothing.
        assert runner.deletions == [(EXPECTED_HANDLES, False)]

    def test_delete_link_targets_flag(self):
        runner = FakeCleanupRunner()
        run_cleanup(runner, X402, delete_link_targets=True)
        assert runner.deletions == [(EXPECTED_HANDLES, True)]

    def test_no_verify_reports_absent_null(self):
        runner = FakeCleanupRunner(verify_missing=[TOP_HANDLE])
        result = run_cleanup(runner, X402, verify=False)
        assert result == {"deleted": EXPECTED_HANDLES, "absent": None, "still_present": []}
        assert runner.deletions == [(EXPECTED_HANDLES, False)]

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
        assert excinfo.value.handles == EXPECTED_HANDLES

    def test_delete_failure_propagates(self):
        runner = FakeCleanupRunner(delete_error=WriteFailure("atomdb-broker unreachable"))
        with pytest.raises(WriteFailure, match="atomdb-broker unreachable"):
            run_cleanup(runner, X402)


class TestCli:
    def test_success_exit_code_and_json(self, capsys, monkeypatch):
        runner = FakeCleanupRunner()
        monkeypatch.setattr(cleanup_module, "DasWriteRunner", lambda: runner)
        code = cleanup_module.main(["--metta", X402])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {
            "deleted": EXPECTED_HANDLES,
            "absent": True,
            "still_present": [],
        }

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
