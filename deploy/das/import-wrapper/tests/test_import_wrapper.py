"""Import wrapper test suite (gate faked; no binary needed).

Covers segmentation (entries + prose + truncated-at-EOF), in-string
newline escaping, gate dispatch (pass/fail/escape-recovered/skip
classes, exit-code-only contract), bare-angle flagging, provenance
rendering exactness, provenance param validation, report schema,
--skip-gate behavior, and ordering of emitted entries.  If a real
syntax_check binary is discoverable at test time (env
DAS_SYNTAX_CHECK_BIN), integration cases run against it; they skip
cleanly otherwise.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import WRAPPER_DIR
from import_wrapper import (
    PROVENANCE_ID_RE,
    ImportWrapperError,
    entry_provenance_lines,
    escape_in_string_newlines,
    has_bare_angle,
    load_input,
    provenance_header_lines,
    resolve_syntax_check_bin,
    run,
    run_syntax_check,
    segment,
    truncate_failure_note,
)

BS = "\\"  # one literal backslash


def make_dummy_binary(tmp_path: Path) -> str:
    """A dummy syntax_check stand-in: exists, exits 0 (the gate is faked anyway)."""
    script = tmp_path / "dummy_syntax_check"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    return str(script)


def make_history(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "history.metta"
    p.write_text(text, encoding="utf-8")
    return p


def _raw_newline_in_string(text: str) -> bool:
    """True if a raw newline appears inside a double-quoted string region."""
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == "\n":
                return True
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
        i += 1
    return False


class FakeGate:
    """Fake syntax_check binary: models the real lexer's behavior.

    Raw newlines inside double-quoted strings break the token (the entry
    fails raw; escaping them to \\n recovers it); unbalanced parens
    (truncated entries) always fail.
    """

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, binary, entry_text):
        self.calls.append(entry_text)
        if _raw_newline_in_string(entry_text):
            return 1, "lexer: raw newline in string"
        if not _parens_balanced(entry_text):
            return 1, "parser: unbalanced parens"
        return 0, ""


def _parens_balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    return depth == 0


class TestSegmentation:
    def test_entries_prose_truncated(self):
        text = (
            '("2026-10-02 18:50:03" \n'
            ' ((query "state") (shell "ls")) \n'
            ")\n"
            "2026-10-02 18:52: prose line between entries\n"
            '("2026-10-02 18:51:33" \n'
            ' ((send "line one\n'
            'line two")) \n'
            ")\n"
        )
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]
        entries, prose = segment(lines)
        assert len(entries) == 2
        assert prose == 1

    def test_entry_start_lines_and_verbatim(self):
        text = '("2026-10-02 18:50:03" \n ((query "x")) \n)\n'
        entries, _ = segment(text.split("\n"))
        assert entries[0].start_line == 1
        assert entries[0].text == text.rstrip("\n")
        assert entries[0].truncated is False

    def test_truncated_at_eof(self):
        text = '("2026-10-02 23:59:59" \n ((send "unterminated'
        entries, _ = segment(text.split("\n"))
        assert len(entries) == 1
        assert entries[0].truncated is True

    def test_trailing_newline_not_counted(self):
        text = '("2026-10-02 18:50:03" \n ((query "x")) \n)\n'
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]
        entries, prose = segment(lines)
        assert len(entries) == 1
        assert prose == 0


class TestEscapeInStringNewlines:
    def test_multiline_string_recovered(self):
        text = '((send "line one\nline two"))'
        assert escape_in_string_newlines(text) == '((send "line one\\nline two"))'

    def test_content_outside_strings_untouched(self):
        text = '("2026-10-02 18:50:03" \n ((query "x") (shell "y")) \n)'
        assert escape_in_string_newlines(text) == text

    def test_existing_escape_not_double_escaped(self):
        # a backslash inside a string consumes the next char, so an
        # existing two-char escape (backslash + n) passes through unchanged
        text = '((send "already' + BS + 'nescaped"))'
        assert escape_in_string_newlines(text) == text

    def test_backslash_before_newline_passes_through(self):
        # backslash + newline is a valid lexer escape and passes through as-is
        text = '((send "a' + BS + '\nb"))'
        assert escape_in_string_newlines(text) == text

    def test_escaped_quote_does_not_end_string(self):
        text = '((send "say ' + BS + '"hi' + BS + '"' + '\nnext"))'
        escaped = escape_in_string_newlines(text)
        assert escaped == '((send "say ' + BS + '"hi' + BS + '"\\nnext"))'

    def test_unterminated_string_still_escapes(self):
        text = '((send "unterminated\n'
        assert escape_in_string_newlines(text) == '((send "unterminated\\n'

    def test_carriage_return_newline(self):
        assert escape_in_string_newlines('((send "a\r\nb"))') == '((send "a\\nb"))'

    def test_lone_carriage_return_passes_through(self):
        assert escape_in_string_newlines('((send "a\rb"))') == '((send "a\rb"))'

    def test_quote_outside_string_toggles_state(self):
        assert escape_in_string_newlines('before "mid\nd" after') == 'before "mid\\nd" after'


class TestBareAngle:
    """Bare < > outside strings: flagged (skipped), not silently loaded mangled."""

    def test_bare_angle_detected(self):
        assert has_bare_angle('(foo --> bar)') is True

    def test_bare_angle_inside_string_not_flagged(self):
        assert has_bare_angle('(shell "grep --> file")') is False

    def test_no_bare_angle_in_clean_entry(self):
        assert has_bare_angle('("2026-10-02 18:50:03" \n ((query "x")))') is False


class TestProvenanceRendering:
    def test_header_golden(self):
        lines = provenance_header_lines("omega-das-bridge", "history-v1", "epoch-1")
        assert lines == [
            "(: Campaign Type)",
            "(: Source Type)",
            "(: Epoch Type)",
            '(: "campaign:omega-das-bridge" Campaign)',
            '(: "source:history-v1" Source)',
            '(: "epoch:epoch-1" Epoch)',
        ]

    def test_entry_golden(self):
        lines = entry_provenance_lines("abc123", "omega-das-bridge", "history-v1", "epoch-1")
        assert lines == [
            '(CampaignProvenance "sha256:abc123" '
            '"campaign:omega-das-bridge" "source:history-v1" "epoch:epoch-1")'
        ]


class TestGateDispatch:
    def test_pass_fail_escape_recover_skip(self, tmp_path, monkeypatch):
        text = (
            '("2026-10-02 18:50:03" \n'
            ' ((query "state") (shell "ls")) \n'
            ")\n"
            "2026-10-02 18:52: prose line between entries\n"
            '("2026-10-02 18:51:33" \n'
            ' ((send "line one\n'
            'line two")) \n'
            ")\n"
            '("2026-10-02 19:33:13" \n'
            ' ((websearch "MeTTa hyperon")) \n'
            ")\n"
            '("2026-10-02 23:59:59" \n'
            ' ((send "unterminated'
        )
        fake = FakeGate()
        monkeypatch.setattr("import_wrapper.run_syntax_check", fake)
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        rc = run(
            str(make_history(tmp_path, text)),
            str(out),
            str(report),
            "omega-das-bridge",
            "history-v1",
            "epoch-1",
            syntax_check_bin=make_dummy_binary(tmp_path),
        )
        # 4 entries: 2 pass raw, 1 escape-recovered, 1 skipped (truncated at line 12)
        assert rc == 1
        data = json.loads(report.read_text())
        assert data["pass_raw"] == 2
        assert data["pass_escaped"] == 1
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["line"] == 12
        assert data["emitted_entries"] == 3
        assert data["gate"] == "syntax_check"

    def test_bare_angle_entry_skipped(self, tmp_path, monkeypatch):
        """Entries with bare <> outside strings are skipped, not loaded mangled."""
        text = '("2026-10-02 18:50:03" \n ((nal --> result)) \n)\n'
        fake = FakeGate()
        monkeypatch.setattr("import_wrapper.run_syntax_check", fake)
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        rc = run(
            str(make_history(tmp_path, text)),
            str(out),
            str(report),
            "omega-das-bridge",
            "history-v1",
            "epoch-1",
            syntax_check_bin=make_dummy_binary(tmp_path),
        )
        assert rc == 1
        data = json.loads(report.read_text())
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["reason"] == "bare-angle-outside-strings"

    def test_exit_code_only_contract_fail(self, tmp_path):
        # a binary printing "Syntax check OK" but exiting 1 must FAIL:
        # stdout is unreliable, the exit code is the only verdict
        script = tmp_path / "fake_syntax_check"
        script.write_text("#!/bin/sh\necho 'Syntax check OK'\nexit 1\n")
        script.chmod(0o755)
        exit_code, _ = run_syntax_check(str(script), '((query "x"))')
        assert exit_code == 1

    def test_exit_code_only_contract_pass(self, tmp_path):
        script = tmp_path / "fake_syntax_check"
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        exit_code, _ = run_syntax_check(str(script), '((query "x"))')
        assert exit_code == 0

    def test_skip_gate(self, tmp_path, monkeypatch):
        fake = FakeGate()
        monkeypatch.setattr("import_wrapper.run_syntax_check", fake)
        history = make_history(
            tmp_path, '("2026-10-02 18:50:03" \n ((query "x")) \n)\n'
        )
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        rc = run(
            str(history),
            str(out),
            str(report),
            "omega-das-bridge",
            "history-v1",
            "epoch-1",
            skip_gate=True,
        )
        assert rc == 0
        data = json.loads(report.read_text())
        assert data["gate"] == "skipped"
        assert data["pass_raw"] == 0
        assert data["pass_escaped"] == 0
        assert data["emitted_entries"] == 1

    def test_ordering_and_escaping(self, tmp_path, monkeypatch):
        text = (
            '("2026-10-02 18:50:03" \n'
            ' ((query "state")) \n'
            ")\n"
            '("2026-10-02 18:51:33" \n'
            ' ((send "line one\n'
            'line two")) \n'
            ")\n"
        )
        fake = FakeGate()
        monkeypatch.setattr("import_wrapper.run_syntax_check", fake)
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        rc = run(
            str(make_history(tmp_path, text)),
            str(out),
            str(report),
            "omega-das-bridge",
            "history-v1",
            "epoch-1",
            syntax_check_bin=make_dummy_binary(tmp_path),
        )
        assert rc == 0
        content = out.read_text()
        # both entries emitted in original order; the second in escaped form
        assert '("2026-10-02 18:50:03"' in content
        assert '((send "line one\\nline two"))' in content


class TestValidation:
    def test_campaign_invalid(self, tmp_path):
        history = make_history(
            tmp_path, '("2026-10-02 18:50:03" \n ((query "x")) \n)\n'
        )
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        with pytest.raises(ImportWrapperError):
            run(
                str(history),
                str(out),
                str(report),
                "Invalid_Campaign",
                "history-v1",
                "epoch-1",
            )

    def test_source_invalid(self, tmp_path):
        history = make_history(
            tmp_path, '("2026-10-02 18:50:03" \n ((query "x")) \n)\n'
        )
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        with pytest.raises(ImportWrapperError):
            run(
                str(history),
                str(out),
                str(report),
                "omega-das-bridge",
                "Invalid_Source",
                "epoch-1",
            )

    def test_epoch_invalid(self, tmp_path):
        history = make_history(
            tmp_path, '("2026-10-02 18:50:03" \n ((query "x")) \n)\n'
        )
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        with pytest.raises(ImportWrapperError):
            run(
                str(history),
                str(out),
                str(report),
                "omega-das-bridge",
                "history-v1",
                "Invalid_Epoch",
            )

    def test_size_refusal(self, tmp_path):
        big = tmp_path / "big.metta"
        big.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        with pytest.raises(ImportWrapperError):
            run(str(big), str(out), str(report), "a" * 65, "history-v1", "epoch-1")

    def test_utf8_refusal(self, tmp_path):
        bad = tmp_path / "bad.metta"
        bad.write_bytes(b"\xff\xfe")
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        with pytest.raises(ImportWrapperError):
            run(str(bad), str(out), str(report), "omega-das-bridge", "history-v1", "epoch-1")

    def test_binary_missing(self, tmp_path):
        history = make_history(
            tmp_path, '("2026-10-02 18:50:03" \n ((query "x")) \n)\n'
        )
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        with pytest.raises(ImportWrapperError):
            run(
                str(history),
                str(out),
                str(report),
                "omega-das-bridge",
                "history-v1",
                "epoch-1",
                syntax_check_bin="/nonexistent/syntax_check",
            )


class TestReportSchema:
    def test_report_keys(self, tmp_path):
        history = make_history(
            tmp_path, '("2026-10-02 18:50:03" \n ((query "x")) \n)\n'
        )
        out = tmp_path / "load.metta"
        report = tmp_path / "report.json"
        rc = run(
            str(history),
            str(out),
            str(report),
            "omega-das-bridge",
            "history-v1",
            "epoch-1",
            skip_gate=True,
        )
        assert rc == 0
        data = json.loads(report.read_text())
        assert set(data.keys()) == {
            "campaign",
            "source",
            "epoch",
            "source_sha256",
            "source_path",
            "total_lines",
            "entries",
            "prose_lines",
            "pass_raw",
            "pass_escaped",
            "skipped",
            "emitted_entries",
            "out_path",
            "gate",
        }


@pytest.mark.skipif(
    not os.environ.get("DAS_SYNTAX_CHECK_BIN"),
    reason="no real syntax_check binary (set DAS_SYNTAX_CHECK_BIN)",
)
class TestIntegration:
    """Integration cases against the real syntax_check binary."""

    def test_provenance_forms_pass(self):
        binary = os.environ["DAS_SYNTAX_CHECK_BIN"]
        entry = '(: "campaign:x" Campaign)\n(: "source:y" Source)\n(: "epoch:z" Epoch)\n(CampaignProvenance "sha256:abc" "campaign:x" "source:y" "epoch:z")'
        exit_code, _ = run_syntax_check(binary, entry)
        assert exit_code == 0

    def test_multiline_string_fails_raw(self):
        binary = os.environ["DAS_SYNTAX_CHECK_BIN"]
        # raw newline inside string + paren in content: leaked tokens break the parse
        entry = '((send "line (one\nline two"))'
        exit_code, _ = run_syntax_check(binary, entry)
        assert exit_code == 1

    def test_multiline_string_passes_escaped(self):
        binary = os.environ["DAS_SYNTAX_CHECK_BIN"]
        entry = '((send "line one' + BS + 'nline two"))'
        exit_code, _ = run_syntax_check(binary, entry)
        assert exit_code == 0
