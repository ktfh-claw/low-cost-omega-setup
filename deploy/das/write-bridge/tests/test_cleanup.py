"""Canary cleanup procedure (fake runner, upstream client stubbed)."""

from __future__ import annotations

import json

import pytest

import cleanup as cleanup_module
from cleanup import cleanup as run_cleanup
from conftest import (
    ALT_EXPECTED_ASSIGNMENTS,
    ALT_T_TOP,
    EXPECTED_HANDLES,
    INNER_X402_HANDLE,
    INNER_PP_HANDLE,
    T_INNER_PP,
    T_INNER_X402,
    T_TOP,
    TOP_HANDLE,
    X402_METTA,
)
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
# The x402 fact's oracle coverage: the top link (arity 3) admits the tight
# alternate form; the 2-arity inner links do not (schema-ambiguous loose
# form, live-measured iteration 6b) and fall back to the primary pattern.
ALT_COVERED = {TOP_HANDLE}
PRIMARY_COVERED = [INNER_X402_HANDLE, INNER_PP_HANDLE]


class FakeCleanupRunner:
    """Routes match_link calls through scripted per-pattern answers.

    ``answers_by_pattern`` maps a token tuple to "does the live answer set
    still contain the link" (True = still matches). The oracle dispatch
    (alternate tokens for alt-covered links, primary tokens otherwise) is
    asserted against the exact expected pattern list.
    """

    def __init__(self, answers_by_pattern=None, delete_error=None, verify_error=None):
        self.answers_by_pattern = dict(answers_by_pattern or {})
        self.delete_error = delete_error
        self.verify_error = verify_error
        self.deletions = []
        self.matched_patterns = []

    def delete_atoms(self, handles, delete_link_targets=False):
        if self.delete_error is not None:
            raise self.delete_error
        self.deletions.append((list(handles), delete_link_targets))

    def match_link(self, tokens, handle, expected_assignment):
        self.matched_patterns.append((tuple(tokens), handle, expected_assignment))
        return self.answers_by_pattern.get(tuple(tokens), False)


def primary_patterns():
    """The primary variable-form patterns for every link, in link_queries order."""
    return {
        tuple(tokens): handle for handle, tokens, _ in _FACT.link_queries
    }


def alt_patterns():
    """The alternate-oracle patterns, in link_absence_queries order."""
    return {
        tuple(tokens): handle for handle, tokens, _ in _FACT.link_absence_queries
    }


