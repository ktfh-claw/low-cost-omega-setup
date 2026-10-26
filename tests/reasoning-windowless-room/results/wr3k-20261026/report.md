# Windowless Room Gating Test Report — wr3k-20261026

## GATE FAIL — 1/2 cases passed

| Case | Verdict | Conditions | Attested | Reconstruction |
|------|---------|------------|----------|----------------|
| original | PASS | Q_ATTESTED_VIA_ACCESS_LOG, E_INGEST_ATTESTED_VIA_FACADE_LOG | QE+access (3 posts) | 3/3 match repo bytes |
| uncertainty | FAIL | Q_ATTESTED_VIA_ACCESS_LOG, E_FACTS_NOT_IN_INDEX | QE+access (4 posts) | 1/1 match repo bytes |

DAS cleanup before run: 17 expressions removed, canaries intact: True

Condition codes: A_* answer, Q_* query-first (Q_ATTESTED_VIA_ACCESS_LOG is informational), E_* extraction, R_* reasoning trace, P_* provenance.