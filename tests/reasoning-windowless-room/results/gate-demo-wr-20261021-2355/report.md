# Windowless Room Gating Test Report — gate-demo-wr-20261021-2355

## GATE FAIL — 0/7 cases passed

| Case | Verdict | Conditions |
|------|---------|------------|
| original | FAIL | Q_MISSING, P_MISSING |
| uncertainty | FAIL | Q_MISSING, P_MISSING |
| unsolvable | FAIL | Q_MISSING, Q_ABSENCE_UNPROVEN |
| true | FAIL | Q_MISSING, P_MISSING |
| false | FAIL | Q_MISSING, P_MISSING |
| easy | FAIL | Q_MISSING, P_MISSING |
| difficult | FAIL | Q_MISSING, P_MISSING |

History window mode: pre-only — das-retrieve calls in window: 0 (placeholder calls: 0)

Condition code reference:

- `A_*` — answer gate (missing / wrong / sky pattern-match / fabricated)
- `Q_*` — query-first gate (no query, no receipt, not in history,
  placeholder arg, degenerate pattern, reissue mismatch, absence unproven)
- `P_*` — provenance gate (citation missing / unresolved vs git repo)
