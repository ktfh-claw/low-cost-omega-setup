#!/usr/bin/env python3
"""Thin import wrapper for the omega-DAS bridge campaign (Phase 2).

Bulk/history loads go through the upstream das-metta-parser binary pair
(``syntax_check`` gate + ``db_loader`` load).  This wrapper segments the
Omega history file into structural entries, syntax-gates each entry with
the upstream ``syntax_check`` binary, falls back to in-string newline
escaping for entries that fail raw, flags bare ``<``/``>`` outside
strings (silently dropped by the upstream lexer — such entries are
skipped, not silently loaded mangled), decorates accepted entries with
Campaign/Source/Epoch provenance (bridge-owned schema), and writes a
db_loader-ready output file plus a JSON per-entry report.

Gate contract: the verdict is the EXIT CODE plus an error-pattern scan
of stdout/stderr — the upstream ``syntax_check`` prints
``Syntax check OK`` unconditionally in some builds, so the OK line is
not a valid gate signal.

Stdlib-only Python; the db_loader load step is environment-variable
driven and documented in README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Sequence

MAX_INPUT_BYTES = 8 * 1024 * 1024
PROVENANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
ENTRY_START_RE = re.compile(r'^\("\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"')
FAILURE_NOTE_MAX = 200

# Error patterns the gate scans for in syntax_check stdout/stderr.  The
# upstream failure path prints "Parse error near line N" / "Error
# message: ..." via yyerror; belt-and-suspenders against builds whose
# OK print is unconditional.
GATE_ERROR_PATTERNS = (
    re.compile(r"Parse error near line"),
    re.compile(r"Error message:"),
    re.compile(r"syntax error", re.IGNORECASE),
)


class ImportWrapperError(Exception):
    """Invalid input or arguments (the wrapper exits 2 on this)."""


@dataclass(frozen=True)
class Entry:
    """One structural entry: verbatim text, 1-based start line, truncated flag."""

    start_line: int
    text: str
    truncated: bool


def segment(lines: Sequence[str]) -> tuple[list[Entry], int]:
    """Split file lines into entries; returns ``(entries, prose_line_count)``.

    Entries start with a line matching ``ENTRY_START_RE`` and end at the
    first subsequent bare ``)`` line (inclusive).  Lines outside entries
    are prose.  EOF mid-entry yields a truncated entry (counted as an
    entry; it will fail the gate and be reported as skipped).
    """
    entries: list[Entry] = []
    prose = 0
    current: list[str] = []
    start: int | None = None
    for lineno, line in enumerate(lines, 1):
        bare = line.rstrip("\r")
        if start is None:
            if ENTRY_START_RE.match(bare):
                current = [line]
                start = lineno
            else:
                prose += 1
            continue
        if bare == ")":
            current.append(line)
            entries.append(Entry(start, "\n".join(current), False))
            current = []
            start = None
        else:
            current.append(line)
    if start is not None:
        entries.append(Entry(start, "\n".join(current), True))
    return entries, prose


def escape_in_string_newlines(text: str) -> str:
    """Escape raw newlines inside double-quoted string regions to ``\\\\n``.

    Scans char-by-char tracking in-string state with backslash-escape
    awareness: a backslash inside a string consumes the following char
    (so existing two-char escapes such as ``\\\\n`` are passed through and
    never double-escaped), an unescaped ``"`` toggles the string state.
    Raw ``\\n`` (and ``\\r\\n``) inside strings becomes the two characters
    ``\\\\`` ``n``; content outside strings is untouched.
    """
    out: list[str] = []
    in_string = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\":
                if i + 1 < n:
                    out.append(ch)
                    out.append(text[i + 1])
                    i += 2
                else:
                    out.append(ch)
                    i += 1
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
                i += 1
                continue
            if ch == "\n":
                out.append("\\n")
                i += 1
                continue
            if ch == "\r":
                if i + 1 < n and text[i + 1] == "\n":
                    out.append("\\n")
                    i += 2
                else:
                    out.append(ch)
                    i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def has_bare_angle(text: str) -> bool:
    """True if a bare ``<`` or ``>`` appears outside double-quoted strings.

    The upstream lexer silently drops bare ``<``/``>`` outside strings
    (flex default rule); such entries would be loaded mangled, so the
    wrapper flags them for a skip verdict instead.
    """
    in_string = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\":
                if i + 1 < n:
                    i += 2
                else:
                    i += 1
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch in ("<", ">"):
            return True
        i += 1
        continue
    return False


def run_syntax_check(binary: str, entry_text: str) -> tuple[int, str]:
    """Gate one entry: run ``syntax_check`` on it, return (exit_code, stderr).

    The verdict combines the EXIT CODE with an error-pattern scan of
    stdout/stderr — the ``Syntax check OK`` print is unconditional in
    some upstream builds and is not a valid gate signal.  The returned
    stderr is the binary's first stderr line (used for the failure
    note).
    """
    with tempfile.NamedTemporaryFile(
        "w", suffix=".metta", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(entry_text)
        temp_path = tf.name
    try:
        proc = subprocess.run([binary, temp_path], capture_output=True, text=True)
        stderr_first = ""
        if proc.stderr:
            stderr_first = proc.stderr.strip().split("\n")[0]
        return proc.returncode, stderr_first
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def resolve_syntax_check_bin(explicit: str | None = None) -> str:
    """Resolve the syntax_check binary path.

    Order: ``--syntax-check-bin``, env ``DAS_SYNTAX_CHECK_BIN``, env
    ``DAS_METTA_PARSER_DIR`` + ``bin/syntax_check``, else bare
    ``syntax_check`` on PATH.
    """
    if explicit:
        return explicit
    env_bin = os.environ.get("DAS_SYNTAX_CHECK_BIN")
    if env_bin:
        return env_bin
    parser_dir = os.environ.get("DAS_METTA_PARSER_DIR")
    if parser_dir:
        return os.path.join(parser_dir, "bin", "syntax_check")
    return "syntax_check"


def _binary_exists(binary: str) -> bool:
    if os.path.sep in binary:
        return os.path.isfile(binary) and os.access(binary, os.X_OK)
    return shutil.which(binary) is not None


# The load file must contain NO type-ascription forms (`(: ...)`) —
# upstream db_loader turns every `(:` line into a junk Symbol type-lattice
# registration (live-measured iter9: atom_types 16455 on a load that should
# have produced 0; the October operator-lane baseline for the same loader
# and client was atom_types = 0).  Provenance is therefore expressed ONLY
# as ground links (one CampaignProvenance Expression per entry), which the
# same live load proved to land correctly with exact payloads.


def entry_provenance_lines(
    fact_sha256: str, campaign: str, source: str, epoch: str
) -> list[str]:
    """Per-entry provenance: CampaignProvenance link (fact -> campaign/source/epoch)."""
    return [
        f'(CampaignProvenance "sha256:{fact_sha256}" '
        f'"campaign:{campaign}" "source:{source}" "epoch:{epoch}")'
    ]


def load_input(input_path: str) -> tuple[str, bytes]:
    """Read the input file: UTF-8 text + raw bytes (for sha256)."""
    try:
        with open(input_path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        raise ImportWrapperError(f"cannot read input file: {exc}") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise ImportWrapperError(
            f"input exceeds the {MAX_INPUT_BYTES} byte limit (got {len(raw)})"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ImportWrapperError(f"input is not valid UTF-8: {exc}") from exc
    return text, raw


def truncate_failure_note(stderr_first_line: str) -> str:
    """Truncate a failure note to ~200 chars."""
    if len(stderr_first_line) <= FAILURE_NOTE_MAX:
        return stderr_first_line
    return stderr_first_line[:FAILURE_NOTE_MAX]


def run(  # noqa: C901
    input_path: str,
    out_path: str,
    report_path: str,
    campaign: str,
    source: str,
    epoch: str,
    syntax_check_bin: str | None = None,
    skip_gate: bool = False,
    no_provenance: bool = False,
) -> int:
    """Run the full pipeline; returns the process exit code.

    Exit codes: 0 = all entries passed (raw+escaped), 1 = any skipped,
    2 = invalid input/args (raised as :class:`ImportWrapperError`).
    """
    for name, value in (("campaign", campaign), ("source", source), ("epoch", epoch)):
        if not PROVENANCE_ID_RE.match(value):
            raise ImportWrapperError(
                f"{name} {value!r} does not match {PROVENANCE_ID_RE.pattern}"
            )
    text, raw = load_input(input_path)
    file_sha256 = hashlib.sha256(raw).hexdigest()
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # trailing newline artifact, not a real line
    entries, prose = segment(lines)

    binary = None if skip_gate else resolve_syntax_check_bin(syntax_check_bin)
    if binary is not None and not _binary_exists(binary):
        raise ImportWrapperError(
            f"syntax_check binary not found at {binary!r}; pass --syntax-check-bin "
            "or set DAS_SYNTAX_CHECK_BIN / DAS_METTA_PARSER_DIR (or --skip-gate)"
        )

    pass_raw = 0
    pass_escaped = 0
    skipped: list[dict] = []
    emitted: list[tuple[Entry, str]] = []  # (entry, emitted text) in original order
    for entry in entries:
        if skip_gate:
            emitted.append((entry, entry.text))
            continue
        if has_bare_angle(entry.text):
            skipped.append(
                {
                    "line": entry.start_line,
                    "reason": "bare-angle-outside-strings",
                    "detail": "upstream lexer silently drops < and > from bare symbols",
                }
            )
            continue
        escaped = escape_in_string_newlines(entry.text)
        if escaped != entry.text:
            # raw newlines inside strings: always escape first (the
            # escaped form is the canonical loadable form), then gate
            esc_exit, _ = run_syntax_check(binary, escaped)
            if esc_exit == 0:
                pass_escaped += 1
                emitted.append((entry, escaped))
                continue
            skipped.append(
                {
                    "line": entry.start_line,
                    "reason": "gate-failure",
                    "detail": truncate_failure_note(""),
                }
            )
            continue
        # no raw newlines: gate the raw form only
        exit_code, stderr_first = run_syntax_check(binary, entry.text)
        if exit_code == 0:
            pass_raw += 1
            emitted.append((entry, entry.text))
            continue
        skipped.append(
            {
                "line": entry.start_line,
                "reason": "gate-failure",
                "detail": truncate_failure_note(stderr_first),
            }
        )

    # Output file: accepted entries in original order (escaped version
    # when that's what passed), each followed by its per-entry ground
    # provenance link.  NO header block and NO `(:` type-ascription forms
    # anywhere (they pollute the atom_types lattice; see module comment).
    # Prose lines are NOT emitted.
    out_lines: list[str] = []
    for entry, emitted_text in emitted:
        fact_sha = hashlib.sha256(entry.text.encode("utf-8")).hexdigest()
        out_lines.append(emitted_text)
        if not no_provenance:
            out_lines.extend(
                entry_provenance_lines(fact_sha, campaign, source, epoch)
            )
    if not out_lines:
        out_lines = [""]  # empty input: emit a single blank line
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")

    report = {
        "campaign": campaign,
        "source": source,
        "epoch": epoch,
        "source_sha256": file_sha256,
        "source_path": input_path,
        "total_lines": len(lines),
        "entries": len(entries),
        "prose_lines": prose,
        "pass_raw": pass_raw,
        "pass_escaped": pass_escaped,
        "skipped": skipped,
        "emitted_entries": len(emitted),
        "out_path": out_path,
        "gate": "syntax_check" if not skip_gate else "skipped",
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    return 1 if skipped else 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="import_wrapper",
        description=(
            "Thin import wrapper: segment history.metta, syntax-gate entries "
            "with the upstream das-metta-parser syntax_check binary, "
            "newline-escape fallback, provenance decoration, db_loader-ready output."
        ),
    )
    parser.add_argument("--input", required=True, help="input MeTTa history file")
    parser.add_argument("--out", required=True, help="output load file path")
    parser.add_argument("--report", required=True, help="JSON report path")
    parser.add_argument(
        "--campaign",
        required=True,
        help="campaign id (provenance; kebab-case, e.g. omega-das-bridge)",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="source id (provenance; kebab-case, e.g. history-v1)",
    )
    parser.add_argument(
        "--epoch",
        required=True,
        help="store epoch (provenance; kebab-case, e.g. epoch-1)",
    )
    parser.add_argument(
        "--syntax-check-bin",
        default=None,
        help="path to the syntax_check binary (default: env DAS_SYNTAX_CHECK_BIN, "
        "env DAS_METTA_PARSER_DIR + bin/syntax_check, or bare syntax_check on PATH)",
    )
    parser.add_argument(
        "--no-provenance",
        action="store_true",
        help="disable provenance decoration (header block only)",
    )
    parser.add_argument(
        "--skip-gate",
        action="store_true",
        help="tests only: emit all entries without gating (still provenance + report)",
    )
    args = parser.parse_args(argv)
    try:
        return run(
            args.input,
            args.out,
            args.report,
            args.campaign,
            args.source,
            args.epoch,
            syntax_check_bin=args.syntax_check_bin,
            skip_gate=args.skip_gate,
            no_provenance=args.no_provenance,
        )
    except ImportWrapperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
