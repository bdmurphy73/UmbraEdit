"""
UmbraEdit - Verification Tests
===============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from umbraedit.umbra.verify import (
    RULE_EMPTY_BODY,
    RULE_INVALID_ANNOTATION,
    RULE_INVALID_ENCODING,
    RULE_MALFORMED_HEADER,
    RULE_MISSING_TAG,
    RULE_NO_FINAL_NEWLINE,
    RULE_NULL_BYTE,
    RULE_TAG_FILENAME_MISMATCH,
    RULE_UNEXPECTED_TRAILING_WS,
    SEVERITY_ADVISORY,
    SEVERITY_BLOCK,
    Problem,
    VerifyReport,
    verifyDocument,
    verifyProject,
)


def _writeDoc(contentPath: Path, handle: str, text: str) -> Path:
    """Write a document file and return its path."""
    docFile = contentPath / f"{handle}.md"
    docFile.write_text(text, encoding="utf-8", newline="\n")
    return docFile


@pytest.mark.umbra
def test_verify_R1_valid_document_no_findings(tmp_path: Path):
    """R1: A valid document produces no findings."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = _writeDoc(contentPath, "h0001", "+++\ntag: h0001\nkind: text\n+++\n\nHello world.\n")
    findings = verifyDocument(docFile)
    assert findings == []


@pytest.mark.umbra
def test_verify_R1_invalid_encoding(tmp_path: Path):
    """R1: Invalid UTF-8 encoding produces a block finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = contentPath / "h0001.md"
    docFile.write_bytes(b"\xff\xfe invalid utf-8")
    findings = verifyDocument(docFile)
    assert len(findings) == 1
    assert findings[0].ruleId == RULE_INVALID_ENCODING
    assert findings[0].severity == SEVERITY_BLOCK
    assert findings[0].handle == "h0001"


@pytest.mark.umbra
def test_verify_R1_null_byte(tmp_path: Path):
    """R1: NUL bytes produce a block finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = contentPath / "h0001.md"
    docFile.write_bytes(b"+++\ntag: h0001\n+++\n\nHello \x00 World\n")
    findings = verifyDocument(docFile)
    assert len(findings) == 1
    assert findings[0].ruleId == RULE_NULL_BYTE
    assert findings[0].severity == SEVERITY_BLOCK


@pytest.mark.umbra
def test_verify_R1_malformed_header(tmp_path: Path):
    """R1: Missing header block produces a block finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = _writeDoc(contentPath, "h0001", "No header here\n\nJust body text.\n")
    findings = verifyDocument(docFile)
    assert len(findings) == 1
    assert findings[0].ruleId == RULE_MALFORMED_HEADER
    assert findings[0].severity == SEVERITY_BLOCK


@pytest.mark.umbra
def test_verify_R1_missing_tag(tmp_path: Path):
    """R1: Missing @tag in header produces a block finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = _writeDoc(contentPath, "h0001", "+++\nkind: text\n+++\n\nHello world.\n")
    findings = verifyDocument(docFile)
    assert len(findings) == 1
    assert findings[0].ruleId == RULE_MISSING_TAG
    assert findings[0].severity == SEVERITY_BLOCK


@pytest.mark.umbra
def test_verify_R1_tag_filename_mismatch(tmp_path: Path):
    """R1: Tag not matching filename produces a block finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = _writeDoc(contentPath, "h0001", "+++\ntag: different\nkind: text\n+++\n\nHello world.\n")
    findings = verifyDocument(docFile)
    assert len(findings) == 1
    assert findings[0].ruleId == RULE_TAG_FILENAME_MISMATCH
    assert findings[0].severity == SEVERITY_BLOCK


@pytest.mark.umbra
def test_verify_R1_trailing_whitespace(tmp_path: Path):
    """R1: Trailing whitespace produces an advisory finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = _writeDoc(contentPath, "h0001", "+++\ntag: h0001\nkind: text\n+++\n\nHello world.  \n")
    findings = verifyDocument(docFile)
    trailing = [f for f in findings if f.ruleId == RULE_UNEXPECTED_TRAILING_WS]
    assert len(trailing) == 1
    assert trailing[0].severity == SEVERITY_ADVISORY


@pytest.mark.umbra
def test_verify_R1_no_final_newline(tmp_path: Path):
    """R1: Missing final newline produces an advisory finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = contentPath / "h0001.md"
    docFile.write_text("+++\ntag: h0001\nkind: text\n+++\n\nHello world.", encoding="utf-8", newline="\n")
    findings = verifyDocument(docFile)
    noNl = [f for f in findings if f.ruleId == RULE_NO_FINAL_NEWLINE]
    assert len(noNl) == 1
    assert noNl[0].severity == SEVERITY_ADVISORY


@pytest.mark.umbra
def test_verify_R1_empty_body(tmp_path: Path):
    """R1: Empty body text produces an advisory finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = _writeDoc(contentPath, "h0001", "+++\ntag: h0001\nkind: text\n+++\n\n   \n")
    findings = verifyDocument(docFile)
    empty = [f for f in findings if f.ruleId == RULE_EMPTY_BODY]
    assert len(empty) == 1
    assert empty[0].severity == SEVERITY_ADVISORY


