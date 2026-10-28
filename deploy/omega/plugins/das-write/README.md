# das-write plugin — `&persistent` interception hook (v4 transparent provenance)

## Mechanism summary

The stock Omega `metta` skill evaluates MeTTa code strings with PeTTa.
`add-atom &persistent X` reaches stock evaluation as a Prolog-space assert
into a space named `persistent` — durable only for the agent container's
lifetime, never reaching `history.metta` or DAS. This plugin rebinds the
`metta` skill clause so that `(add-atom &persistent <balanced-expression> ...)`
routes the balanced payload expression to the write-bridge facade
(`deploy/das/write-bridge/`, already deployed as a compose service on the
`omega-das-integration-client` network) for a durable, verified DAS write.
The stock clause is removed first and a bridged clause installed in its
place — a second `(= (metta ...) ...)` clause added alongside the stock one
would double-evaluate (both clauses fire on every call), so the
remove-then-add single-definition invariant is load-bearing. Everything
else — every non-`&persistent` expression, every error, every non-str
input — falls through to stock MeTTa evaluation unchanged.

`remove-atom &persistent` is **not bridged** — the plugin returns a
truthful `BRIDGE-PERSIST-REMOVE-UNSUPPORTED` status instead of silently
diverging (a local-only removal would leave DAS unchanged, silently
contradicting the agent's intent).

## Grammar (v3 + v1)

```
(add-atom &persistent <balanced-expression>)                                     ; v1
(add-atom &persistent <balanced-expression> "<http(s)-url>")                    ; v3
(add-atom &persistent <balanced-expression> "<abs-container-path>")             ; v3 (path refs)
(add-atom &persistent <balanced-expression> "<source-ref>" (stv <s> <c>))       ; v3 + truth value
```

- **`<source-ref>`** — the source the fact was derived from: an http(s)
  URL (always allowed), or an absolute container path (allowed only when
  `dasWriteSourceRoots` is configured and `realpath(ref)` resolves inside
  one of its roots). At most 480 chars, no whitespace. The 2048-char cap
  applies to the fact expression only.
- **`(stv <strength> <confidence>)`** — optional PLN truth value, both
  floats in [0,1]; may also appear without a source ref.
- **v2 is retired** — a quoted `git:<sha>` citation token (alone or after
  a URL) is rejected with the actionable status
  `git citations are no longer accepted — pass the source reference; archiving is automatic`.
- **v1 (suffix-less) is unchanged** — a plain, unprovenanced write
  (canaries and dormant prompts keep working; benchmark gates enforce
  refs on graded facts).

## Transparent provenance (the two-POST flow)

The agent passes **only the source reference** — no git commit, no
archive step, no provenance bookkeeping; the mechanics are invisible to
it. On a v3 write the plugin:

1. **resolves the ref** — URL: bounded fetch (20 s timeout,
   2,000,000-character cap, text-only content types); path: a
   filesystem read, only within the configured `dasWriteSourceRoots`;
2. **computes sha256** of the source content itself;
3. **ledger-appends** — `POST /v1/source {"ref", "sha256"}` on the
   facade → the git source ledger (`SOURCE-LEDGER.json`) appends one
   entry and returns the commit (`{commit, deduped, entry_date}`);
   dedup on `(ref, sha256)` returns the original commit, so retries are
   idempotent end-to-end;
4. **gated write** — `POST /v1/write` with
   `{"metta", "verify": true, "provenance": {"ref", "git_commit", "blob_sha256"}}`
   — the facade verifies the ledger citation BEFORE any DAS write, then
   decorates the fact top-link custom attributes.

A per-process cache (ref → `{sha256, commit}`) makes the first write per
source 1 fetch + 2 POSTs and every subsequent write citing the same
source a single `/v1/write` POST.

## Configuration contract

The plugin reads stock **Omega configuration keys** (not raw environment
variables — the stock image entrypoint scrubs the agent environment down
to an allowlist, so custom `docker create` env vars never survive to the
agent process; the stock config machinery is the only launch-time path
that reaches the plugin):

| Key | Meaning | Default | Set via |
|---|---|---|---|
| `dasWriteEnabled` | opt-in gate — value `1` enables the interception path; any other value leaves stock behavior untouched | unset | container command line `dasWriteEnabled=1`, config.yaml overlay, or env `OMEGA_dasWriteEnabled=1` |
| `dasWriteOrigin` | write-bridge facade origin (strict `http://host:port`, no path/query/userinfo) | `http://write-bridge:8080` | container command line, config.yaml overlay, or env `OMEGA_dasWriteOrigin=...` |
| `dasWriteSourceRoots` | optional; comma/whitespace-separated **absolute container-path prefixes** enabling path refs — a path ref is read only when `os.path.realpath(ref)` resolves inside one of the roots | unset (path refs disabled; URL refs only) | container command line, config.yaml overlay, or env `OMEGA_dasWriteSourceRoots=...` |

The Python module (`das_write_bridge.py`) re-checks `dasWriteEnabled` on
every call (defensive double gate — the MeTTa wrapper checks once at
plugin-load time, the Python module checks again at intercept time), so
the hook cannot fire when the gate is off even if the MeTTa clause is
somehow installed. `dasWriteSourceRoots` is re-read on every v3 write.

## Mount contract (agent container)

```
--volume <repo>/deploy/omega/plugins/das-write:/PeTTa/repos/Omega/plugins/das-write:ro
--volume <repo>/deploy/omega/plugins.yaml.overlay:/PeTTa/repos/Omega/config/plugins.yaml:ro
```

- The **plugin dir** is bind-mounted read-only into the stock plugins tree
  — the plugin loader puts the plugin dir on `sys.path` so
  `das_write_bridge.py` is py-callable from `das-write.metta`.
- The **plugins.yaml overlay** is bind-mounted read-only over the stock
  config — it reproduces the stock entries verbatim and appends the
  `das-write` entry. The overlay exists so the stock file is never edited
  in place.

Both mounts are read-only (`:ro`) — the agent never modifies upstream
sources.

## Fall-through guarantee (disabled = zero behavioral change)

When `dasWriteEnabled != 1`:
- `loadOmegaPlugin` logs `"DAS persistent-space bridging disabled"` and
  changes **nothing** — the stock `(= (metta $str) ...)` clause stays in
  place.
- `das_write_bridge.intercept` returns `[]` for every input (defensive
  double gate), so even a stale bridged clause would fall through to
  stock evaluation.

## Status vocabulary (returned as `[status_string]`)

- `BRIDGE-PERSIST-OK: verified=<n> top=<handle> [stv=(s,c)]` — durable,
  verified DAS write; `top=` is the fact's top-link atom handle (copied
  from the facade response `top_handle`), `stv=(s,c)` appears when a
  truth value was supplied
