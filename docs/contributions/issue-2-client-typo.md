# Issue draft 2 — Python client typo `user_metta_as_query_tokens` makes MeTTa-mode queries a silent no-op

**Target:** singnet/das · **Severity: MEDIUM** · **Type:** bug (client)
**Status:** DRAFT — re-validated against upstream `48507929` (2026-10-20); **fork branch `fix/python-client-metta-typo` drafted in ktfh-claw/das**; filing upstream requires Balázs's explicit go-ahead.

## Defect

The server reads the flag `use_metta_as_query_tokens` — now at `src/agents/BaseQueryProxy.cc:25` (`string BaseQueryProxy::USE_METTA_AS_QUERY_TOKENS = "use_metta_as_query_tokens";`, path moved from `src/rm/api-server/` in the +66 upstream commits) — but the python client still sends `user_metta_as_query_tokens` (now at `3rd_party_slots/python_client/hyperon_das/service_clients/base.py:63`, also a moved path; the old `3rd_party_slots/python_client/das_peer_client/` tree no longer exists). The parameter name mismatch is silent: setting the flag from the python client has no effect. MeTTa-syntax queries then fall back to LINK_TEMPLATE token parsing and fail with `Invalid token` — a failure that looks like a data problem, not a config one.

Re-validation 2026-10-20 (upstream master `48507929`): grep for the misspelled string finds exactly the one client constant + its `__init__` default (`base.py:63,76`); server-side spellings are all correct. Repo-wide references now also exist in `src/agents/command_router/http_api/HttpCommandProxyFactory.cc:305,316` (JSON-API validation errors mention the correct spelling). Typo live-confirmed unchanged.

## Repro (live-verified 2026-10-18)

Against a running stack with a loaded KB (e.g. `(Inheritance (Concept "x402") $b)` present):

1. Query with MeTTa-mode "enabled" via the python client: `query_engineproxy... pattern=...` with `user_metta_as_query_tokens=True` → **0 answers** (flag silently ignored).
2. Same query with the correctly-spelled parameter `use_metta_as_query_tokens=true` → **4 answers** with correct handle assignments.

## Proposed fix (trivial PR, fork branch ready to draft)

One-line rename in the python client: `user_metta_as_query_tokens` → `use_metta_as_query_tokens`. For backwards compatibility, accept both keys server-side (or translate in the client wrapper). Include a regression note referencing the issue.

## Local impact

Until merged, the bridge's read-proxy client wrapper sends the correctly-spelled parameter (config-level workaround documented in `docs/architecture.md` §2 read path).
