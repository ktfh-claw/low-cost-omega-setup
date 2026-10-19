# Issue draft 4 — `syntax_check` prints "Syntax check OK" even on failure

**Target:** singnet/das-metta-parser · **Severity: LOW-MED** · **Type:** bug (CLI)
**Status:** DRAFT — fork-local; filing upstream requires Balázs's explicit go-ahead.

## Defect

`syntax_check.c:26` prints the OK message unconditionally; only the exit code reflects failure (`yyerror` → exit(1)). Scripts that key on stdout believe failed loads passed.

## Evidence (live-verified 2026-10-18)

Real `history.metta` aborts at line 19 (a prose line), yet still prints "Syntax check OK"; exit code 1 is the only reliable failure signal.

## Proposed fix (small PR)

Print OK only on success; on failure, print the failing line number clearly. Unit test: bad input → non-zero exit + no OK line; good input → OK line.
