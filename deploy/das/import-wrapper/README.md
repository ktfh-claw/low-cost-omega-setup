# Thin import wrapper (Phase 2)

Segments the Omega history file into structural entries, syntax-gates
each entry with the upstream das-metta-parser `syntax_check` binary,
falls back to in-string newline escaping for entries that fail raw,
and decorates accepted entries with Campaign/Source/Epoch provenance —
producing a `db_loader`-ready load file. Config-only: no upstream
sources are forked or modified; the wrapper is a thin pre-processor
for the stock parser.

## Pipeline

```text
history.metta
  -> segment (structural entries; prose lines counted + skipped)
  -> syntax gate (upstream syntax_check binary; exit code ONLY)
  -> escape fallback (raw \n inside double-quoted strings -> two-char \n)
  -> flag (bare < / > outside strings: silently dropped by the lexer)
  -> skip (entries failing both raw and escaped; recorded in the report)
  -> provenance decoration (Campaign/Source/Epoch atoms)
  -> load file (db_loader-ready)
```

## CLI

```bash
python3 import_wrapper.py --input history.metta --out load.metta \
    --report report.json --campaign omega-das-bridge \
    --source history-v1 --epoch epoch-1 \
    [--syntax-check-bin PATH] [--no-provenance] [--skip-gate]
```

`--campaign`, `--source`, and `--epoch` are the provenance params
(kebab-case ids). `--syntax-check-bin` defaults to env
`DAS_SYNTAX_CHECK_BIN`, then `$DAS_METTA_PARSER_DIR/bin/syntax_check`,
then a bare `syntax_check` on PATH. `--skip-gate` is for tests only: it
emits all entries without gating (still provenance + report). Exit
codes: 0 = all entries passed (raw+escaped), 1 = any skipped, 2 =
invalid input/args.

## Verified parser quirks (all live-verified)

- **Exit code only.** `syntax_check` prints `Syntax check OK`
  UNCONDITIONALLY — the exit code is the ONLY reliable signal.
- **Newline-in-string.** Raw newlines inside double-quoted strings
  break the quoted-string token (lexer token:
  `["]([^"\n\\]|\\(.|\n))*["]`); multi-line strings must be
  newline-escaped (`\n` two-char escape inside strings). Escaping every
  raw newline inside string regions recovers these entries.
- **Bare `<>` outside strings** is silently dropped by the parser
  (acceptable; in-string arrows are safe).

## Binary build

The `syntax_check` binary is built from ktfh-claw/das-metta-parser via
`scripts/build.sh` (see that repo). No binary is bundled here.

## db_loader interface (the load step)

`db_loader` does NOT use a config.json. Its MongoDB interface is
environment variables only:

| Variable | Meaning |
|---|---|
| `DAS_MONGODB_HOSTNAME` | mongo host (scratch-network alias) |
| `DAS_MONGODB_PORT` | mongo port (27017) |
| `DAS_MONGODB_USERNAME` | mongo user |
| `DAS_MONGODB_PASSWORD` | mongo password |

The database name is HARDCODED to `das` (collections: `nodes`, `links`,
`atom_types`, `pattern_index_schema`) — load target isolation means
pointing db_loader at a dedicated mongo instance, not a db name.
`--skip-redis` skips the Redis score step (redis_setup is env-gated
otherwise; not needed for our runs — the write path scores separately).

Documented load command (env values from the operator's environment; no
secrets in the repo):

```bash
docker run --rm --network <scratch-net> \
    -v <dir>:/work \
    -e DAS_MONGODB_HOSTNAME=<mongo-host> \
    -e DAS_MONGODB_PORT=27017 \
    -e DAS_MONGODB_USERNAME=<mongo-user> \
    -e DAS_MONGODB_PASSWORD=<mongo-password> \
    trueagi/das:1.0.0-metta-parser \
    db_loader --skip-redis /work/load.metta
```

## Tests

Unit tests with the gate faked (no binary needed, no network, no
docker): `python -m pytest tests/ -q` from this directory. If a real
`syntax_check` binary is discoverable at test time (env
`DAS_SYNTAX_CHECK_BIN`), 2-3 integration cases additionally run against
it; they skip cleanly otherwise.
