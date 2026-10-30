#!/usr/bin/env python3
"""L1 deltas (Balázs directive 2026-10-30 23:50 UTC): harness-side
state-vs-claim adherence cross-checks (delta 1), layer-split verdicts
(delta 2), and the stall watchdog (delta 3).

Additive harness lane — the A/Q/E/R/P mechanism gate semantics and the
existing grade-case / grade.json contracts stay pinned unchanged by the
existing suites. These tests pin the NEW lane only.

Live evidence basis (wr3t-20261028, case false): the agent pinned the
terminal ledger ``done: answer block written`` and sent a completion
claim while answers.md NEVER received the block (zero append-file
calls). The wr3s duplicate-block and the wr3r pre-write pin are the
same class: a deterministic contradiction between pinned claims and
volume file state. Emission lane = COMMAND_RETURN (docker logs); the
agent's pins are echoed ~8x inside later LLMRequest prompts (74 echo
vs 9 emission lines live) — echoes are excluded exactly like the
persist-receipt census.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import run_benchmark as rb


# --- live-shaped log lines (wr3t-20261028, verbatim shapes) -------------

LEDGER_TERMINAL = (
    "LEDGER: step 5 | done: answer block written | next: none — case "
    "complete, idle silently")
LEDGER_INTERMEDIATE = (
    "LEDGER: step 5 | done: terminal close-out composed | next: "
    "append-file repos/Omega/memory/benchmark/answers.md with the answer "
    "block once, then pin the done line")

PIN_EMISSION_TERMINAL = (
    '2026-10-30 23:43:06 | INFO     | loop | (COMMAND_RETURN: ((pin "'
    + LEDGER_TERMINAL + '") "SUCCESS, RETURN: PIN-SUCCESS"))')
PIN_EMISSION_INTERMEDIATE = (
    '2026-10-30 22:47:01 | INFO     | loop | (COMMAND_RETURN: ((pin "'
    + LEDGER_INTERMEDIATE + '") "SUCCESS, RETURN: PIN-SUCCESS"))')
PIN_REQUEST_ECHO = (
    "2026-10-30 23:44:00 | INFO     | loop | (REQUEST: "
    "LLMRequest[messages=[LLMMessage[role='system',content='... "
    + LEDGER_TERMINAL + " ...']")

BLOCK_FALSE = (
    "### CASE false\n\nQUERY: (Evaluation (Predicate \"reveals\") "
    "(List \"looking-up-illuminated-room\" $X))\nDAS_RETRIEVE_OK "
    "untrusted=true count=1\nFINAL ANSWER (false): FALSE\n")
BLOCK_ORIGINAL = "### CASE original\n\nQUERY: (x)\nFINAL ANSWER (original): yes\n"


def _pins_from_lines(lines):
    saved = rb._docker_logs_since
    rb._docker_logs_since = lambda c, s, u: "\n".join(lines)
    try:
        return rb._census_ledger_pins("2026-10-30T22:41:00Z",
                                     "2026-10-30T23:50:00Z")
    finally:
        rb._docker_logs_since = saved


# --- delta 1: ledger-pin census (emission lane) --------------------------

def test_ledger_pin_census_emission_lane_only():
    c = _pins_from_lines([PIN_REQUEST_ECHO, PIN_EMISSION_INTERMEDIATE,
                          PIN_EMISSION_TERMINAL])
    assert c["pins"] == [LEDGER_INTERMEDIATE, LEDGER_TERMINAL], c["pins"]
    assert c["window"] == ["2026-10-30T22:41:00Z", "2026-10-30T23:50:00Z"]


def test_ledger_pin_census_echo_excluded():
    c = _pins_from_lines([PIN_REQUEST_ECHO])
    assert c["pins"] == [], c["pins"]


def test_ledger_pin_census_error_not_gate_evidence():
    def boom(c, s, u):
        raise RuntimeError("docker down")
    saved = rb._docker_logs_since
    rb._docker_logs_since = boom
    try:
        c = rb._census_ledger_pins("a", "b")
    finally:
        rb._docker_logs_since = saved
    assert c["pins"] == []
    assert "error" in c


# --- delta 1: classify_adherence (state-vs-claim) -------------------------

def test_classify_false_completion():
    # wr3t live case: terminal pin claims the block exists; answers.md
    # has no block for the case -> the pinned claim is false.
    conds = rb.classify_adherence("false", LEDGER_TERMINAL, BLOCK_ORIGINAL)
    assert conds == ["ADHERENCE_FALSE_COMPLETION"], conds


def test_classify_consistent_terminal_clean():
    conds = rb.classify_adherence("false", LEDGER_TERMINAL,
                                  BLOCK_ORIGINAL + "\n" + BLOCK_FALSE)
    assert conds == [], conds


def test_classify_duplicate_block():
    # wr3q live class: two blocks for the case (last-wins grading hides
    # the discipline breach from the mechanism gate).
    conds = rb.classify_adherence("false", LEDGER_TERMINAL,
                                  BLOCK_FALSE + "\n" + BLOCK_FALSE)
    assert conds == ["ADHERENCE_DUPLICATE_BLOCK"], conds


def test_classify_intermediate_pin_incomplete_clean():
    # an intermediate close-out pin with no block is an INCOMPLETE case
    # (timeout lane), not a false claim.
    conds = rb.classify_adherence("false", LEDGER_INTERMEDIATE, BLOCK_ORIGINAL)
    assert conds == [], conds


def test_classify_no_pins_clean():
    assert rb.classify_adherence("false", "", BLOCK_FALSE) == []


def test_adherence_lane_shape():
    lane = rb._adherence_lane("false", {"pins": [LEDGER_TERMINAL]},
                             BLOCK_ORIGINAL)
    assert lane["conditions"] == ["ADHERENCE_FALSE_COMPLETION"]
    assert lane["evidence"]["last_ledger_pin"] == LEDGER_TERMINAL
    assert lane["evidence"]["block_count"] == 0
    assert lane["evidence"]["ledger_pin_count"] == 1


# --- delta 2: layer-split fields -------------------------------------------

def test_layer_split_fields_shape():
    fields = rb._layer_split_fields(
        "PASS", ["Q_ATTESTED_VIA_ACCESS_LOG"],
        {"conditions": ["ADHERENCE_FALSE_COMPLETION"],
         "evidence": {"block_count": 0}})
    assert fields["mechanism_verdict"] == "PASS"
    assert fields["mechanism_conditions"] == ["Q_ATTESTED_VIA_ACCESS_LOG"]
    assert fields["adherence_conditions"] == ["ADHERENCE_FALSE_COMPLETION"]
    assert fields["adherence_evidence"] == {"block_count": 0}


# --- delta 3: stall watchdog ------------------------------------------------

def test_watchdog_triggers_after_quiet_window():
    w = rb.StallWatchdog(stall_minutes=15, now=0.0)
    assert not w.should_abort(now=899.0)
    assert w.should_abort(now=901.0)


def test_watchdog_register_resets():
    w = rb.StallWatchdog(stall_minutes=15, now=0.0)
    w.register(moved=True, now=600.0)
    assert not w.should_abort(now=1400.0)
    assert w.should_abort(now=1501.0)


def test_watchdog_quiet_register_does_not_reset():
    w = rb.StallWatchdog(stall_minutes=15, now=100.0)
    w.register(moved=False, now=200.0)
    assert w.should_abort(now=100.0 + 901.0)


def test_default_stall_minutes():
    # Balázs directive 22:54 UTC: ~10-15 min is the healthy case budget;
    # the watchdog default is the upper bound of that range.
    assert rb.DEFAULT_STALL_MINUTES == 15
