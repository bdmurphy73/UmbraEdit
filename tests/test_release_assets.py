"""Tests for release asset validation."""

from __future__ import annotations

import os

from pathlib import Path

import pytest

from utils.manual import InvalidManualError, main, validate_manual_pdf


def _validPdf() -> bytes:
    """Return a minimal structurally valid PDF payload."""
    return b"%PDF-1.7\n" + (b"release-manual-data\n" * 256) + b"startxref\n0\n%%EOF\n"


def testValidateManualPdf_AcceptsCompletePdf(tmp_path: Path):
    """Test that a complete PDF manual is accepted."""
    manual = tmp_path / "manual.pdf"
    manual.write_bytes(_validPdf())

    validate_manual_pdf(manual)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not a pdf",
        b"%PDF-1.7\n" + (b"x" * 5000),
        b"%PDF-1.7\n" + (b"x" * 5000) + b"startxref\n0\n",
    ],
)
def testValidateManualPdf_RejectsIncompletePdf(tmp_path: Path, payload: bytes):
    """Test that empty and malformed PDF manuals are rejected."""
    manual = tmp_path / "manual.pdf"
    manual.write_bytes(payload)

    with pytest.raises(InvalidManualError):
        validate_manual_pdf(manual)


def testValidateManualPdf_RejectsSymlink(tmp_path: Path):
    """Test that a symbolic link is not accepted as a release manual."""
    target = tmp_path / "manual.pdf"
    target.write_bytes(_validPdf())
    link = tmp_path / "manual-link.pdf"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("Symbolic links are not supported on this platform")

    with pytest.raises(InvalidManualError):
        validate_manual_pdf(link)


def testValidateManualPdf_CommandReportsFailure(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Test that the command-line validator returns a failure status."""
    manual = tmp_path / "manual.pdf"
    manual.write_bytes(b"")

    assert main([str(manual)]) == 1
    assert "ERROR" in capsys.readouterr().out
