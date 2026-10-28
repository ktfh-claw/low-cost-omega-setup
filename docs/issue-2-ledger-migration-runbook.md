# Issue #2 — Phase 3: Host Ledger Migration Runbook (operator/SSH)

Deliverable of `docs/issue-2-implementation-spec.md` §6 (US4). Companion
helper: `deploy/das/write-bridge/tools/migrate_ledger_repo.sh`
(verification-only; see `deploy/das/write-bridge/tools/README.md`).

## Purpose

Cut the live provenance store over from the v2 offline archive repo to the
fresh single-file `SOURCE-LEDGER.json` git repo (spec §2.2). The ledger repo
is the provenance anchor every DAS atom cites (`provenance_git_commit`);
after the Phase 1 facade rewrite, the citation gate (`LedgerStore.verify_commit`)
can only verify commits that live in the NEW ledger repo — v2-era `archive:`
commits are absent from it. The migration is therefore the cutover moment:
retire the old repo (with full-history backups), init the fresh repo at the
SAME host path (compose/env unchanged, `compose.write-bridge.yaml:67,71`), and
restart the facade against it.

## Scope — operator-executed, NEVER automated

- Executed BY AN OPERATOR over SSH on the OVH host. The migration itself is
  never scripted.
- **D6: evidence is never mutated by scripts.** The only state changes are
  the operator's own commands below. The Phase 3 helper
  (`migrate_ledger_repo.sh`) is VERIFICATION-ONLY (`--check`): it checks and
  reports, never writes/creates/deletes anything.
- Same window as the Phase 2 plugin redeploy (step 7): between the repo
  migration and the plugin redeploy, v2 writes fail loudly at the citation
  gate (actionable 400) — the designed safe state.
- Nothing is deleted at any step: the legacy repo is retired to a sibling
  path, the backups are permanent, and ledger smoke entries are permanent
  evidence.

## Placeholders

| Placeholder | Meaning | Example / expansion |
|---|---|---|
| `<date>` | UTC date stamp | `$(date -u +%Y%m%d)` |
| `<repo>` | host checkout of this repository | `/home/ubuntu/low-cost-omega-setup` |
| `<64hex>` | any 64-lowercase-hex string (the facade validates shape only) | see step 6 |

## Migration procedure — spec §6 steps 1-7 (verbatim)

1. Preconditions: facade container healthy; note current repo state `sudo git -C /home/ubuntu/omega-provenance log --oneline | head`; confirm no benchmark run in flight.
2. Backup: `sudo git -C /home/ubuntu/omega-provenance bundle create /home/ubuntu/omega-provenance.legacy-<date>.bundle --all` (full history incl. blobs) + `sudo tar czf /home/ubuntu/omega-provenance.legacy-<date>.tar.gz -C /home/ubuntu omega-provenance` (working tree, belt-and-braces); verify: `git bundle verify`, tar listing; record both paths (the legacy paths feed `--legacy-repo`).
3. Retire: `sudo mv /home/ubuntu/omega-provenance /home/ubuntu/omega-provenance.legacy-<date>` (keep readable at the known path for legacy resolution; alternatively restore from the bundle at a sibling dir).
4. Fresh init (SAME host path — compose/env unchanged, `compose.write-bridge.yaml:67,71`):

   ```
   sudo mkdir -p /home/ubuntu/omega-provenance && sudo chown -R 65532:65532 /home/ubuntu/omega-provenance
   # as the container user or with matching ownership, create SOURCE-LEDGER.json containing:
   # [
   # ]
   sudo git -C /home/ubuntu/omega-provenance init && … initial commit "ledger: init" (identity: omega-write-bridge <write-bridge@omega.local>)
   ```

   (Container git runs as user 65532 — the per-invocation `-c` identity config convention, `provenance_store.py:14,46-47`, is preserved in `LedgerStore`.)
5. Restart the facade: `sudo docker compose -f deploy/das/write-bridge/compose.write-bridge.yaml up -d` (picks up the new code + repo; `ensure_repo()` is idempotent).
6. Verify: preflight's `provenance_repo` check (`run_benchmark.py:391-396`) passes; manual smoke: `POST /v1/source {"ref": "https://example.com/smoke", "sha256": "<64hex>"}` → 200 + commit; `git -C … show --stat` → exactly one SOURCE-LEDGER.json line added; delete nothing (ledger smoke entries are permanent evidence — use a clearly-labeled ref).
7. Sequencing rule: the plugin redeploy (Phase 2 rollout via the normal `start.sh` `:ro` mount path) happens in the SAME window as this migration — between the two, v2 writes fail loudly at the gate (actionable 400), which is the designed safe state.

## Exact commands (expanded, with placeholders)

Set once per session:

