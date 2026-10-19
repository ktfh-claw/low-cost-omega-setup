# Issue draft 3 — Lexer silently drops `<` and `>` from bare symbols

**Target:** singnet/das-metta-parser · **Severity: MEDIUM** · **Type:** bug (lexer)
**Status:** DRAFT — fork-local; filing upstream requires Balázs's explicit go-ahead.

## Defect

The flex lexer has no explicit rule for bare `<` / `>` characters; the default rule echoes and discards unmatched input. Consequence: `<` and `>` outside quoted strings silently vanish from stored symbols. Example: a bare NAL-style arrow `-->` becomes `--` with no warning. Quoted strings are unaffected.

## Evidence (coder source review + live build, 2026-10-18)

- Parser built from source at `19022d2`; lexer default-rule behavior confirmed by test.
- Real-world check on the Omega campaign `history.metta` (26,556 lines → 8,285 entries): 17 entries contain `-->`, all inside quoted shell strings — safe in our corpus, but any bare-symbol use would be silently corrupted.

## Proposed fix (small PR, fork branch ready to draft)

Either an explicit lexer rule for `<`/`>` in bare symbols, or loud rejection at parse time. Prefer maintainer's choice from the issue discussion before the PR (per the contribution ladder: issue → discussion → PR).

## Test plan

- Unit test in the repo's existing `tests/unit/` shell pattern: bare `-->` symbol either survives intact or produces a clear syntax error — never silent truncation.
