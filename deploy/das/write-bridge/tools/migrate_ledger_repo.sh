#!/usr/bin/env bash
set -euo pipefail

DEFAULT_REPO="/home/ubuntu/omega-provenance"
DEFAULT_FILE="SOURCE-LEDGER.json"

REPO="$DEFAULT_REPO"
LEDGER_FILE="$DEFAULT_FILE"

usage() {
  cat <<'USAGE'
Usage: migrate_ledger_repo.sh [--check] [--repo PATH] [--file NAME] [--help]

Verification-only helper for the issue #2 ledger migration (Phase 3,
docs/issue-2-implementation-spec.md §6, decision D6: evidence is never
mutated by scripts). It CHECKS the host provenance repo format and never
writes, creates or deletes anything.

Checks (run in order; the first failure exits 1):
  1. the repo directory exists and is a git repository
  2. HEAD exists and touches ONLY the ledger file, or is the init commit
     (init-commit detection: subject exactly "ledger: init" OR empty tree)
  3. the ledger file exists and python3 json.load parses it as a list
  4. every entry is a JSON object with EXACTLY the keys ref/sha256/entry_date
     (sha256: 64 lowercase hex characters; entry_date: non-empty string)

Flags:
  --check      run the checks (also the default when no arguments are given)
  --repo PATH  ledger repo directory (default: /home/ubuntu/omega-provenance)
  --file NAME  ledger file name inside the repo (default: SOURCE-LEDGER.json)
  --help       print this usage and exit 0

Exit codes:
  0  all checks passed
  1  a check failed (see the FAIL line)
  2  usage error (unknown flag or missing flag value)

This helper is the preflight ledger_repo_format source of truth
(resolution 5 — replaces the old provenance_repo check). Harness wiring
happens in Phase 5; until then run it manually, e.g. over SSH:
  sudo bash deploy/das/write-bridge/tools/migrate_ledger_repo.sh --check
USAGE
}

fail() {
  printf 'FAIL: %s\n' "$1"
  exit 1
}

pass() {
  printf 'PASS: %s\n' "$1"
}

git_read() {
  git -C "$REPO" -c safe.directory="$REPO" "$@"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --check)
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    --repo)
      if [ $# -lt 2 ]; then
        usage >&2
        exit 2
      fi
      REPO="$2"
      shift 2
      ;;
    --file)
      if [ $# -lt 2 ]; then
        usage >&2
        exit 2
      fi
      LEDGER_FILE="$2"
      shift 2
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

# Check 1: repo dir exists and is a git repo.
if [ ! -d "$REPO" ]; then
  fail "repo directory does not exist: $REPO"
fi
REPO="$(cd "$REPO" && pwd)"
if ! git_read rev-parse --git-dir >/dev/null 2>&1; then
  fail "not a git repository: $REPO"
fi
pass "repo exists and is a git repository ($REPO)"

# Check 2: HEAD exists and touches ONLY the ledger file, or is the init
# commit (subject exactly "ledger: init" OR empty tree allowed).
if ! git_read rev-parse --verify HEAD >/dev/null 2>&1; then
  fail "no HEAD commit in $REPO (empty repository — run the fresh-init step)"
fi
subject="$(git_read log -1 --format=%s)"
if [ "$subject" = "ledger: init" ]; then
  pass "HEAD is the ledger: init commit"
else
  files="$(git_read diff-tree --root --no-commit-id --name-only -r HEAD)"
  if [ -z "$files" ]; then
    pass "HEAD is an empty-tree commit (init allowed)"
  elif [ "$files" = "$LEDGER_FILE" ]; then
    pass "HEAD touches only $LEDGER_FILE"
  else
    fail "HEAD commit touches files other than $LEDGER_FILE: $(printf '%s' "$files" | tr '\n' ' ')"
  fi
fi

# Check 3: the ledger file exists and json.load parses it as a list.
if entry_count="$(python3 -c '
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        data = json.load(handle)
except OSError as exc:
    print("cannot read %s: %s" % (sys.argv[1], exc.strerror or exc))
    sys.exit(1)
except (json.JSONDecodeError, UnicodeDecodeError) as exc:
    print("invalid JSON: %s" % exc)
    sys.exit(1)
if not isinstance(data, list):
    print("top-level JSON value is a %s, not a list" % type(data).__name__)
    sys.exit(1)
print(len(data))
' "$REPO/$LEDGER_FILE" 2>&1)"; then
  pass "$LEDGER_FILE exists and parses as a JSON array ($entry_count entries)"
else
  fail "$LEDGER_FILE must exist and json.load to a list: $entry_count"
fi

# Check 4: every element has EXACTLY the keys ref/sha256/entry_date, with
# sha256 64 lowercase hex and entry_date a non-empty string.
if entry_total="$(python3 -c '
import json, re, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        entries = json.load(handle)
except Exception as exc:
    print("unreadable or invalid JSON: %s" % exc)
    sys.exit(1)
if not isinstance(entries, list):
    print("ledger is not a JSON list")
    sys.exit(1)
expected = {"ref", "sha256", "entry_date"}
sha256_pattern = re.compile(r"^[0-9a-f]{64}$")
for index, entry in enumerate(entries):
    if not isinstance(entry, dict):
        print("entry %d is a %s, not a JSON object" % (index, type(entry).__name__))
        sys.exit(1)
    keys = set(entry)
    if keys != expected:
        missing = ",".join(sorted(expected - keys)) or "-"
        extra = ",".join(sorted(keys - expected)) or "-"
        print("entry %d must have exactly the keys ref/sha256/entry_date (missing: %s; unexpected: %s)" % (index, missing, extra))
        sys.exit(1)
    if not isinstance(entry["sha256"], str) or sha256_pattern.match(entry["sha256"]) is None:
        print("entry %d sha256 is not 64 lowercase hex characters: %r" % (index, entry["sha256"]))
        sys.exit(1)
    if not isinstance(entry["entry_date"], str) or not entry["entry_date"]:
        print("entry %d entry_date must be a non-empty string: %r" % (index, entry["entry_date"]))
        sys.exit(1)
print(len(entries))
' "$REPO/$LEDGER_FILE" 2>&1)"; then
  pass "every entry has exactly the keys ref/sha256/entry_date ($entry_total checked)"
else
  fail "entries must be objects with exactly ref/sha256/entry_date (sha256 64 lowercase hex, entry_date non-empty): $entry_total"
fi

printf 'OK: ledger repo format verified: %s (%s)\n' "$REPO" "$LEDGER_FILE"
