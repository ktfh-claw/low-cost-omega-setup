# Issue draft 5 — Raw newline inside a quoted string breaks the token

**Target:** singnet/das-metta-parser · **Severity: LOW-MED** · **Type:** bug (lexer) / docs
**Status:** DRAFT — fork-local; filing upstream requires Balázs's explicit go-ahead.

## Defect

The quoted-string token pattern is `["]([^"\n\\]|\\(.|\n))*["]` — a raw newline (unescaped `\n`) inside a quoted string terminates the token match. The string content then leaks out as bare tokens → parse errors or silent mis-tokenization.

## Evidence + validated workaround (2026-10-18)

- On the real Omega campaign `history.metta`: pass rate 98.2% raw → **99.3%** with newline-escaping applied by the caller; the residual 0.7% (61/8,285 entries) are shell-heredoc quirks, not MeTTa semantics.
- Full validated pipeline: segmentation → per-entry syntax gate → newline-escape fallback → db_loader → exit 0, 8,224 entries → 18,699 nodes + 13,680 links (scratch store).

## Proposed fix (small PR or docs)

Either allow raw newlines inside quoted strings in the lexer, or document the escape requirement in the README's atom-mapping spec. Maintainer's choice via issue discussion first.