def _one_pass_runner():
    """A runner whose oracle pass issues the exact expected pattern set once."""
    return FakeCleanupRunner()


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
            "checks": 1,
            "standby_seconds": 0.0,
        }

    def test_oracle_dispatch_alternate_and_primary(self):
        # The oracle pass must query alt-covered links through their
        # ALTERNATE tokens and the rest through the primary variable form
        # -- one query per link, in link_queries order.
        runner = FakeCleanupRunner()
        run_cleanup(runner, X402)
        primaries = primary_patterns()
        alts = alt_patterns()
        assert set(alts) == {tuple(ALT_T_TOP)}, "top link is the only alt-covered one"
        assert runner.matched_patterns == [
            (tuple(T_INNER_X402), INNER_X402_HANDLE, {"unassigned": "5e50ef7542bb0fde52aed0d841335790"}),
            (tuple(T_INNER_PP), INNER_PP_HANDLE, {"unassigned": "5e50ef7542bb0fde52aed0d841335790"}),
            (tuple(ALT_T_TOP), TOP_HANDLE, ALT_EXPECTED_ASSIGNMENTS[tuple(ALT_T_TOP)]),
        ]

    def test_delete_nodes_deletes_every_fact_handle(self):
        # Opt-in full wipe: only safe on a scratch DB owned by the caller.
        runner = FakeCleanupRunner()
        run_cleanup(runner, X402, delete_nodes=True)
        assert runner.deletions == [(EXPECTED_HANDLES, False)]

    def test_still_present_links_reported(self):
        runner = FakeCleanupRunner({tuple(ALT_T_TOP): True})
        result = run_cleanup(runner, X402, recheck_limit=0)
        assert result["absent"] is False
        assert result["still_present"] == [TOP_HANDLE]
        assert result["checks"] == 1
        assert result["standby_seconds"] == 0.0

    def test_primary_fallback_still_present(self):
        # A 2-arity link (no tight alternate form) still matching through
        # its PRIMARY pattern must be reported as still present.
        runner = FakeCleanupRunner({tuple(T_INNER_X402): True})
        result = run_cleanup(runner, X402, recheck_limit=0)
        assert result["absent"] is False
        assert result["still_present"] == [INNER_X402_HANDLE]

    def test_explicit_handles_must_belong_to_fact(self):
        runner = FakeCleanupRunner()
        # A subset of the fact's handles (e.g. the canary's unique nodes for
        # zero-residue cleanup) is accepted and verifiable: bare nodes are
        # not covered by the link walk, so absence is reported as null.
        result = run_cleanup(runner, X402, handles=list(NODE_HANDLES))
        assert runner.deletions == [(NODE_HANDLES, False)]
        assert result == {
            "deleted": NODE_HANDLES,
            "absent": None,
            "still_present": [],
            "checks": 0,
            "standby_seconds": 0.0,
        }
        with pytest.raises(ValueError, match="do not belong"):
            run_cleanup(runner, X402, handles=["a" * 32])
        # The mismatched call deleted nothing.
        assert runner.deletions == [(NODE_HANDLES, False)]

    def test_delete_link_targets_flag(self):
        runner = FakeCleanupRunner()
        run_cleanup(runner, X402, delete_link_targets=True)
        assert runner.deletions == [(LINK_HANDLES, True)]

    def test_no_verify_reports_absent_null(self):
        runner = FakeCleanupRunner({tuple(ALT_T_TOP): True})
        result = run_cleanup(runner, X402, verify=False)
        assert result == {
            "deleted": LINK_HANDLES,
            "absent": None,
            "still_present": [],
            "checks": 0,
            "standby_seconds": 0.0,
        }
        assert runner.deletions == [(LINK_HANDLES, False)]

    def test_parse_error_propagates_before_delete(self):
        runner = FakeCleanupRunner()
        with pytest.raises(MettaParseError):
            run_cleanup(runner, "(a")
        assert runner.deletions == []

    def test_verification_failure_wraps_handles(self):
        class FailingRunner(FakeCleanupRunner):
            def match_link(self, tokens, handle, expected_assignment):
                raise WriteFailure("read-back query timed out")

        runner = FailingRunner()
        with pytest.raises(WriteFailure) as excinfo:
            run_cleanup(runner, X402)
        assert "deletion verification failed" in str(excinfo.value)
        assert excinfo.value.handles == LINK_HANDLES

    def test_delete_failure_propagates(self):
        runner = FakeCleanupRunner(delete_error=WriteFailure("atomdb-broker unreachable"))
        with pytest.raises(WriteFailure, match="atomdb-broker unreachable"):
            run_cleanup(runner, X402)


