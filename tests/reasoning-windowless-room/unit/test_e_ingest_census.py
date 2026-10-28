#!/usr/bin/env python3
r"""v17 harness iteration 2: E_NO_INGEST agent-container census (wr3o-20261028).

Live wr3o-20261028 evidence (2026-10-28): under v17 transparency the agent
is UNAWARE of provenance (by design) and the serialized history collapses
tool calls to ``$_`` tuples, so the per-case history windows carry ZERO
persist receipts — the receipts-only E_NO_INGEST census
(``history_parse.extract_persist_receipts`` over the window) fired
E_NO_INGEST on the original case although the agent container's docker
logs carried 374 real v4 receipt lines. The receipts ARE emitted today —
the plugin emits ``BRIDGE-PERSIST-OK: verified=<n> top=<32-hex>``
(das_write_bridge.py:549) — but on the AGENT-CONTAINER stdout, and the
container is REPLACED at every setup/teardown restart (start.sh trap
rm -f), so the census is valid LIVE (grade right after the case) and
grade-time must PERSIST the matched lines into the run dir (retroactive
re-grading of a dead container's logs is impossible).

Fix (run_benchmark.py grade-case): mirror the Q-gate access-log lane —
read the agent container's docker logs bounded by [setup restarted_at,
grade-now] via the existing ``_docker_logs_since``, count STRICT v4
receipt lines, prefer the docker-log census over the (lossy) history
window census, and persist the matched lines into
``persist-receipts-<case>.json`` in the run dir. STRICT regex
``BRIDGE-PERSIST-OK: verified=\d+ top=[0-9a-f]{32}``: the live container
also carries v2-ERA echo receipts (``handles=<hex> provenance=<hex>
source=archived``, from pre-transparent narrations echoed in history)
and the plugin's banner text ``receipt: BRIDGE-PERSIST-OK:
verified=<n> top=<handle>`` (placeholders, not a receipt) — the regex
must match NEITHER (live-verified 2026-10-28: 0 matches on the standby
container, 374 on the run-instance container).

Spec deviation (§8 item 2 assumed receipts extractable from history
windows — falsified live by the transparency change itself) recorded in
GATES-REFERENCE §5. Resolution 6 intact: receipts-only, no facade-log
census, no agent cooperation.

All tests are offline: run_benchmark._run / _docker_logs_since are
monkeypatched module attributes (the established pattern).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import run_benchmark  # noqa: E402


def _patch_logs(monkey_lines_by_container):
    """Patch run_benchmark._docker_logs_since to serve canned logs."""
    calls = []

    def fake(container, since_iso, until_iso):
        calls.append((container, since_iso, until_iso))
        return monkey_lines_by_container.get(container, "")

    run_benchmark._docker_logs_since = fake
    return calls


V4_RECEIPT = ("BRIDGE-PERSIST-OK: verified=2 top=b2842448fa6583e2646daaabfe786729")
V4_RECEIPT_2 = ("2026-10-28 06:31:44 | das-write-plugin | "
                "BRIDGE-PERSIST-OK: verified=1 top=a06f0e0028d04826dfe6382ca8bc5810")
V2_ECHO = ("Bridge status: BRIDGE-PERSIST-OK: verified=1 handles=1d99a6ae3511f38e35f95bf54215c6f3 "
           "provenance=c4695189ef6e1d34397b7b0ddbe67949 source=archived stv=(0.8,0.6)")
BANNER = ('(log INFO "das-write-plugin" "DAS persistent-space bridging enabled: '
          '(add-atom &persistent <expr> <http(s)-url | abs-container-path> [(stv s c)]) '
          'routes to the write-bridge with transparent provenance; receipt: '
          'BRIDGE-PERSIST-OK: verified=<n> top=<handle>")')


def test_regex_matches_v4_receipt():
    assert run_benchmark.PERSIST_RECEIPT_RE.search(V4_RECEIPT)
    assert run_benchmark.PERSIST_RECEIPT_RE.search(V4_RECEIPT_2)


def test_regex_rejects_v2_echo_and_banner():
    # the two live NON-receipt shapes on the current (standby) container:
    # v2-era echo narrations and the plugin banner's placeholder form
    assert not run_benchmark.PERSIST_RECEIPT_RE.search(V2_ECHO)
    assert not run_benchmark.PERSIST_RECEIPT_RE.search(BANNER)


def test_census_uses_agent_container_bounded_window():
    served = None

    def fake_logs(container, since_iso, until_iso):
        nonlocal served
        served = (container, since_iso, until_iso)
        return V4_RECEIPT + "\n" + V2_ECHO + "\n"

    run_benchmark._docker_logs_since = fake_logs
    out = run_benchmark._census_persist_receipts("2026-10-28T06:25:02Z",
                                                 "2026-10-28T07:30:00Z")
    assert served[0] == run_benchmark.CONTAINER_AGENT
    assert served[1] == "2026-10-28T06:25:02Z"
    assert served[2] == "2026-10-28T07:30:00Z"
    assert out["count"] == 1
    assert out["matched"] == [V4_RECEIPT]
    assert out["window"] == ["2026-10-28T06:25:02Z", "2026-10-28T07:30:00Z"]


def test_census_zero_on_receipt_free_logs():
    run_benchmark._docker_logs_since = (lambda c, s, u: BANNER + "\n" + V2_ECHO)
    out = run_benchmark._census_persist_receipts("2026-10-28T06:25:02Z",
                                                 "2026-10-28T07:30:00Z")
    assert out["count"] == 0 and out["matched"] == []


def test_census_docker_error_is_zero_not_crash():
    def boom(container, since_iso, until_iso):
        raise RuntimeError("docker: no such container")

    run_benchmark._docker_logs_since = boom
    out = run_benchmark._census_persist_receipts("a", "b")
    assert out["count"] == 0
    assert out.get("error"), out
