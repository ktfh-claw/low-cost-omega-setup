# write-bridge tools

Standalone operator-side tools for the write-bridge deployment. They run on
the host (over SSH), never inside the container, and are invoked
independently of the pytest suite.

## `migrate_ledger_repo.sh` — verification-only ledger repo format check

Helper for the issue #2 Phase 3 host migration (decision D6: evidence is
never mutated by scripts). It CHECKS the provenance repo format and never
writes, creates or deletes anything — every git invocation is read-only
(`rev-parse` / `log` / `diff-tree`), every file access is a read. The
migration itself is operator-executed per
`docs/issue-2-ledger-migration-runbook.md`.

### Usage

```bash
# over SSH on the OVH host (root owns the repo dir, hence sudo — the
# helper passes -c safe.directory=<repo> per the run_benchmark.py convention)
sudo bash deploy/das/write-bridge/tools/migrate_ledger_repo.sh --check

# non-default locations (e.g. testing against a copy)
bash deploy/das/write-bridge/tools/migrate_ledger_repo.sh \
  --repo /home/ubuntu/omega-provenance --file SOURCE-LEDGER.json
```

### Checks (in order; first failure exits 1)

1. The repo directory exists and is a git repository.
2. `HEAD` exists and touches ONLY the ledger file — or is the init commit
   (init-commit detection: subject exactly `ledger: init` OR empty tree).
3. The ledger file exists and `json.load` parses it as a JSON list.
4. Every element is a JSON object with EXACTLY the keys
   `ref`/`sha256`/`entry_date` (mirrors `provenance_store._ENTRY_KEYS` and
   the entry shape at `provenance_store.py:8`): `sha256` is 64 lowercase
   hex characters, `entry_date` is a non-empty string.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | all checks passed (final line: `OK: ledger repo format verified: …`) |
| `1` | first failed check (see the `FAIL:` line) |
| `2` | usage error (unknown flag or missing flag value) |

Flags: `--check` (default mode; also the default with no arguments),
`--repo PATH` (default `/home/ubuntu/omega-provenance`),
`--file NAME` (default `SOURCE-LEDGER.json`), `--help`.

### Preflight wiring — Phase 5 (NOT yet wired)

`--check` is the preflight `ledger_repo_format` **source of truth**
(spec §6 test strategy, resolution 5 — it replaces the old
`provenance_repo` check, `run_benchmark.py:391-396`, and becomes a
REQUIRED preflight check). **The harness wiring happens in Phase 5**
(spec §8 item 7b); until then this helper is run manually by the operator
(runbook step 6). Unit tests: `tests/test_migrate_ledger_repo.py`.
