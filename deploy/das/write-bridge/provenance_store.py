"""Git-backed source ledger for the write-bridge facade (provenance v4).

Provenance is metadata-only: source CONTENT is never archived. The ledger
is a single ``SOURCE-LEDGER.json`` file in a local git repository — a JSON
array with one element per line (leading-comma pinned form):

    [
    {"ref": "<url|path>", "sha256": "<64hex>", "entry_date": "<ISO-8601 UTC>"}
    ,{"ref": ...}
    ]

Each new entry is exactly one commit appending exactly one line before the
final ``]`` line; the commit hash is the provenance anchor cited by DAS
atoms. Deduped by ``(ref, sha256)``: recording the same pair returns the
ORIGINAL entry's commit (idempotent, no new commit).

The store is serialized by the facade (ThreadingHTTPServer) through an
flock on ``.ledger.lock`` because git index operations are not
concurrent-safe. Git runs via subprocess with per-invocation ``-c``
identity config (no global config; the container user is 65532).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

LEDGER_NAME = "SOURCE-LEDGER.json"
LOCK_NAME = ".ledger.lock"

MAX_REF_CHARS = 480

GIT_AUTHOR_NAME = "omega-write-bridge"
GIT_AUTHOR_EMAIL = "write-bridge@omega.local"

# Citation gate: a write may only cite a commit created by this ledger.
_GIT_COMMIT_PATTERN = re.compile(r"^git:([0-9a-f]{40})$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_ENTRY_KEYS = {"ref", "sha256", "entry_date"}


class ArchiveError(RuntimeError):
    """The ledger operation failed (validated input or git failure)."""


def _commit_sha_from_citation(git_commit: str) -> str:
    """Extract the 40-hex sha from a ``git:<sha>`` citation."""
    if not isinstance(git_commit, str) or _GIT_COMMIT_PATTERN.match(git_commit) is None:
        raise ArchiveError('provenance git_commit must be "git:" + 40 hex chars')
    return _GIT_COMMIT_PATTERN.match(git_commit).group(1)


class LedgerStore:
    """Append-only git ledger of ``(ref, sha256)`` source entries."""

    def __init__(self, repo_root: str) -> None:
        self.repo_root = os.path.abspath(repo_root)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ init

    def ensure_repo(self) -> None:
        """Create the git repo and empty ledger if missing; idempotent."""
        os.makedirs(self.repo_root, exist_ok=True)
        git_dir = os.path.join(self.repo_root, ".git")
        if not os.path.isdir(git_dir):
            self._git("init", "--quiet")
        ledger_path = os.path.join(self.repo_root, LEDGER_NAME)
        if not os.path.exists(ledger_path):
            with open(ledger_path, "w", encoding="utf-8", newline="") as f:
                f.write("[\n]\n")
            self._git("add", "--", LEDGER_NAME)
            self._git("commit", "--quiet", "-m", "ledger: init")

    # ---------------------------------------------------------------- public

    def record(self, ref: str, sha256: str) -> dict[str, Any]:
        """Append one ledger entry; return ``{commit, deduped, entry_date}``."""
        ref = _validate_ref(ref)
        sha256 = _validate_sha256(sha256)

        with self._lock:
            self.ensure_repo()
            lock_path = os.path.join(self.repo_root, LOCK_NAME)
            with open(lock_path, "a+b") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    existing = self._find_entry(ref, sha256)
                    if existing is not None:
                        element, entry = existing
                        commit = self._original_commit_for(element)
                        return {
                            "commit": commit,
                            "deduped": True,
                            "entry_date": entry["entry_date"],
                        }

                    entry_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    element = json.dumps(
                        {"ref": ref, "sha256": sha256, "entry_date": entry_date},
                        separators=(",", ":"),
                    )
                    self._append_element_line(element)
                    self._git("add", "--", LEDGER_NAME)
                    self._git(
                        "commit", "--quiet", "-m", f"ledger: {sha256[:12]} {ref[:96]}"
                    )
                    commit = self._git(
                        "rev-parse", "HEAD", check=True, capture=True
                    ).strip()
                    return {"commit": commit, "deduped": False, "entry_date": entry_date}
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def verify_commit(self, git_commit: str, ref: str, sha256: str) -> dict[str, Any]:
        """Write-time citation gate (provenance v4).

        The cited commit must exist in the ledger repo, touch only
        ``SOURCE-LEDGER.json``, add exactly one entry-shaped line, and that
        entry's ``(ref, sha256)`` must equal the cited pair — this catches
        hallucinated shas and right-sha-wrong-source swaps. Raises
        :class:`ArchiveError` with an actionable, retryable message on
        failure; returns the cited entry's metadata on success. Serialized
        like ``record()`` (flock) because it reads repo state.
        """
        sha = _commit_sha_from_citation(git_commit)

        with self._lock:
            self.ensure_repo()
            lock_path = os.path.join(self.repo_root, LOCK_NAME)
            with open(lock_path, "a+b") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    resolved = self._git(
                        "rev-parse", "--verify", f"{sha}^{{commit}}", capture=True
                    ).strip()
                    if not resolved:
                        raise ArchiveError(
                            f'provenance git_commit "{git_commit}" not found in the '
                            "ledger — write the source first via the skill, then retry"
                        )
                    names = [
                        line.strip()
                        for line in self._git(
                            "show", "--name-only", "--format=", sha, capture=True
                        ).splitlines()
                        if line.strip()
                    ]
                    if names != [LEDGER_NAME]:
                        raise ArchiveError(
                            f'provenance git_commit "{git_commit}" is not a ledger '
                            f"commit (touching only {LEDGER_NAME})"
                        )
                    diff = self._git(
                        "show", sha, "--", LEDGER_NAME, capture=True
                    )
                    entries = _entry_shaped_lines(diff)
                    if (
                        len(entries) != 1
                        or (entries[0]["ref"], entries[0]["sha256"]) != (ref, sha256)
                    ):
                        raise ArchiveError(
                            f'provenance git_commit "{git_commit}" does not add the '
                            "cited source entry — re-run the skill write, then retry"
                        )
                    entry = entries[0]
                    return {
                        "commit": sha,
                        "ref": entry["ref"],
                        "sha256": entry["sha256"],
                        "entry_date": entry["entry_date"],
                    }
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    # --------------------------------------------------------------- helpers

    def _find_entry(self, ref: str, sha256: str) -> tuple[str, dict[str, Any]] | None:
        """The first ledger element whose ``(ref, sha256)`` matches.

        Returns ``(element line text, parsed entry)`` or ``None``.
        """
        ledger_abs = os.path.join(self.repo_root, LEDGER_NAME)
        with open(ledger_abs, "r", encoding="utf-8") as f:
            for line in f:
                element = _element_text(line)
                if element is None:
                    continue
                try:
                    entry = json.loads(element)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                if entry.get("ref") == ref and entry.get("sha256") == sha256:
                    return element, entry
        return None

    def _original_commit_for(self, element: str) -> str:
        """The OLDEST commit that introduced ``element`` (pickaxe)."""
        result = self._git(
            "log", "--reverse", "--format=%H", f"-S{element}", "--", LEDGER_NAME,
            capture=True,
        )
        lines = [line for line in result.splitlines() if line.strip()]
        if not lines:
            raise ArchiveError(
                "ledger entry exists but no commit adds its line — the repo is "
                "inconsistent; inspect SOURCE-LEDGER.json and the git log"
            )
        return lines[0].strip()

    def _append_element_line(self, element: str) -> None:
        """Insert ``element`` as one line immediately before the final ``]``.

        Pinned form: the FIRST element line starts ``{``, every subsequent
        element line starts ``,{`` (leading commas — each append is a pure
        +1-line diff and the file stays a valid JSON array).
        """
        ledger_abs = os.path.join(self.repo_root, LEDGER_NAME)
        with open(ledger_abs, "r", encoding="utf-8") as f:
            lines = f.readlines()
        last = max(index for index, line in enumerate(lines) if line.strip())
        if lines[last].strip() != "]":
            raise ArchiveError(f"{LEDGER_NAME} is malformed: no closing ] line")
        has_elements = any(
            _element_text(line) is not None for line in lines[:last]
        )
        prefix = "" if not has_elements else ","
        lines.insert(last, prefix + element + "\n")
        with open(ledger_abs, "w", encoding="utf-8", newline="") as f:
            f.write("".join(lines))

    def _git(self, *args: str, check: bool = False, capture: bool = False) -> str:
        cmd = [
            "git",
            "-C",
            self.repo_root,
            "-c",
            f"user.name={GIT_AUTHOR_NAME}",
            "-c",
            f"user.email={GIT_AUTHOR_EMAIL}",
            "-c",
            "commit.gpgsign=false",
            *args,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check and proc.returncode != 0:
            raise ArchiveError(f"git {args[0]} failed: {proc.stderr.strip()[:200]}")
        if capture:
            if proc.returncode != 0:
                if check:
                    raise ArchiveError(f"git {args[0]} failed: {proc.stderr.strip()[:200]}")
                return ""
            return proc.stdout
        if proc.returncode != 0 and check:
            raise ArchiveError(f"git {args[0]} failed: {proc.stderr.strip()[:200]}")
        return proc.stdout


def _element_text(line: str) -> str | None:
    """The comma-stripped element text of one ledger line, else ``None``."""
    text = line.strip()
    if text.startswith(","):
        text = text[1:]
    if not text.startswith("{"):
        return None
    return text


def _entry_shaped_lines(diff: str) -> list[dict[str, Any]]:
    """Entry-shaped objects added by a ``git show`` diff.

    Added lines only (leading ``+``, never the ``+++`` header), one leading
    comma stripped, kept when they parse as JSON objects with the exact
    three-field key set. The ``ledger: init`` commit's ``[``/``]`` lines and
    any non-entry additions are filtered out.
    """
    entries: list[dict[str, Any]] = []
    for line in diff.splitlines():
        if line.startswith("+++") or not line.startswith("+"):
            continue
        element = _element_text(line[1:])
        if element is None:
            continue
        try:
            entry = json.loads(element)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and set(entry) == _ENTRY_KEYS:
            entries.append(entry)
    return entries


def _validate_ref(ref: str) -> str:
    if not isinstance(ref, str) or not ref or len(ref) > MAX_REF_CHARS:
        raise ArchiveError(
            "ref must be a non-empty string of at most 480 characters"
        )
    if any(ch.isspace() for ch in ref):
        raise ArchiveError("ref must not contain whitespace")
    if ref.startswith("/"):
        return ref
    try:
        parsed = urlsplit(ref)
    except ValueError as exc:
        raise ArchiveError("ref must be an http(s) URL or an absolute path") from exc
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ArchiveError("ref must be an http(s) URL or an absolute path")
    return ref


def _validate_sha256(sha256: str) -> str:
    if not isinstance(sha256, str) or _SHA256_PATTERN.match(sha256) is None:
        raise ArchiveError("sha256 must be 64 lowercase hex characters")
    return sha256
