# Issue draft 2 — Python client typo `user_metta_as_query_tokens` makes MeTTa-mode queries a silent no-op

**Target:** singnet/das · **Severity: MEDIUM** · **Type:** bug (client)
**Status:** DRAFT — fork-local; filing upstream requires Balázs's explicit go-ahead.

## Defect

The server reads the flag `use_metta_as_query_tokens` (`src/rm/api-server/BaseQueryProxy.cc:25`; `src/rm/api-server/PatternMatchingQueryProcessor.cc:203-207, 287-308`), but the python client sends `user_metta_as_query_tokens` (`3rd_party_slots/python_client/das_peer_client/base.py:63`). The parameter name mismatch is silent: setting the flag from the python client has no effect. MeTTa-syntax queries then fall back to LINK_TEMPLATE token parsing and fail with `Invalid token` (`PatternMatchingQueryProcessor.cc:331`) — a failure that looks like a data problem, not a config one.

## Repro (live-verified 2026-10-18)

Against a running stack with a loaded KB (e.g. `(Inheritance (Concept "x402") $b)` present):

1. Query with MeTTa-mode "enabled" via the python client: `query_engineproxy... pattern=...` with `user_metta_as_query_tokens=True` → **0 answers** (flag silently ignored).
2. Same query with the correctly-spelled parameter `use_metta_as_query_tokens=true` → **4 answers** with correct handle assignments.

## Proposed fix (trivial PR, fork branch ready to draft)

One-line rename in the python client: `user_metta_as_query_tokens` → `use_metta_as_query_tokens`. For backwards compatibility, accept both keys server-side (or translate in the client wrapper). Include a regression note referencing the issue.

## Local impact

Until merged, the bridge's read-proxy client wrapper sends the correctly-spelled parameter (config-level workaround documented in `docs/architecture.md` §2 read path).