@pytest.mark.umbra
def test_verify_R1_voice_line_always_parses(tmp_path: Path):
    """R1: Any %Voice: line starting with the prefix parses successfully."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    # Even minimal %Voice: lines parse without error
    docFile = _writeDoc(contentPath, "h0001", "+++\ntag: h0001\nkind: text\n+++\n\n%Voice:\n")
    findings = verifyDocument(docFile)
    voice = [f for f in findings if f.ruleId == RULE_INVALID_ANNOTATION]
    assert voice == []


@pytest.mark.umbra
def test_verify_R1_valid_voice_line_no_finding(tmp_path: Path):
    """R1: Valid %Voice: line produces no finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = _writeDoc(contentPath, "h0001", "+++\ntag: h0001\nkind: text\n+++\n\n%Voice: Alice: Hello world.\n")
    findings = verifyDocument(docFile)
    voice = [f for f in findings if f.ruleId == RULE_INVALID_ANNOTATION]
    assert voice == []


@pytest.mark.umbra
def test_verify_R1_project_with_content_path(tmp_path: Path):
    """R1: verifyProject scans all documents in content/."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    _writeDoc(contentPath, "h0001", "+++\ntag: h0001\nkind: text\n+++\n\nHello.\n")
    _writeDoc(contentPath, "h0002", "+++\ntag: h0002\nkind: text\n+++\n\nWorld.\n")
    report = verifyProject(tmp_path)
    assert report.projectPath == str(tmp_path)
    assert len(report.findings) == 0
    assert not report.blocked


@pytest.mark.umbra
def test_verify_R1_project_missing_content_path(tmp_path: Path):
    """R1: verifyProject with no content/ produces a block finding."""
    report = verifyProject(tmp_path)
    assert len(report.findings) == 1
    assert report.findings[0].severity == SEVERITY_BLOCK
    assert report.blocked


@pytest.mark.umbra
def test_verify_A1_report_has_timestamp(tmp_path: Path):
    """A1: VerifyReport includes a UTC ISO 8601 timestamp."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    _writeDoc(contentPath, "h0001", "+++\ntag: h0001\nkind: text\n+++\n\nHello.\n")
    report = verifyProject(tmp_path)
    assert report.ranAt != ""
    assert "T" in report.ranAt
    assert report.ranAt.endswith("Z")


@pytest.mark.umbra
def test_verify_A2_unicode_content(tmp_path: Path):
    """A2: Unicode content including Chinese, Spanish accents, curly quotes."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    text = "+++\ntag: h0001\nkind: text\n+++\n\nHola José, 你好,“curly quotes”.\n"
    docFile = _writeDoc(contentPath, "h0001", text)
    findings = verifyDocument(docFile)
    # Should have no block findings for valid unicode
    blocks = [f for f in findings if f.severity == SEVERITY_BLOCK]
    assert blocks == []


@pytest.mark.umbra
def test_verify_A3_large_document(tmp_path: Path):
    """A3: Very large document does not crash."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    text = "+++\ntag: h0001\nkind: text\n+++\n\n" + "x" * 100000 + "\n"
    docFile = _writeDoc(contentPath, "h0001", text)
    findings = verifyDocument(docFile)
    assert isinstance(findings, list)


@pytest.mark.umbra
def test_verify_A4_problem_dataclass_immutable():
    """A4: Problem dataclass is frozen (immutable)."""
    from dataclasses import FrozenInstanceError

    p = Problem(ruleId="test", severity="block", message="msg", fix="fix")
    with pytest.raises(FrozenInstanceError, match=""):
        p.ruleId = "changed"


@pytest.mark.umbra
def test_verify_A5_verify_report_blocked_property():
    """A5: VerifyReport.blocked returns True for block findings."""
    p_block = Problem(ruleId="r1", severity="block", message="m", fix="f")
    p_adv = Problem(ruleId="r2", severity="advisory", message="m", fix="f")
    report_blocked = VerifyReport(projectPath="/p", findings=[p_block], ranAt="")
    report_not_blocked = VerifyReport(projectPath="/p", findings=[p_adv], ranAt="")
    assert report_blocked.blocked is True
    assert report_not_blocked.blocked is False


@pytest.mark.umbra
def test_verify_R2_sha256_file_hash(tmp_path: Path):
    """R2: _sha256File produces correct SHA-256 hash."""
    from umbraedit.umbra.verify import _sha256File

    docFile = tmp_path / "test.md"
    docFile.write_text("hello\n", encoding="utf-8")
    h = _sha256File(docFile)
    assert len(h) == 64
    assert h == "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"


@pytest.mark.umbra
def test_verify_R2_parse_header_closed(tmp_path: Path):
    """R2: Header parsing handles properly closed +++ blocks."""
    from umbraedit.umbra.verify import _parseHeader

    text = "+++\ntag: foo\nkind: bar\n+++\n\nBody text.\n"
    result = _parseHeader(text)
    assert result is not None
    meta, body = result
    assert meta["tag"] == "foo"
    assert meta["kind"] == "bar"
    assert body == "\nBody text.\n"


@pytest.mark.umbra
def test_verify_R2_parse_header_unclosed(tmp_path: Path):
    """R2: Header parsing returns None for unclosed block."""
    from umbraedit.umbra.verify import _parseHeader

    text = "+++\ntag: foo\nkind: bar\n\nNo closing.\n"
    result = _parseHeader(text)
    assert result is None


@pytest.mark.umbra
def test_verify_R2_no_header(tmp_path: Path):
    """R2: Text without +++ header returns None."""
    from umbraedit.umbra.verify import _parseHeader

    result = _parseHeader("Just body text.\n")
    assert result is None
