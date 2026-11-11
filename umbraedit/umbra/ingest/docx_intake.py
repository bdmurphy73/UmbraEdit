"""
UmbraEdit - DOCX Intake Stage
==============================

This file is a part of UmbraEdit, a fork of novelWriter.

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

import hashlib
import logging
import subprocess
import zipfile

from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntakeResult:
    """Result of the intake stage."""

    file_path: Path
    sha256: str
    file_size: int
    pandoc_version: str
    valid: bool
    error: str | None = None


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _get_pandoc_version() -> str:
    """Get Pandoc version string."""
    try:
        result = subprocess.run(
            ["pandoc", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        # First line contains version, e.g., "pandoc 3.1.11"
        lines = result.stdout.strip().split("\n")
        if lines:
            return lines[0].strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
        logger.warning("Could not get Pandoc version: %s", e)
    return "unknown"


def _validate_docx(file_path: Path) -> str | None:
    """Validate DOCX file structure. Returns error message if invalid."""
    if not file_path.is_file():
        return f"File not found: {file_path}"

    # Check if it's a valid ZIP
    if not zipfile.is_zipfile(file_path):
        return f"Not a valid ZIP/DOCX file: {file_path}"

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            names = zf.namelist()

            # Must have word/document.xml
            if "word/document.xml" not in names:
                return "Missing word/document.xml in DOCX"

            # Reject encrypted/macro-enabled files
            if "vbaProject.bin" in names:
                return "Macro-enabled DOCX (.docm) files are not supported"

            # Check for encryption indicators
            if "word/document.xml.enc" in names or "EncryptedPackage" in names:
                return "Encrypted DOCX files are not supported"

    except zipfile.BadZipFile as e:
        return f"Corrupted ZIP file: {e}"

    return None


class DocxIntake:
    """Intake stage: validate file, compute hash, detect Pandoc version."""

    def __init__(self) -> None:
        self._pandoc_version: str | None = None

    def process(self, file_path: Path) -> IntakeResult:
        """Process a DOCX file through the intake stage."""
        logger.info("Intake: processing %s", file_path)

        # Validate file
        error = _validate_docx(file_path)
        if error:
            return IntakeResult(
                file_path=file_path,
                sha256="",
                file_size=0,
                pandoc_version=self._get_pandoc_version_cached(),
                valid=False,
                error=error,
            )

        # Compute SHA-256
        sha256 = _compute_sha256(file_path)
        file_size = file_path.stat().st_size

        # Get Pandoc version
        pandoc_version = self._get_pandoc_version_cached()

        return IntakeResult(
            file_path=file_path,
            sha256=sha256,
            file_size=file_size,
            pandoc_version=pandoc_version,
            valid=True,
        )

    def _get_pandoc_version_cached(self) -> str:
        """Get cached Pandoc version or detect it."""
        if self._pandoc_version is None:
            self._pandoc_version = _get_pandoc_version()
        return self._pandoc_version