class TestStandbyRechecks:
    """Bounded query-free standby for the eventual, starved delete apply.

    Live-measured iterations 3-6: the server-side delete apply is starved
    by sustained verification traffic -- every polling grace window
    (30/90/300 s) false-alarmed while the deletion always landed seconds
    after the loop stopped querying. The oracle therefore WAITS query-free
    between checks instead of polling, a bounded number of times.
    """

    def test_stale_match_then_absent_after_standby(self, monkeypatch):
        # First pass: the alt oracle still matches (stale). After one
        # query-free standby the apply has landed: absent, two passes, the
        # standby time accounted.
        class StaleFirstPassRunner(FakeCleanupRunner):
            # The alt pattern matches only during pass 1 (the x402 fact's
            # oracle pass is 3 match calls); after the standby the live
            # answer set no longer contains the link.
            def match_link(self, tokens, handle, expected_assignment):
                self.matched_patterns.append((tuple(tokens), handle, expected_assignment))
                return tuple(tokens) == tuple(ALT_T_TOP) and len(self.matched_patterns) <= 3

        sleeps = []
        monkeypatch.setattr(cleanup_module.time, "sleep", lambda s: sleeps.append(s))
        runner = StaleFirstPassRunner()
        result = run_cleanup(runner, X402, recheck_limit=3, recheck_wait_seconds=10)
        assert result["absent"] is True
        assert result["checks"] == 2
        assert result["standby_seconds"] == 10.0
        assert sleeps == [10.0]
        # Both passes issued the full oracle pattern set.
        assert len(runner.matched_patterns) == 6  # 2 passes x 3 links

    def test_rechecks_stop_at_limit(self, monkeypatch):
        # The apply never lands inside the window: exactly recheck_limit
        # standbys + re-checks, then absent: false with what matched.
        sleeps = []
        monkeypatch.setattr(cleanup_module.time, "sleep", lambda s: sleeps.append(s))
        runner = FakeCleanupRunner({tuple(ALT_T_TOP): True})
        result = run_cleanup(runner, X402, recheck_limit=2, recheck_wait_seconds=5)
        assert result["absent"] is False
        assert result["still_present"] == [TOP_HANDLE]
        assert result["checks"] == 3  # initial pass + 2 re-checks
        assert result["standby_seconds"] == 10.0
        assert sleeps == [5.0, 5.0]

    def test_zero_recheck_limit_single_pass(self, monkeypatch):
        # recheck_limit=0: exactly one verification pass, no standby.
        sleeps = []
        monkeypatch.setattr(cleanup_module.time, "sleep", lambda s: sleeps.append(s))
        runner = FakeCleanupRunner({tuple(T_INNER_PP): True})
        result = run_cleanup(runner, X402, recheck_limit=0)
        assert result["absent"] is False
        assert result["still_present"] == [INNER_PP_HANDLE]
        assert result["checks"] == 1
        assert result["standby_seconds"] == 0.0
        assert sleeps == []

    def test_total_standby_is_bounded(self, monkeypatch):
        # The pathological ceiling: however large the requested wait, the
        # total standby never exceeds MAX_TOTAL_STANDBY_SECONDS.
        sleeps = []
        monkeypatch.setattr(cleanup_module.time, "sleep", lambda s: sleeps.append(s))
        runner = FakeCleanupRunner({tuple(ALT_T_TOP): True})
        run_cleanup(runner, X402, recheck_limit=5, recheck_wait_seconds=60)
        assert sum(sleeps) <= cleanup_module.MAX_TOTAL_STANDBY_SECONDS
        assert all(s <= 60 for s in sleeps)
        # The final check after the clipped wait still ran.
        assert runner.matched_patterns  # at least the first pass

    def test_verification_failure_fails_fast(self, monkeypatch):
        # A bus-level read-back failure is not evidence of eventual deletion:
        # it raises immediately instead of being retried after standby.
        sleeps = []
        monkeypatch.setattr(cleanup_module.time, "sleep", lambda s: sleeps.append(s))

        class FailingRunner(FakeCleanupRunner):
            def match_link(self, tokens, handle, expected_assignment):
                self.matched_patterns.append((tuple(tokens), handle, expected_assignment))
                raise WriteFailure("read-back query timed out")

        runner = FailingRunner()
        with pytest.raises(WriteFailure, match="deletion verification failed"):
            run_cleanup(runner, X402, recheck_limit=3, recheck_wait_seconds=0)
        assert len(runner.matched_patterns) == 1  # raised on the first link
        assert sleeps == []  # never entered standby


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
            "checks": 1,
            "standby_seconds": 0.0,
        }

    def test_recheck_flags_accepted(self, capsys, monkeypatch):
        # --recheck-limit / --recheck-wait-seconds reach cleanup(): a stuck
        # delete reports absent: false after exactly one check with a zero
        # re-check limit.
        runner = FakeCleanupRunner({tuple(ALT_T_TOP): True})
        monkeypatch.setattr(cleanup_module, "DasWriteRunner", lambda: runner)
        code = cleanup_module.main(
            ["--metta", X402, "--recheck-limit", "0", "--recheck-wait-seconds", "0"]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["absent"] is False
        assert payload["checks"] == 1
        assert payload["standby_seconds"] == 0.0

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
