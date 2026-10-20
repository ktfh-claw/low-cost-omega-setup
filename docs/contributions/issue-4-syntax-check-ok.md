# Issue draft 4 — `syntax_check` prints "Syntax check OK" even on failure

**Target:** singnet/das-metta-parser · **Severity: LOW-MED** · **Type:** bug (CLI)
**Status:** DRAFT — re-validated against upstream `19022d2` (2026-10-20); filing upstream requires Balázs's explicit go-ahead.

## Defect

`syntax_check.c:26` prints the OK message unconditionally; only the exit code reflects failure (`yyerror` → exit(1), `src/metta.l:64-67`). Scripts that key on stdout believe failed loads passed.

Re-validation 2026-10-20 (source review at `19022d2`): `start()` is called from the grammar at `src/metta.y:58` on successful `toplevel_list` reduction only — so any input that fails mid-parse never reaches it, yet a file that parses but contains zero toplevels (e.g. only comments/whitespace) also prints OK with nothing checked. Note: the `db_loader` binary links a DIFFERENT `start()` (`src/db_loader.c:911`, empty body, no OK print) — the defect is specific to `syntax_check`. Confirmed unchanged.

## Evidence (live-verified 2026-10-18)

Real `history.metta` aborts at line 19 (a prose line), yet still prints "Syntax check OK"; exit code 1 is the only reliable failure signal.

## Proposed fix (small PR)

Print OK only on success; on failure, print the failing line number clearly. Unit test: bad input → non-zero exit + no OK line; good input → OK line.
