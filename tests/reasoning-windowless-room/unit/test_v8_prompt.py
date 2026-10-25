"""v8 prompt contract: PINNED LEDGER — the cross-cycle progress channel.

2026-10-25 14:48 UTC directive (Balázs: "build the pin ledger as v8 and
restart e2e"). Root cause of the wr3g read-oscillation (memory/windowless-
room-v3/wr3g-20261025-oscillation-rootcause.md): per-wake restarts collapse
prior tool results to `$_` history tuples, so each wake re-derived progress
from file reads alone; the ~6-10 read calls consumed the whole burst budget
and the agent never reached a pipeline action (120/122 shell reads, zero
DAS calls, header-only artifacts). The `pin` tool output is the only tool
result that survives a wake cycle — v8 makes a mechanical LEDGER line the
required cross-cycle working memory and names the next literal call, so
each wake starts from in-prompt state instead of re-deriving it.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

TEMPLATE_PATH = os.path.join(HERE, "..", "agent_prompt_template.md")


def _template() -> str:
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


def test_ledger_section_present():
    t = _template()
    assert "## PINNED LEDGER — required, mechanical" in t
    assert "LEDGER: step <1-5> | done: <completed items> | next: <ONE literal tool call>" in t


def test_ledger_first_cycle_seed():
    # the FIRST action of the case is a pin: the ledger with the literal
    # archive-source call for the first URL — not a file read
    t = _template()
    seg = t[t.index("## PINNED LEDGER"):t.index("1. **EXTRACT")]
    assert "First cycle of this case" in seg
    assert "read `{{URL_LIST_PATH}}` ONCE" in seg
    assert "That pin is your first tool call of the case" in seg


def test_ledger_update_after_every_tool_result():
    t = _template()
    seg = t[t.index("## PINNED LEDGER"):t.index("1. **EXTRACT")]
    assert "After EVERY tool result" in seg
    assert "the LAST LEDGER line is current" in seg


def test_ledger_act_on_next_field():
    # each wake: issue the `next:` call immediately; no re-derivation from
    # files; orientation reads bounded to ONE and only when building a call
    t = _template()
    seg = t[t.index("## PINNED LEDGER"):t.index("1. **EXTRACT")]
    assert "ISSUE the `next:` call immediately" in seg
    assert "Do not re-derive progress from files" in seg
    assert "At most ONE orientation read" in seg
    assert "never as a loop" in seg


def test_ledger_terminal_state():
    # completion pins a terminal ledger line and stops (A2 defect-2 guard
    # carried into the ledger channel)
    t = _template()
    seg = t[t.index("## PINNED LEDGER"):t.index("1. **EXTRACT")]
    assert "next: none — case complete, idle silently" in seg


def test_working_memory_names_both_channels():
    # files carry the durable record; the PIN carries the cross-cycle
    # working state — and only the pin survives a wake
    t = _template()
    seg = t[t.index("**Working memory across wake cycles:**"):t.index("## PINNED LEDGER")]
    assert "{{FACTS_INDEX_PATH}}" in seg
    assert "PINNED LEDGER (`pin` tool)" in seg
    assert "ONLY tool result that survives a wake cycle" in seg


def test_anti_loop_rules_point_to_ledger():
    # the "unsure" rule must resolve via the ledger's next: field, and
    # forbid re-reading state already in the prompt
    t = _template()
    seg = t[t.index("**Campaign rules (anti-loop, hard):**"):t.index("### REQUIRED FORMAT")]
    assert "LAST LEDGER line's `next:` field" in seg
    assert "never re-read state files you already have in your prompt" in seg


def test_truthful_artifacts_pin_rule_updated():
    # the old generic pin-advice line must be replaced by ledger-keeping;
    # LEDGER line must stay the last-pinned item
    t = _template()
    seg = t[t.index("## Write artifacts truthfully"):t.index("## STOP rule")]
    assert "Keep the PINNED LEDGER current after every tool result" in seg
    assert "the LEDGER line must stay the last-pinned" in seg
    assert "`pin` useful facts/receipts (pinned items persist into your following prompts as working memory)" not in seg


def test_ledger_precedes_pipeline_steps():
    # ledger contract must be read before the pipeline steps (it sits between
    # the task-list working-memory preamble and step 1)
    t = _template()
    assert t.index("## PINNED LEDGER") < t.index("1. **EXTRACT")
