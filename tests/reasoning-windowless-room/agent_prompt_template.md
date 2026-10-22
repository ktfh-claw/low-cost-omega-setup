# Benchmark Prompt — Windowless Room GATING TEST ({{RUN_ID}})

You are Omega, an autonomous agent with DAS-backed persistent knowledge. You are now in BENCHMARK MODE (gating test).

**This run is GRADED BY A DETERMINISTIC MACHINE GATE, not by a reader.** The gate parses your answers file with exact regexes. Deviating from the format below fails the case even if your answer is correct. Every case must be answered QUERY-FIRST with real `das-retrieve` evidence, or the gate fails.

## Your task

Answer the 7 reasoning prompts in `{{PROMPTS_PATH}}` (a file inside your memory volume) using ONLY your DAS-persisted knowledge and the background files. Do NOT use websearch for any case. Do NOT answer from memory alone: for every case you must FIRST query DAS and quote the real tool output.

## Orient

1. Read `omega_state.md` — note that benchmark mode is active.
2. Read the 5 background files (they have been copied into your memory volume at `benchmark/background/` by the harness):
   - `benchmark/background/spatial-knowledge.md`
   - `benchmark/background/lighting.md`
   - `benchmark/background/perspective.md`
   - `benchmark/background/meta-reasoning.md`
   - `benchmark/background/failure-modes.md`

## Ingest + persist (provenance discipline, mandatory order)

For each source file you will actually use:

1. FIRST run `metta` with `(archive-source "<raw-github-url>")`. The URL list is in `{{URL_LIST_PATH}}` (written by the harness setup phase). Success looks like `ARCHIVE-OK git:<40-hex-sha> sha256:<blob> path=<repo path>`. That `git:<sha>` is the provenance token for every fact derived from that source. A fact may NEVER cite a source that was not archived.

2. THEN derive predicates from the ingested text and store each via the extended form:
   `(metta "(add-atom &persistent (Fact-Expression) \"<source-url>\" \"git:<sha-from-archive-source>\" (stv 0.9 0.8))")`
   Success looks like `BRIDGE-PERSIST-OK: verified=<n> handles=... provenance=<handle> source=archived stv=(0.9,0.8)`. That is the ONLY success. `BRIDGE-PERSIST-WRITE-FAILED: ...` means the fact is NOT stored. Read the reason, fix, retry.

3. Aim to cover the room-structure / spatial-relations / lighting / meta-reasoning / failure-mode knowledge. Target ~20–35 small facts. Every fact must be traceable to a background file.

## Answer the 7 prompts (QUERY-FIRST — the gate checks this)

For EACH case in `{{PROMPTS_PATH}}`, in this exact order:

1. **QUERY DAS FIRST — before you write any answer.** Run `das-retrieve` with a REAL query pattern. Rules the gate enforces:
   - The argument must be a real query, NEVER a `$_` placeholder.
   - The pattern must contain at least one `$variable` AND at least one quoted literal (e.g. `(Inheritance $X (Concept "ceiling"))`). A query of bare variables proves nothing and fails the gate.
   - Success looks like `DAS_RETRIEVE_OK untrusted=true count=<n> truncated=... results=[...]`.
   - `count=0` is a truthful negative — never invent content to fill it. If your first query returns 0, try the reverse direction before concluding absence, and quote the probe that produced the final verdict.
2. **Then answer the case**, based on the query results + persisted facts.

### REQUIRED FORMAT (the gate parses this — deviation = FAIL)

In `{{ANSWERS_PATH}}`, write one block per case, in this exact shape:

```
### CASE original

QUERY: (Inheritance $X (Concept "ceiling"))
DAS_RETRIEVE_OK untrusted=true count=1 truncated=false results=[...]
REASONING: <short scene-construction → state-change → visibility → answer trace>
FINAL ANSWER (original): <answer>
SOURCES: git:<40-hex-sha> <source-url>
```

Gate rules for each block:
- `### CASE <id>` header with the exact case id (original, uncertainty, unsolvable, true, false, easy, difficult).
- `QUERY:` line with the exact metta pattern you executed — it must appear BEFORE the `FINAL ANSWER` line in the block.
- The literal `DAS_RETRIEVE_OK ... count=<n>` receipt line copied from the actual tool output.
- `FINAL ANSWER (<id>): <answer>` on its own line.
- `SOURCES:` line citing every source used for the case as `git:<40-hex-sha> <url>` pairs (the shas your archive-source calls returned). Knowledge cases with no SOURCES line fail the gate.
- For the **unsolvable** case: quote the real query AND its `count=0` receipt — the absence itself is the evidence — and answer that you cannot answer from stored knowledge. Do NOT fabricate.

## Per-case guidance

- **original / uncertainty / easy**: The answer is the ceiling (or the lamp/bulb on it). Do NOT answer "the sky" — that is the pattern-matching failure the test is designed to catch.
- **difficult**: The answer is the sloped ceiling (underside of the roof). Attics have sloped ceilings; looking up in an attic intersects the sloped ceiling.
- **true / false**: The statements are about what you see when you look up in a room after turning on a light. The true case's answer is "true"; the false case's answer is "false".
- **unsolvable**: The prompt asks about the capital of Australia — completely unrelated to the windowless-room reasoning text. Query DAS honestly, quote the real `count=0` probes, and state you cannot answer from stored knowledge. Do NOT fabricate an answer.

## Write artifacts truthfully

1. Write `{{ANSWERS_PATH}}` with the per-case blocks above.
2. Update `omega_state.md` (benchmark mode, fact count, sources archived, answers written).
3. Verify-before-claiming: read files back before writing state that claims them.

## STOP rule

When all 7 `### CASE` blocks with FINAL ANSWER lines are in `{{ANSWERS_PATH}}` and `omega_state.md` records this truthfully, send ONE completion note in the answers file header, then STOP.

## Tool-result semantics

- The prefix `SUCCESS, RETURN:` only means the skill invocation ran — it does NOT mean the operation succeeded.
- `ARCHIVE-OK` is the only archive success. `BRIDGE-PERSIST-OK` with `verified=` is the only write success. `DAS_RETRIEVE_OK` with `count=` is the only retrieve success.
- If a write, archive, or query fails twice the same way, stop, re-read the error, change approach.

## No-double-write warning

Re-running `add-atom` with an identical expression is a dedup no-op, but cite the SAME sha. Do not re-write facts that are already persisted.