```bash
DATE=$(date -u +%Y%m%d)          # feeds every legacy-<date> path below
```

### Step 1 — preconditions

```bash
sudo docker compose -f <repo>/deploy/das/write-bridge/compose.write-bridge.yaml ps
# facade (write-bridge) must show healthy/running

sudo git -C /home/ubuntu/omega-provenance -c safe.directory=/home/ubuntu/omega-provenance \
  log --oneline | head
# RECORD this output (the pre-migration repo state)

pgrep -af run_benchmark.py || echo "no benchmark run in flight"
# confirm no harness run is in flight before touching the repo
```

### Step 2 — backups, with verification

```bash
sudo git -C /home/ubuntu/omega-provenance bundle create \
  /home/ubuntu/omega-provenance.legacy-${DATE}.bundle --all

# verify the bundle (needs a repo context — run it while the repo is still
# at the known path):
sudo git -C /home/ubuntu/omega-provenance bundle verify \
  /home/ubuntu/omega-provenance.legacy-${DATE}.bundle
# RECORD the output (refs + "is okay")

sudo tar czf /home/ubuntu/omega-provenance.legacy-${DATE}.tar.gz \
  -C /home/ubuntu omega-provenance
sudo tar tzf /home/ubuntu/omega-provenance.legacy-${DATE}.tar.gz | head
# RECORD the listing head (working-tree belt-and-braces copy)

ls -l /home/ubuntu/omega-provenance.legacy-${DATE}.bundle \
      /home/ubuntu/omega-provenance.legacy-${DATE}.tar.gz
# RECORD both paths — they feed --legacy-repo (legacy resolution, spec §2.4)
```

### Step 3 — retire the old repo

```bash
sudo mv /home/ubuntu/omega-provenance /home/ubuntu/omega-provenance.legacy-${DATE}
ls -ld /home/ubuntu/omega-provenance.legacy-${DATE}
# RECORD the retired path (readable at the known sibling path for legacy
# resolution; the bundle at the sibling .bundle path is the alternative
# restore source)
```

### Step 4 — fresh init at the SAME host path

```bash
sudo mkdir -p /home/ubuntu/omega-provenance
sudo chown -R 65532:65532 /home/ubuntu/omega-provenance

# create the empty-array ledger (exactly the two lines "[\n" and "]\n"):
printf '[\n]\n' | sudo tee /home/ubuntu/omega-provenance/SOURCE-LEDGER.json >/dev/null

sudo git -C /home/ubuntu/omega-provenance init
sudo git -C /home/ubuntu/omega-provenance add SOURCE-LEDGER.json
sudo git -C /home/ubuntu/omega-provenance \
  -c user.name='omega-write-bridge' \
  -c user.email='write-bridge@omega.local' \
  -c commit.gpgsign=false \
  commit -m 'ledger: init'

# the git steps above ran as root: hand the WHOLE repo to the container
# user 65532 so the facade can commit (compose.write-bridge.yaml:69-70):
sudo chown -R 65532:65532 /home/ubuntu/omega-provenance

# verify the fresh repo (run as root → -c safe.directory, the
# run_benchmark.py:391-396 convention):
sudo cat /home/ubuntu/omega-provenance/SOURCE-LEDGER.json
# expect exactly:
# [
# ]
sudo git -C /home/ubuntu/omega-provenance -c safe.directory=/home/ubuntu/omega-provenance \
  log --oneline
# expect exactly ONE commit: <sha> ledger: init
sudo git -C /home/ubuntu/omega-provenance -c safe.directory=/home/ubuntu/omega-provenance \
  log -1 --format='%an <%ae>'
# expect: omega-write-bridge <write-bridge@omega.local>
ls -ld /home/ubuntu/omega-provenance /home/ubuntu/omega-provenance/.git \
       /home/ubuntu/omega-provenance/SOURCE-LEDGER.json
# expect owner 65532:65532 on all three
```

Note: the equivalent alternative is to run the git steps as the container
user (`sudo -u '#65532' git …`) — "as the container user or with matching
ownership" per the spec step; the root + final `chown -R` form above achieves
matching ownership and is easier to copy-paste.

### Step 5 — restart the facade

```bash
cd <repo>
sudo docker compose -f deploy/das/write-bridge/compose.write-bridge.yaml up -d
# if the running image predates the Phase 1 code, rebuild it in the same
# command (up -d --build; build arg PYTHON_IMAGE_DIGEST per
# deploy/das/write-bridge/.env.example) — "picks up the new code + repo"

sudo docker compose -f deploy/das/write-bridge/compose.write-bridge.yaml ps
# RECORD the facade status (healthy)
sudo docker compose -f deploy/das/write-bridge/compose.write-bridge.yaml logs --tail 20
# no ledger/repo errors; ensure_repo() is idempotent — it must NOT create a
# second init commit (the repo from step 4 is already valid)
```

