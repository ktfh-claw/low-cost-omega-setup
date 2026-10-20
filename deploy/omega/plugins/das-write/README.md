# das-write plugin — `&persistent` interception hook (iteration 11)

## Mechanism summary

The stock Omega `metta` skill evaluates MeTTa code strings with PeTTa.
`add-atom &persistent X` reaches stock evaluation as a Prolog-space assert
into a space named `persistent` — durable only for the agent container's
lifetime, never reaching `history.metta` or DAS. This plugin rebinds the
`metta` skill clause so that `(add-atom &persistent <balanced-expression>)`
routes the balanced payload expression to the write-bridge facade
(`deploy/das/write-bridge/`, already deployed as a compose service on the
`omega-das-integration-client` network) for a durable, verified DAS write.
The stock clause is removed first and a bridged clause installed in its
place — a second `(= (metta ...) ...)` clause added alongside the stock one
would double-evaluate (both clauses fire on every call), so the
remove-then-add single-definition invariant is load-bearing. Everything
else — every non-`&persistent` expression, every error, every non-str
input — falls through to stock MeTTa evaluation unchanged.

`remove-atom &persistent` is **not bridged in v1** — the plugin returns a
truthful `BRIDGE-PERSIST-REMOVE-UNSUPPORTED` status instead of silently
diverging (a local-only removal would leave DAS unchanged, silently
contradicting the agent's intent).

## Configuration contract

The plugin reads two stock **Omega configuration keys** (not raw
tenvironment variables — the stock image entrypoint scrubs the agent
environment down to an allowlist, so custom `docker create` env vars never
survive to the agent process; the stock config machinery is the only
launch-time path that reaches the plugin):

| Key | Meaning | Default | Set via |
|---|---|---|---|
| `dasWriteEnabled` | opt-in gate — value `1` enables the interception path; any other value leaves stock behavior untouched | unset | container command line `dasWriteEnabled=1`, config.yaml overlay, or env `OMEGA_dasWriteEnabled=1` |
| `dasWriteOrigin` | write-bridge facade origin (strict `http://host:port`, no path/query/userinfo) | `http://write-bridge:8080` | container command line, config.yaml overlay, or env `OMEGA_dasWriteOrigin=...` |

The Python module (`das_write_bridge.py`) re-checks `dasWriteEnabled` on
every call (defensive double gate — the MeTTa wrapper checks once at
plugin-load time, the Python module checks again at intercept time), so
the hook cannot fire when the gate is off even if the MeTTa clause is
somehow installed.

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

- `BRIDGE-PERSIST-OK: verified=<n> handles=<first 3 handles comma-joined>`
  — durable, verified DAS write (read-back verification passed)
- `BRIDGE-PERSIST-WRITE-FAILED: <reason>` — parse/shape violation, size
  violation, invalid origin, HTTP error (400/502 error field), timeout,
  network error, or unverified write (missing handles listed)
- `BRIDGE-PERSIST-REMOVE-UNSUPPORTED: remove-atom &persistent is not
  bridged yet; nothing was removed from DAS` — truthful v1 failure

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
