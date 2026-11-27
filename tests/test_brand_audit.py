"""
UmbraEdit - Brand Audit Tests
=============================

This file is a part of UmbraEdit.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import sys

from pathlib import Path

import pytest

from utils import umbra_brand_audit as brand


@pytest.fixture()
def auditRoot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the brand audit at a temporary source tree."""
    monkeypatch.setattr(brand, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(brand, "HASHES_FILE", tmp_path / "hashes.txt")
    return tmp_path


@pytest.mark.base
def testBrand_noLegacyFileName(auditRoot: Path):
    """Test that a file with the old product name in its name is caught."""
    (auditRoot / "setup" / "windows").mkdir(parents=True)
    (auditRoot / "setup" / "windows" / "novelWriter.exe").write_bytes(b"MZ")

    failures = brand.checkFileNames()
    assert len(failures) == 1
    assert "novelWriter.exe" in failures[0]


@pytest.mark.base
def testBrand_allowedLegacyFileName(auditRoot: Path):
    """Test that the allowed documentation file is not flagged."""
    docPath = auditRoot / "docs" / "source" / "umbra" / "introduction"
    docPath.mkdir(parents=True)
    (docPath / "coming-from-novelwriter.rst").write_text("text", encoding="utf-8")

    assert brand.checkFileNames() == []


@pytest.mark.base
def testBrand_legacyNameInBinary(auditRoot: Path):
    """Test that the old product name in binary metadata is caught."""
    winDir = auditRoot / "setup" / "windows"
    winDir.mkdir(parents=True)
    # The upstream launcher carries the product name as a UTF-16 string in
    # its version resources.
    payload = "novelWriter".encode("utf-16-le")
    (winDir / "UmbraEdit.exe").write_bytes(b"MZ" + payload)

    failures = brand.checkBinaryNames()
    assert len(failures) == 1
    assert "UmbraEdit.exe" in failures[0]


@pytest.mark.base
def testBrand_upstreamBinaryHash(auditRoot: Path):
    """Test that a copy of an upstream binary is caught by its hash."""
    winDir = auditRoot / "setup" / "windows"
    winDir.mkdir(parents=True)
    exeFile = winDir / "UmbraEdit.exe"
    exeFile.write_bytes(b"MZ-upstream-binary")

    import hashlib

    digest = hashlib.sha256(exeFile.read_bytes()).hexdigest()
    (auditRoot / "hashes.txt").write_text(f"# comment\n{digest}\n", encoding="utf-8")

    failures = brand.checkHashes()
    assert len(failures) == 1
    assert "UmbraEdit.exe" in failures[0]


@pytest.mark.base
def testBrand_cleanTree(auditRoot: Path):
    """Test that a clean source tree passes all the checks."""
    winDir = auditRoot / "setup" / "windows"
    winDir.mkdir(parents=True)
    (winDir / "UmbraEdit.exe").write_bytes(b"MZ-clean")
    (winDir / "umbraedit.ico").write_bytes(b"icon")

    assert brand.checkFileNames() == []
    assert brand.checkBinaryNames() == []
    assert brand.checkHashes() == []


@pytest.mark.base
def testBrand_skipGeneratedFolders(auditRoot: Path):
    """Test that generated documentation output is not flagged."""
    buildDir = auditRoot / "docs" / "build" / "html-en"
    buildDir.mkdir(parents=True)
    (buildDir / "coming-from-novelwriter.html").write_text("text", encoding="utf-8")

    assert brand.checkFileNames() == []


@pytest.mark.base
def testBrand_auditRunsOnRepo():
    """Test that the audit passes on the actual repository."""
    assert brand.main() == 0


if __name__ == "__main__":
    sys.exit(0)
