"""Tests for release asset validation."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile

from pathlib import Path

import pytest

from utils.manual import InvalidManualError, main, validate_manual_pdf

_REPO_ROOT = Path(__file__).parent.parent
_TARBALL_SCRIPT = _REPO_ROOT / "setup" / "linux" / "build-tarball.sh"


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


@pytest.mark.skipif(sys.platform == "win32", reason="The tarball build script requires Bash")
@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is required")
def testBuildTarball_ExcludesGeneratedFiles(tmp_path: Path):
    """Test that generated release and worktree files stay out of the source tarball."""
    sourceRoot = tmp_path / "source"
    scriptPath = sourceRoot / "setup" / "linux" / "build-tarball.sh"
    scriptPath.parent.mkdir(parents=True)
    shutil.copy2(_TARBALL_SCRIPT, scriptPath)

    includedFiles = (
        "umbraedit/core/project.py",
        "tests/_files/ue_en_GB.qm",
    )
    excludedFiles = (
        ".git",
        "docs/build/latex/manual.pdf",
        "docs/source/locales/fr/LC_MESSAGES/index.mo",
        "setup/macos/Info.plist",
        "umbraedit/assets/i18n/ue_fr_FR.qm",
        "umbraedit/assets/manual.pdf",
    )
    for relativePath in includedFiles + excludedFiles:
        filePath = sourceRoot / relativePath
        filePath.parent.mkdir(parents=True, exist_ok=True)
        filePath.write_bytes(b"test content\n")

    result = subprocess.run(
        ["bash", str(scriptPath), "9.9.9"],
        cwd=sourceRoot,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    tarballPath = sourceRoot / "dist" / "umbraedit-9.9.9.tar.gz"
    assert tarballPath.is_file()
    with tarfile.open(tarballPath, "r:gz") as archive:
        members = set(archive.getnames())

    prefix = "umbraedit-9.9.9/"
    for relativePath in includedFiles:
        assert prefix + relativePath in members
    for relativePath in excludedFiles:
        assert prefix + relativePath not in members