### Step 6 — verify

```bash
# 6a. ledger repo format — the verification-only helper (checks, never
# mutates; the preflight ledger_repo_format source of truth, resolution 5):
sudo bash <repo>/deploy/das/write-bridge/tools/migrate_ledger_repo.sh --check
# RECORD the output: four PASS lines +
# "OK: ledger repo format verified: /home/ubuntu/omega-provenance (SOURCE-LEDGER.json)"

# 6b. harness preflight (the provenance_repo check, run_benchmark.py:391-396;
# the helper above is its Phase 5 successor as ledger_repo_format):
cd <repo>/tests/reasoning-windowless-room
sudo python3 run_benchmark.py preflight
# RECORD: preflight exit 0, provenance_repo: ok

# 6c. manual smoke — clearly-labeled PERMANENT ref (delete nothing; ledger
# smoke entries are permanent evidence):
WB_IP=$(sudo docker inspect -f \
  '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
  omega-das-write-bridge-write-bridge-1)
SMOKE_SHA=$(python3 -c "import hashlib; print(hashlib.sha256(b'issue-2 phase-3 migration smoke').hexdigest())")
curl -sS -X POST "http://${WB_IP}:8080/v1/source" \
  -H 'Content-Type: application/json' \
  -d "{\"ref\": \"https://example.com/smoke-issue2-phase3-${DATE}\", \"sha256\": \"${SMOKE_SHA}\"}"
# expect: {"commit": "<40hex>", "deduped": false, "entry_date": "<ISO-8601 UTC>"}
# RECORD the full response JSON

sudo git -C /home/ubuntu/omega-provenance -c safe.directory=/home/ubuntu/omega-provenance \
  show --stat HEAD
# expect: exactly one SOURCE-LEDGER.json line added (the smoke entry commit)
# DELETE NOTHING — the smoke entry is permanent evidence
```

### Step 7 — sequencing (same window as the plugin redeploy)

```bash
# Phase 2 rollout: redeploy the agent plugin overlay via the normal
# start.sh :ro mount path (deploy/omega/start.sh), in the SAME SSH window
# as this migration, right after step 6:
cd <repo>/deploy/omega && sudo bash start.sh
```

Between the repo migration (step 4/5) and the plugin redeploy, v2-shaped
writes (`"git:<40hex>"` citations) fail loudly at the citation gate with the
actionable 400 error (`provenance git_commit … not found in the ledger —
write the source first via the skill, then retry`) — the designed safe
state. Close the window by completing the plugin redeploy.

## Verification evidence to record

Record everything under `tests/reasoning-windowless-room/results/<run-id>/`
(or the migration note that accompanies it):

- [ ] Step 1: pre-migration repo state (`git log --oneline | head` output) + facade health + no-run-in-flight confirmation
- [ ] Step 2: `git bundle verify` output; tar listing head; both backup paths (`/home/ubuntu/omega-provenance.legacy-<date>.bundle`, `/home/ubuntu/omega-provenance.legacy-<date>.tar.gz`)
- [ ] Step 3: retired repo path `/home/ubuntu/omega-provenance.legacy-<date>` (the `--legacy-repo` fallback path)
- [ ] Step 4: fresh repo `log --oneline` (exactly one commit `ledger: init`), init commit identity (`omega-write-bridge <write-bridge@omega.local>`), `SOURCE-LEDGER.json` content (`[` / `]`), ownership listing (65532:65532)
- [ ] Step 5: facade compose `ps` status after restart; log tail (no repo errors, no second init commit)
- [ ] Step 6: helper `--check` output (four PASS + OK); preflight output (`provenance_repo: ok`); the smoke POST response JSON; `git show --stat HEAD` output; the clearly-labeled smoke ref used
- [ ] Step 7: plugin redeploy confirmation (start.sh run) — window closed

## Acceptance criteria (mirrors spec §6)

- [ ] Runbook committed (this document, on the `issue-2-transparent-provenance` branch)
- [ ] Fresh repo has exactly one init commit and a valid empty-array ledger (`[\n]`)
- [ ] Facade healthy after the restart
- [ ] Legacy bundle verified (`git bundle verify` output recorded)
- [ ] `--legacy-repo` paths recorded (retired dir + bundle path)
- [ ] Test strategy: the verification helper `--check` passes on the migrated repo (repo exists; HEAD touches only `SOURCE-LEDGER.json` or is the init commit; `json.load` of the ledger is a list; every element has exactly the 3 keys) — it becomes the REQUIRED preflight `ledger_repo_format` check (resolution 5, replacing `provenance_repo`); harness wiring lands in Phase 5
