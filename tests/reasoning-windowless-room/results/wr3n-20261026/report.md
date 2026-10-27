# Windowless Room Gating Test Report — wr3n-20261026

## GATE FAIL — 0/3 cases passed

| Case | Verdict | Conditions | Attested | Reconstruction |
|------|---------|------------|----------|----------------|
| original | FAIL | A_MISSING, Q_MISSING, P_MISSING, R_MISSING | - | - |
| unsolvable | FAIL | A_WRONG, Q_ATTESTED_VIA_ACCESS_LOG, Q_ABSENCE_UNPROVEN, E_NO_EXTRACTION, R_NOT_METTA, P_UNRESOLVED:COMMIT_NOT_IN_REPO | QE+access (6 posts) | 0/1 match repo bytes |
| false | FAIL | A_MISSING, Q_MISSING, P_MISSING, R_MISSING | - | - |

DAS cleanup before run: 10 expressions removed, canaries intact: True

Condition codes: A_* answer, Q_* query-first (Q_ATTESTED_VIA_ACCESS_LOG is informational), E_* extraction, R_* reasoning trace, P_* provenance.