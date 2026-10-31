"""v8 prompt contract (v2 re-pin, 2026-10-31): PINNED LEDGER — the
cross-cycle progress channel.

Balázs directive 2026-10-31 11:31 UTC: minimal pseudocode prompt. The
substance of every v8 invariant survives the rewrite; the pinned
wording is updated to the v2 template's ("## Working state" section
carries the ledger + record channels).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

TEMPLATE_PATH = os.path.join(HERE, "..", "agent_prompt_template.md")


def _template() -> str:
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


def _working_state(t: str) -> str:
    return t[t.index("## Working state"):t.index("## Procedure")]


def test_ledger_section_present():
    t = _template()
    assert "LEDGER — exactly one pinned line" in t
    assert "LEDGER: step <1-5> | done: <completed items> | next: <ONE literal tool call>" in t


def test_ledger_first_cycle_seed():
    # the FIRST action of the case is a pin: the ledger with `next:` set
    # to the first add-atom call of step 1
    t = _template()
    seg = _working_state(t)
    assert "First cycle of the case" in seg
    assert "read `{{URL_LIST_PATH}}` ONCE" in seg
    assert "pin the LEDGER with `next:` = the first add-atom call of step 1" in seg


def test_ledger_update_after_every_tool_result():
    t = _template()
    seg = _working_state(t)
    assert "After EVERY tool result, pin the updated line" in seg
    assert "the LAST one is current" in seg


def test_ledger_act_on_next_field():
    # each wake: issue the `next:` call immediately; no re-derivation from
    # files; orientation reads bounded to ONE and only when building a call
    t = _template()
    seg = _working_state(t)
    assert "issue the `next:` call immediately" in seg
    assert "only to look up a recorded handle/expression/URL" in seg
    assert "At most ONE orientation read per cycle" in seg


def test_ledger_terminal_state():
    # completion pins a terminal ledger line and stops
    t = _template()
    assert "next: none — case complete, idle silently" in t


def test_working_memory_names_both_channels():
    # files carry the durable record; the pin carries the cross-cycle
    # working state — and only the pin survives a wake
    t = _template()
    seg = _working_state(t)
    assert "{{FACTS_INDEX_PATH}}" in seg
    assert "pins and files do" in t  # header: results don't survive; pins/files do
    assert "Never redo a recorded result" in seg


def test_anti_loop_rules_point_to_ledger():
    # the unsure-resolution rule rides the working-state section: act on
    # the ledger's next: field, never re-read state already in the prompt
    t = _template()
    seg = _working_state(t)
    assert "Earlier LEDGER lines are stale" in seg
    assert "Never redo a recorded result" in seg


def test_ledger_precedes_pipeline_steps():
    # the working-state contract must be read before the procedure steps
    t = _template()
    assert t.index("## Working state") < t.index("1. EXTRACT")
