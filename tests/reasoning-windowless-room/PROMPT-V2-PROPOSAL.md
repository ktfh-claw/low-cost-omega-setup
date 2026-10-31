# PROMPT V2 PROPOSAL — minimal pseudocode prompt (branch `prompt-v2-minimal-pseudocode`)

Balázs directive 2026-10-31 11:31 UTC: restructure the agent prompt only — no harness/gate changes — into minimal, formal pseudocode with exact tool-call references, then rerun the same 10-run e2e campaign as the single-variable experiment.

## 1. Root-cause rationale

The l1 campaign (10 runs, 30 cases) attributed all instability to the agent execution layer, expressed as stall-idle degeneracy. Forensics (assessment §1–§7) show three recurring behaviors inside stalls:

1. **Uncertainty-driven defensive action** — the agent "does something just in case" (re-pins, re-reads, writes narratives, occasionally fabricates a completion claim). The 6k-word prose template gives many partially-overlapping rules; under long context the model resolves ambiguity by inventing safety actions.
2. **Ledger ambiguity** — when unsure, the agent re-derived progress from files or re-pinned orientation state instead of issuing the ledger's `next:` call.
3. **Language/role drift** (TG anomaly) — exclusively inside degenerate idle loops, never in healthy runs.

Hypothesis: the instruction-following failure is largely prompt-induced (saturation + ambiguity), not a model capability ceiling. A short, unambiguous, procedure-shaped prompt should reduce both stalls and false claims.

## 2. Design — what V2 is

**Form:** a numbered 5-step pipeline in pseudocode style + one ledger protocol + one exact answer-block schema. Imperative, one instruction per line, explicit tool names and literal call shapes. No lessons, no rationale prose, no repetition. The lessons' *substance* survives only as bare rules ("never pin done before the append succeeds", "no second block").

**Size target:** ~450–550 words vs ~2,600 (≈80% reduction). Context share of the system prompt drops accordingly.

**Answer format: unchanged.** The block stays markdown-shaped (`### CASE`, `QUERY:`, `DAS_RETRIEVE_OK` receipt, `FACTS:`, `HANDLES:`, `REASONING:`, `FINAL ANSWER`) because grading.py regexes parse exactly that. Switching to YAML/JSON would require gate changes — that violates "prompt only" and destroys single-variable comparability with the l1a–l1j baseline. Recommended as a separate follow-up branch (gate would parse a schema-validated block, agent gets the schema in-prompt).

**Hard invariants preserved (harness contracts, byte-exact where marked):**
- Terminal pin text `LEDGER: step 5 | done: answer block written | next: none — case complete, idle silently` (delta-1 classifier matches `answer block written`; pin lines must start `LEDGER:`).
- Intermediate close-out pin before append; terminal pin only after append succeeds.
- facts-index line shapes: `expr <expr> top=<handle>`, `query <pattern> count=<n>`, `exec <call> => <output>`, `trace:` (grading.py parses these).
- add-atom v3 form with source-url + `(stv 0.9 0.8)`; success only via `BRIDGE-PERSIST-OK verified= top=`.
- das-retrieve JSON shape; count=0 → reverse probe + one re-persist; max 2 identical queries.
- metta 2-argument `|-`/`|~` chaining; trace = semicolon-separated s-expressions, first step bare QUERY, interpreter stv outputs only.
- FACTS/HANDLES verbatim copy-not-compose pairing.
- STOP rule: no sends, no duplicate blocks, no re-reads after done; `omega_state.md` truthful.
- Placeholders `{{RUN_ID}} {{CASE_ID}} {{QUESTION}} {{ANSWERS_PATH}} {{FACTS_INDEX_PATH}} {{URL_LIST_PATH}}`.

**Removed:** wr3k/wr3p/wr3q/wr3r lesson narratives, motivational/fear framing, repeated restatements of the same rule (V1 states the copy-not-compose rule ~4×), long explanations of *why* the gate exists. Kept as one-line rules where they gate behavior.

## 3. Scope of code change

- `agent_prompt_template.md` — rewritten (the only functional change).
- `unit/test_v17_prompt.py` + other template-pinning tests — updated to pin the V2 contract (these tests assert prompt content; they change with the prompt). **grading.py, run_benchmark.py, gates: untouched.**

## 4. Verification + experiment

1. Unit suite green (379 total expected, prompt tests re-pinned).
2. Deploy branch to OVH host worktree, run the same 10-run campaign (`run_benchmark.py full --run-id p2[a-j]-20261031 --timeout-minutes 120 --stall-minutes 15`, fresh run-ids, same case sequence).
3. Same statistics protocol: VALID/INVALID classification, invalid → RCA, per-case pass rates, failure-class histogram, adherence-clean rate, wall-clock, watchdog cuts — compared side-by-side against l1a–l1j in a second GDoc.
4. Success criteria for the hypothesis: stall rate and false-completion rate drop materially (l1 baseline: 21/30 watchdog cuts, 6 false-completion catches, 23.3% mechanism pass) with zero regression in answer correctness (l1: 0 wrong answers).
