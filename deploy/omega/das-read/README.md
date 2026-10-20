# das-read — patched `das_skills.py` (read-path fix, iteration 29)

Bind-mounted read-only over the image's
`/PeTTa/repos/Omega/src/das_skills.py` in the agent container (see
`deploy/omega/start.sh`). Config-only: the stock image is never edited.

## Why (defect chain, live evidence 2026-10-20 iters 25–28)

The v1 adapter (our Oct-3 read wrapper baked into image
`omegaclaw:das-f38217f`) made the agent's DAS read path unreachable
end-to-end — while the write path worked, so the report mandate
("every statement backed by MeTTa reasoning from DAS") was unsatisfiable:

1. **Request gate forbade `metta`**: v1 accepted *exactly*
   `{"tokens", "max_answers"}` — but the read-proxy's tokens mode only
   accepts the rigid `LINK_TEMPLATE` schema and its **metta mode (the one
   that reliably answers) was forbidden** by the wrapper. The only working
   shape was undiscoverable. Live: 12/12 das-retrieve attempts failed; the
   exactly-compliant `{"tokens": [...], "max_answers": 10}` attempt got
   HTTP 400 at the proxy (15:33:51), 0×200 from the agent ever.
2. **Response gate rejected every success**: v1 demanded exactly
   `{answers, count, truncated}`; the proxy always returns
   `{"mode", "answers", "count", "truncated"}` — so even a 200 would have
   failed parsing.
3. **Error bodies discarded**: proxy 400/502 carry instructive
   `{"error": ...}` bodies; v1 surfaced only the bare code, so the agent
   could not self-correct.

## What v2 changes

- Accepts `{"metta": <expr>, "max_answers"?: n}` (recommended),
  `{"query": <expr>}` (lenient alias for metta), and the original
  `{"tokens": [...], "max_answers"?: n}`. `max_answers` optional
  (default 10).
- Client-side pre-validation with the same guidance the proxy gives
  (parenthesized expression, mandatory `$variable`).
- Accepts the proxy's real success schema (`mode` optional).
- Surfaces proxy error bodies (`DAS_RETRIEVE_FAILED: proxy returned
  HTTP 400: <proxy error>`).
- Timeout 10 s (live metta queries: 1.3–4+ s).

## Working shapes (verified live against the deployed read-proxy)

```json
{"metta": "(Inheritance (Concept \"x402\") $X)", "max_answers": 10}
{"query": "(Evaluation (Predicate \"released-date\") $P $V)"}
```

Structural mode (rigid schema, proxy-validated):

```json
{"tokens": ["LINK_TEMPLATE", "Expression", "2", "VARIABLE", "V1", "NODE", "Symbol", "\"x402\""], "max_answers": 10}
```

## Validation record

- Test container (2026-10-20, iteration 29): metta OK (real handles,
  x402 facts), query alias OK, 0-answer query OK, tokens-malformed →
  instructive proxy error surfaced, ground pattern → instructive
  `$variable` guidance. See `memory/omega-das-bridge/evidence/iter29-fix/`
  (gateway workspace).
- Live agent: restarted with the patched file mounted; first agent-side
  `DAS_RETRIEVE_OK` verified at the proxy layer (agent-IP 200s) —
  recorded in `docs/status.md` iteration 29.