- `BRIDGE-PERSIST-WRITE-FAILED: <reason>` — parse/shape violation, size
  violation, invalid origin, source-resolution failure (`source fetch
  failed (...)`, `fetch timed out`, `unsupported content type ... (text
  only)`, `source content empty`, `source exceeds the 2,000,000
  character limit`, `source unreadable at ...`, `source path outside the
  configured roots (dasWriteSourceRoots)`), ledger append failure
  (`ledger append failed (<facade error>)`), HTTP error (400/502 error
  field), timeout, network error, invalid facade response, or an
  unverified write (missing handles listed)
- `BRIDGE-PERSIST-REMOVE-UNSUPPORTED: remove-atom &persistent is not
  bridged yet; nothing was removed from DAS` — truthful failure

Retired v2 vocabulary: the standalone source-capture skill and its two
receipt statuses are gone (the v2 flow — agent-side archive step, git
citation tokens in the suffix, and the facade's old archive route — is
retired end-to-end); the v3 write subsumes the capture step, and
archiving is automatic.

## Validation record

**Test container (iteration 11, 2026-10-20 ~05:00 UTC):** enabled path
green — `BRIDGE-PERSIST-OK: verified=7` + read-proxy read-back + oracle
cleanup + mongo zero-residue; disabled path zero behavioral change;
stock fall-through intact; suite 58 passed.

**Live agent (iteration 22, 2026-10-20 12:01–12:05 UTC, explicitly approved
restart):** agent `omega-curiosity` started from the updated `start.sh` with
the plugin mounted (`dasWriteEnabled=1`, origin
`http://write-bridge:8080`); loader logged
`DAS persistent-space bridging enabled`. First two autonomous research
findings persisted live, no operator involvement:

- `BRIDGE-PERSIST-OK: verified=7` — `(Inheritance (Concept "FetchCoder-V2")
  (Concept "FetchAI-product"))`
- `BRIDGE-PERSIST-OK: verified=8` — `(Evaluation (Predicate "released-date")
  (Concept "FetchCoder-V2-2026-01-15"))`

Both write-bridge POSTs returned 200 with read-back verification. Mongo
ground truth: handles present, `atom_types` 0, E1/Crow canaries and prior
import markers intact, totals 1864/3710 → 1868/3716 — cumulative growth,
zero residue. Evidence:
`memory/omega-das-bridge/evidence/iter22-live/` (gateway workspace).
These iteration-11/22 records are history of the pre-v3 plugin (receipts
then carried `handles=<first3>`; the capture skill still existed) and are
preserved verbatim.

**Plugin v4 live validation:** PENDING — the live e2e run happens at the
Phase 7 deploy (OVH); this section is updated with run evidence then.
