# Spec: Omega uplift to v0.1.23-era upstream — migration of fork deltas and retirement of superseded workarounds

## Context and provenance

Directive (Balázs, 2026-10-31 22:19 UTC): upgrade the Omega agent to the
newer upstream release; enumerate every workaround introduced for observed
Omega issues; review which are fixed upstream; create a migration branch
from the tip of bridge-repo main; port only the workarounds that upstream
has NOT fixed; drop workarounds superseded by upstream code; elementary
commits; smoke-test with the 3-case e2e windowless-room reasoning test
WITHOUT relaxing or semantically changing gates (comparability with the
l1/p2 campaigns is a hard requirement); if implementation completes within
~6h, launch the 10-run comparison campaign in the same format as l1/p2
(same adherence gating, same watchdog, same GDoc structure, exact commit
provenance recorded). 30-minute cron monitor overnight; INVALID runs are
tolerated and fixed rather than treated as data.

Full workaround enumeration with live-verified upstream status:
[`memory/omega-uplift-v0.1.23/workaround-enumeration.md`](../../../../memory/omega-uplift-v0.1.23/workaround-enumeration.md)
(workspace memory, canonical).

## Frozen facts (verified 2026-10-31)

- Deployed image today: `omegaclaw:das-a44739e`, source = ktfh-claw/OmegaClaw-Core
  branch `uplift-v0.1.20-pr358` @ a44739e (origin/main tip).
- Migration source: ktfh-claw/OmegaClaw-Core branch `omega-uplift-v0.1.23`
  @ 577ef63 = merge of upstream main a6bd778 (v0.1.23-era, 112 commits
  ahead of the v0.1.20 base) into the fork lineage; conflicts resolved:
  `src/loop.metta` (union: upstream restructured body incl. collapse-fix
  7ec7d92 + no-tool-calls f7dd6d1 handling, plus fork telegramAutonomousWake
  gate, telegramFollowup tracking, autonomousWake reset), and
  `Autotests/unit/test_llm_budget.py` (upstream side). 186 files compile
  clean; fork invariants verified in-tree.
- Harness baseline for comparability: bridge-repo main tip 80c06c7 — harness
  dir byte-identical to frozen 2ecd1e1 (l1), WITHOUT the rejected p2 prompt.
  The e2e campaign runs on this baseline with NO gate/prompt changes.

## Upstream-fixed vs fork-retained deltas (disposition table)

| Fork delta | Upstream v0.1.23 status | Disposition |
|---|---|---|
| `providers/asione.py` | shipped upstream, byte-identical | drop fork concern; upstream file wins |
| `src/websearch.py` overlay | shipped upstream, byte-identical | **DROP the :ro overlay mount** |
| `das_skills.py` v2 adapter + das-retrieve/das-write skills | not upstream | KEEP (fork core) |
| telegramAutonomousWake + wake-gate + followup (1808b94/dd4e0a1/f38217f) | not upstream | KEEP (ported into merged loop.metta) |
| nginx master-as-root (bd6638a) | not upstream | KEEP |
| ARC lane / OpenRouterFree | already removed at a44739e | stays removed |
| pin skill rebind plugin | upstream pin still a no-op stub (PIN-SUCCESS) | KEEP plugin |
| das-read/metta-grammar remove+re-add registration | upstream add-skill now de-duplicates (2a4b6da) | KEEP pattern (still correct; safer now) |
| chroma memory dir fix | unknown on new image | VERIFY on new image; keep if still needed |

## Requirements

### R1 — Bridge-repo deploy tree on `omega-uplift-v0.1.23` branch
- `deploy/omega/start.sh`: image tag → `omegaclaw:v0.1.23-577ef63`;
  REMOVE the websearch.py overlay mount (upstream identical);
  keep all other mounts, env, networks, hardening identical.
- Launch args unchanged: `commchannel=telegram provider=ASIOne
  model=asi1-ultra embeddingprovider=Local telegramAutonomousWake
  dasWriteEnabled=1 dasWriteOrigin=http://write-bridge:8080
  dasWriteRequireRef=1`.
- Elementary commits, one logical change each.

### R2 — Harness comparability contract (MUST NOT change semantics)
- `tests/reasoning-windowless-room/`: NO gate, judge, prompt-template,
  case, or grading changes. Allowed additions only: preflight checks
  needed by the new image (e.g. image tag / version-file consistency),
  and mechanical driver adjustments ONLY if the container interface
  changed (verify before editing; prefer zero harness edits).
- The 10-run campaign must be directly comparable to l1/p2: same cases
  (original, unsolvable, false), same watchdog, same adherence classifier,
  same GDoc format, commit provenance recorded (agent image commit +
  harness commit + branches).

### R3 — Image build and validation
- Build `omegaclaw:v0.1.23-577ef63` on OVH from the exact pushed commit
  (clone-and-verify provenance pattern from omega-1020-uplift.md).
- Plugin validation in a throwaway container on the new image:
  das-read + metta-grammar drivers (existing `tests/run_driver.sh`
  pattern), pin plugin presence, das-retrieve skill registration,
  ASI:One 200, Telegram polling, chroma/knowledge-init behavior.
- New-image observations (wake cadence, history serialization size,
  tool-call surfaces) recorded as smoke evidence, not fixed silently.

### R4 — Smoke run
- Full e2e `full --cases original,unsolvable,false --timeout-minutes 75`
  on the new image with the UNCHANGED harness (main-tip 80c06c7).
- Smoke verdict classes: PASS/FAIL are agent data (report only);
  harness-error/INVALID = implementation defect → fix implementation
  (not gates) and rerun.
- Gate-by-gate analysis of smoke; verify each removed workaround is
  genuinely superseded (websearch overlay absence causes no regression)
  and each retained workaround still works (pin receipts, das-read
  grammar, write-bridge persistence).

### R5 — Campaign (conditional, time-gated)
- If the implementation (merge + build + deploy + plugin validation)
  completes within ~6h of the 22:19 UTC directive: launch the 10-run
  campaign (l1/p2 driver format, 3 cases per run, 75-min watchdog,
  adherence + layer-split + judge).
- INVALID/harness-error runs: fix implementation, mark INVALID, continue
  (directive explicitly tolerates these; do not force into data).
- Final deliverables: stats GDoc in l1/p2 format + commit provenance
  (agent image = ktfh-claw/OmegaClaw-Core@577ef63 branch
  omega-uplift-v0.1.23; harness = bridge-repo@80c06c7 main tip);
  share to nem841425bal@gmail.com.

### R6 — No upstream filing, no secrets
- All work stays on ktfh-claw forks; nothing goes to upstream repos.
- No credentials in repo files, logs, commits, or GDocs.

## Out of scope
- Any change to the harness gates, judge, prompt template, or case set.
- Omega runtime behavior fixes beyond what the merge carries (the smoke
  and campaign MEASURE the new runtime; they do not patch it).
- Scenario B, das-toolbox lane, upstream issue filing.
