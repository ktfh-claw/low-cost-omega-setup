"""Git-backed source archive for the write-bridge facade (provenance v2).

Implements the final missing provenance layer: URL content fetched at
research time is committed into a LOCAL git repository on the host, and
the returned commit hash is what DAS atoms refer to. Content-addressed
blobs under ``sources/<yyyy>/<mm>/<sha256>.<ext>`` plus an append-only
``index.jsonl``; one commit per archived source. Deduped by
``(url, blob sha256)``: re-archiving the same content from the same URL
returns the ORIGINAL commit (idempotent, no new commit).

The store is serialized by the facade (ThreadingHTTPServer) through an
flock on ``.archive.lock`` because git index operations are not
concurrent-safe. Git runs via subprocess with per-invocation ``-c``
identity config (no global config; the container user is 65532).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any

INDEX_NAME = "index.jsonl"
LOCK_NAME = ".archive.lock"

MAX_URL_CHARS = 2048
MAX_CONTENT_TYPE_CHARS = 128
MAX_FETCHED_AT_CHARS = 64

CONTENT_TYPE_EXT = {
    "application/json": "json",
    "application/xml": "xml",
    "text/html": "html",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/xml": "xml",
}
DEFAULT_EXT = "txt"

GIT_AUTHOR_NAME = "omega-write-bridge"
GIT_AUTHOR_EMAIL = "write-bridge@omega.local"

# Provenance citation gate (v2.1, Options A+B): a write may only cite a
# commit that this store itself created for exactly the cited URL.
_GIT_COMMIT_PATTERN = re.compile(r"^git:([0-9a-f]{40})$")
_ARCHIVE_SUBJECT_PREFIX = "archive: "
_RECOMMIT_SUFFIX = " (re-commit)"


class ArchiveError(RuntimeError):
    """The archive operation failed (validated input or git failure)."""


def parse_archive_subject(subject: str) -> tuple[str, str] | None:
    """Parse an archive commit subject into ``(url, blob12)``.

    Subjects are ``archive: <url> <blob12>`` (or the same with a trailing
    ``(re-commit)`` marker). Returns ``None`` when malformed. The URL never
    contains whitespace (validated at archive time), so the final
    whitespace-separated token is always the 12-hex blob prefix.
    """
    if not isinstance(subject, str) or not subject.startswith(_ARCHIVE_SUBJECT_PREFIX):
        return None
    body = subject[len(_ARCHIVE_SUBJECT_PREFIX):]
    if body.endswith(_RECOMMIT_SUFFIX):
        body = body[: -len(_RECOMMIT_SUFFIX)]
    url, sep, blob = body.rpartition(" ")
    if not sep or not url or not blob:
        return None
    return url, blob


def _commit_sha_from_citation(git_commit: str) -> str:
    """Extract the 40-hex sha from a ``git:<sha>`` citation."""
    if not isinstance(git_commit, str) or _GIT_COMMIT_PATTERN.match(git_commit) is None:
        raise ArchiveError('provenance git_commit must be "git:" + 40 hex chars')
    return _GIT_COMMIT_PATTERN.match(git_commit).group(1)


class ProvenanceStore:
    """Content-addressed, git-committed archive of fetched source content."""

    def __init__(self, repo_root: str) -> None:
        self.repo_root = os.path.abspath(repo_root)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ init

    def ensure_repo(self) -> None:
        """Create the git repo if missing; idempotent."""
        os.makedirs(self.repo_root, exist_ok=True)
        git_dir = os.path.join(self.repo_root, ".git")
        if not os.path.isdir(git_dir):
            self._git("init", "--quiet")
        index_path = os.path.join(self.repo_root, INDEX_NAME)
        if not os.path.exists(index_path):
            with open(index_path, "a", encoding="utf-8"):
                pass

    # ---------------------------------------------------------------- public

    def archive(
        self,
        url: str,
        content: str,
        content_type: str | None = None,
        fetched_at: str | None = None,
    ) -> dict[str, Any]:
        """Archive ``content`` fetched from ``url``; return commit metadata."""
        url = _validate_url(url)
        if not isinstance(content, str) or not content:
            raise ArchiveError("content must be a non-empty string")
        if content_type is not None and (
            not isinstance(content_type, str)
            or not content_type
            or len(content_type) > MAX_CONTENT_TYPE_CHARS
            or content_type.strip() != content_type
        ):
            raise ArchiveError("content_type must be a short trimmed string")
        if fetched_at is not None and (
            not isinstance(fetched_at, str)
            or not fetched_at
            or len(fetched_at) > MAX_FETCHED_AT_CHARS
        ):
            raise ArchiveError("fetched_at must be a short string")

        blob_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        ext = CONTENT_TYPE_EXT.get((content_type or "").split(";")[0].strip().lower(), DEFAULT_EXT)
        now = datetime.now(timezone.utc)
        path = os.path.join(
            "sources", f"{now.year:04d}", f"{now.month:02d}", f"{blob_sha}.{ext}"
        )
        archived_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._lock:
            self.ensure_repo()
            lock_path = os.path.join(self.repo_root, LOCK_NAME)
            with open(lock_path, "a+b") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    existing = self._find_index_entry(url, blob_sha)
                    if existing is not None:
                        commit = self._commit_for_path(existing["path"])
                        if commit is None:
                            # Index line exists but the blob commit is gone
                            # (repo tampered/restored); re-commit the line.
                            commit = self._commit_files(
                                [os.path.join(self.repo_root, existing["path"])],
                                f"archive: {url} {blob_sha[:12]} (re-commit)",
                            )
                        return {
                            "commit": commit,
                            "blob_sha256": blob_sha,
                            "path": existing["path"],
                            "deduped": True,
                            "archived_at": existing["archived_at"],
                        }

                    blob_abs = os.path.join(self.repo_root, path)
                    os.makedirs(os.path.dirname(blob_abs), exist_ok=True)
                    with open(blob_abs, "w", encoding="utf-8", newline="") as f:
                        f.write(content)

                    entry = {
                        "url": url,
                        "blob_sha256": blob_sha,
                        "path": path,
                        "content_type": content_type or DEFAULT_EXT,
                        "fetched_at": fetched_at,
                        "archived_at": archived_at,
                    }
                    index_abs = os.path.join(self.repo_root, INDEX_NAME)
                    with open(index_abs, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")

                    commit = self._commit_files(
                        [blob_abs, index_abs], f"archive: {url} {blob_sha[:12]}"
                    )
                    if commit is None:
                        # Nothing changed (same url+content already committed
                        # but the index line was pruned): return existing.
                        commit = self._commit_for_path(path)
                        if commit is None:
                            raise ArchiveError("git commit produced no commit")
                    return {
                        "commit": commit,
                        "blob_sha256": blob_sha,
                        "path": path,
                        "deduped": False,
                        "archived_at": archived_at,
                    }
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def lookup(self, blob_sha: str) -> dict[str, Any] | None:
        """Return the newest index entry whose blob sha starts with ``blob_sha``."""
        with self._lock:
            self.ensure_repo()
            existing = self._find_index_entry(None, blob_sha)
            if existing is None:
                return None
            result = dict(existing)
            result["commit"] = self._commit_for_path(existing["path"])
            return result

    def verify_commit(self, git_commit: str, url: str) -> dict[str, Any]:
        """Write-time citation gate (provenance v2.1, Options A+B).

        (A) The cited commit must exist in the archive repo, and (B) its
        subject must cite exactly ``url`` — this catches both hallucinated
        shas and right-sha-wrong-source swaps. Raises :class:`ArchiveError`
        with an actionable, retryable message on failure; returns the
        archived entry metadata on success. Serialized like ``archive()``
        (flock) because it reads repo state.
        """
        sha = _commit_sha_from_citation(git_commit)
        if not isinstance(url, str) or not url:
            raise ArchiveError("provenance url is required to verify the cited commit")

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
                            f'provenance git commit "{git_commit}" not found in the '
                            f'archive — run (archive-source "{url}") and use the sha '
                            "from its ARCHIVE-OK return, then retry"
                        )
                    subject = self._git(
                        "show", "-s", "--format=%s", sha, capture=True
                    ).strip()
                    parsed = parse_archive_subject(subject)
                    if parsed is None:
                        raise ArchiveError(
                            f'provenance git commit "{git_commit}" exists but is not '
                            f'an archive commit — run (archive-source "{url}") and use '
                            "the sha from its ARCHIVE-OK return, then retry"
                        )
                    archived_url, _blob12 = parsed
                    if archived_url != url:
                        raise ArchiveError(
                            f'provenance git commit "{git_commit}" archives a different '
                            f'source: "{archived_url}", not "{url}" — run '
                            f'(archive-source "{url}") and use the sha from its '
                            "ARCHIVE-OK return, then retry"
                        )
                    # Resolve the archived blob sha from the commit's tree so
                    # the returned metadata is grounded in the commit itself.
                    names = self._git(
                        "show", "--name-only", "--format=", sha, capture=True
                    )
                    blob_path = next(
                        (ln.strip() for ln in names.splitlines() if ln.strip().startswith("sources/")),
                        "",
                    )
                    result: dict[str, Any] = {"commit": sha, "url": archived_url}
                    if blob_path:
                        blob_sha = os.path.basename(blob_path).rsplit(".", 1)[0]
                        result["blob_sha256"] = blob_sha
                        entry = self._find_index_entry(archived_url, blob_sha)
                        if entry is not None:
                            result["path"] = entry.get("path")
                            result["archived_at"] = entry.get("archived_at")
                    return result
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    # --------------------------------------------------------------- helpers

    def _find_index_entry(self, url: str | None, blob_sha: str) -> dict[str, Any] | None:
        index_abs = os.path.join(self.repo_root, INDEX_NAME)
        found: dict[str, Any] | None = None
        with open(index_abs, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if url is not None:
                    if entry.get("url") == url and entry.get("blob_sha256") == blob_sha:
                        found = entry
                else:
                    sha = str(entry.get("blob_sha256", ""))
                    if sha.startswith(blob_sha):
                        found = entry
        return found

    def _commit_for_path(self, rel_path: str) -> str | None:
        """The OLDEST commit touching ``rel_path`` (= the one that added it)."""
        result = self._git(
            "log", "--format=%H", "--", rel_path, check=True, capture=True
        )
        lines = [line for line in result.splitlines() if line.strip()]
        if not lines:
            return None
        return lines[-1].strip()

    def _commit_files(self, abs_paths: list[str], message: str) -> str | None:
        for path in abs_paths:
            self._git("add", "--", os.path.relpath(path, self.repo_root))
        staged = self._git("diff", "--cached", "--name-only", capture=True) or ""
        if not staged.strip():
            return None
        self._git("commit", "--quiet", "-m", message)
        return self._git("rev-parse", "HEAD", check=True, capture=True).strip()

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


def _validate_url(url: str) -> str:
    from urllib.parse import urlsplit

    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS:
        raise ArchiveError("url must be a non-empty string of at most 2048 characters")
    if url.strip() != url or any(ch.isspace() for ch in url):
        raise ArchiveError("url must not contain whitespace")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ArchiveError("url is invalid") from exc
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ArchiveError("url must be an http(s) URL")
    return url
