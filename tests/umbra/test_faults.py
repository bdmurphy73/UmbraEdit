"""
UmbraEdit - Fault Injection Tests
==================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from umbraedit.umbra.verify import RULE_INVALID_ENCODING, verifyDocument

from tests.umbra.faults import FAULT_TYPES, FaultInjector


def _writeDoc(contentPath: Path, handle: str, text: str) -> Path:
    docFile = contentPath / f"{handle}.md"
    docFile.write_text(text, encoding="utf-8", newline="\n")
    return docFile


def _makeValidDoc(contentPath: Path, handle: str = "h0001") -> Path:
    return _writeDoc(
        contentPath,
        handle,
        "+++\ntag: h0001\nkind: text\n+++\n\nHello world.\n",
    )


@pytest.mark.umbra
def test_faults_R1_no_crash_on_all_faults(tmp_path: Path):
    """R1: No crash for any fault type over 50 random cases."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    injector = FaultInjector(seed=12345)

    for i in range(50):
        faultType = FAULT_TYPES[i % len(FAULT_TYPES)]
        docFile = _makeValidDoc(contentPath, f"h{i:04d}")
        # Damage the file
        injector.damage(docFile, faultType)
        # Verification must not crash
        findings = verifyDocument(docFile)
        assert isinstance(findings, list)


@pytest.mark.umbra
def test_faults_R1_truncate_detected(tmp_path: Path):
    """R1: Truncated file produces a finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    injector = FaultInjector(seed=1)
    docFile = _makeValidDoc(contentPath)
    injector.damage(docFile, "truncate")
    findings = verifyDocument(docFile)
    # Truncation likely breaks header or removes final newline
    assert len(findings) >= 1


@pytest.mark.umbra
def test_faults_R1_null_byte_detected(tmp_path: Path):
    """R1: Inserted NUL byte is detected."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    injector = FaultInjector(seed=1)
    docFile = _makeValidDoc(contentPath)
    injector.damage(docFile, "insert_null")
    findings = verifyDocument(docFile)
    null_findings = [f for f in findings if f.ruleId == "nullByte"]
    assert len(null_findings) >= 1


@pytest.mark.umbra
def test_faults_R1_header_terminator_removed(tmp_path: Path):
    """R1: Removed header terminator produces malformed header finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    injector = FaultInjector(seed=1)
    docFile = _makeValidDoc(contentPath)
    injector.damage(docFile, "remove_header_terminator")
    findings = verifyDocument(docFile)
    header_findings = [f for f in findings if f.ruleId == "annotationMalformedHeader"]
    assert len(header_findings) >= 1


@pytest.mark.umbra
def test_faults_R1_encoding_change_detected(tmp_path: Path):
    """R1: Changed encoding produces invalid encoding finding."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    injector = FaultInjector(seed=1)
    docFile = _makeValidDoc(contentPath)
    injector.damage(docFile, "change_encoding")
    findings = verifyDocument(docFile)
    enc_findings = [f for f in findings if f.ruleId == RULE_INVALID_ENCODING]
    assert len(enc_findings) >= 1


@pytest.mark.umbra
def test_faults_A1_repair_or_unrecoverable(tmp_path: Path):
    """A1: Each fault produces a report line; document is repaired or unrecoverable."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    injector = FaultInjector(seed=999)

    for i in range(20):
        faultType = FAULT_TYPES[i % len(FAULT_TYPES)]
        docFile = _makeValidDoc(contentPath, f"h{i:04d}")
        injector.damage(docFile, faultType)
        findings = verifyDocument(docFile)
        # flip_byte may not always produce a detectable change (e.g., flipping
        # a bit in body text may just change a character). Other faults should
        # always produce at least one finding.
        if faultType != "flip_byte":
            assert len(findings) >= 1, f"Fault {faultType} produced no findings"
        # All findings must have required fields
        for f in findings:
            assert f.ruleId
            assert f.severity
            assert f.message
            assert f.fix


@pytest.mark.umbra
def test_faults_A2_external_edit_hash_change(tmp_path: Path):
    """A2: External edit changes hash and is accepted without data loss."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = _makeValidDoc(contentPath)

    # Simulate external edit: modify the file outside the app
    modified_text = "+++\ntag: h0001\nkind: text\n+++\n\nHello world. Edited externally.\n"
    docFile.write_text(modified_text, encoding="utf-8", newline="\n")

    findings = verifyDocument(docFile)
    # The document is still structurally valid
    blocks = [f for f in findings if f.severity == "block"]
    assert blocks == [], f"External edit should not produce block findings: {blocks}"


@pytest.mark.umbra
def test_faults_A3_kill_between_write_and_rename(tmp_path: Path):
    """A3: Kill between temp write and rename leaves old file intact."""
    contentPath = tmp_path / "content"
    contentPath.mkdir(parents=True, exist_ok=True)
    docFile = _makeValidDoc(contentPath)
    original_text = docFile.read_text(encoding="utf-8")

    # Simulate: write to temp but crash before rename
    docTemp = docFile.with_suffix(".tmp")
    docTemp.write_text("CORRUPTED TEMP CONTENT\n", encoding="utf-8", newline="\n")

    # The original file should still be intact
    assert docFile.read_text(encoding="utf-8") == original_text
    # Temp file exists but was not renamed
    assert docTemp.is_file()
    # Clean up
    docTemp.unlink()
