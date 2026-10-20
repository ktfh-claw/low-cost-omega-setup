# Issue draft 5 — Raw newline inside a quoted string breaks the token

**Target:** singnet/das-metta-parser · **Severity: LOW-MED** · **Type:** bug (lexer) / docs
**Status:** DRAFT — re-validated against upstream `19022d2` (2026-10-20); filing upstream requires Balázs's explicit go-ahead.

## Defect

The quoted-string token pattern is `["]([^"\n\\]|\\(.|\n))*["]` (`src/metta.l:56`) — a raw newline (unescaped `\n`) inside a quoted string terminates the token match. The string content then leaks out as bare tokens → parse errors or silent mis-tokenization.

Re-validation 2026-10-20 (source review at `19022d2`): pattern byte-for-byte unchanged. Campaign evidence updated by the Phase-2 wrapper (iters 9–10): real `history.metta` gate run — 8,285 entries, 8,216 emitted (**99.17%**, meets ≥99% target), 69 skipped of which the newline/shell-quirk residual is 50 known shell-heredoc quirks (incl. lines 1243/3404); the shipped newline-escape fallback is what carries the pipeline past this lexer defect. Confirmed unchanged.

## Evidence + validated workaround (2026-10-18)

- On the real Omega campaign `history.metta`: pass rate 98.2% raw → **99.3%** with newline-escaping applied by the caller; the residual 0.7% (61/8,285 entries) are shell-heredoc quirks, not MeTTa semantics.
- Full validated pipeline: segmentation → per-entry syntax gate → newline-escape fallback → db_loader → exit 0, 8,224 entries → 18,699 nodes + 13,680 links (scratch store).

## Proposed fix (small PR or docs)

Either allow raw newlines inside quoted strings in the lexer, or document the escape requirement in the README's atom-mapping spec. Maintainer's choice via issue discussion first.
