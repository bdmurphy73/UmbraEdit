"""
UmbraEdit - Pandoc EPUB Validator
=================================

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

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.formats.toPandocJson import toPandocJson
from umbraedit.umbra.metadata import loadMetadata

if TYPE_CHECKING:  # pragma: no cover
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)


@dataclass
class EpubValidationResult:
    """Result of EPUB validation."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    epub_path: str | None = None


def _find_epubcheck() -> str | None:
    """Find EPUBCheck JAR file."""
    # Check common locations
    locations = [
        Path("/usr/share/java/epubcheck.jar"),
        Path("/opt/epubcheck/epubcheck.jar"),
        Path.home() / ".local/share/epubcheck/epubcheck.jar",
        Path("/opt/homebrew/Cellar/epubcheck") / "libexec" / "epubcheck.jar",
    ]
    for loc in locations:
        if loc.exists():
            return str(loc)
    return None


def _check_java_available() -> bool:
    """Check if Java is available."""
    try:
        subprocess.run(["java", "-version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


def validate_epub(epub_path: Path, epubcheck_jar: str | None = None) -> tuple[bool, list[str], list[str]]:
    """Validate an EPUB file using EPUBCheck.

    Args:
        epub_path: Path to the EPUB file.
        epubcheck_jar: Optional path to EPUBCheck JAR. If None, tries to find it.

    Returns:
        Tuple of (is_valid, errors, warnings).
    """
    if not epub_path.is_file():
        return False, [f"EPUB file not found: {epub_path}"], []

    if not _check_java_available():
        return False, ["Java runtime not found. EPUBCheck requires Java."], []

    epubcheck_jar = epubcheck_jar or _find_epubcheck()
    if not epubcheck_jar:
        return False, ["EPUBCheck not found. Install epubcheck or set EPUBCHECK_JAR env var."], []

    try:
        result = subprocess.run(
            ["java", "-jar", epubcheck_jar, str(epub_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        errors = []
        warnings = []
        for line in result.stderr.splitlines():
            line = line.strip()
            if "ERROR" in line.upper():
                errors.append(line)
            elif "WARNING" in line.upper():
                warnings.append(line)
            elif "ERROR" in line.upper():
                errors.append(line)

        return result.returncode == 0, errors, warnings

    except subprocess.TimeoutExpired:
        return False, ["EPUBCheck timed out"], []
    except Exception as e:
        logger.exception("EPUBCheck failed")
        return False, [f"EPUBCheck failed: {e}"], []


def _find_epubcheck() -> str | None:
    """Find EPUBCheck JAR file."""
    # Check common locations
    locations = [
        Path("/usr/share/java/epubcheck.jar"),
        Path("/opt/epubcheck/epubcheck.jar"),
        Path.home() / ".local/share/epubcheck/epubcheck.jar",
        Path("/opt/homebrew/Cellar/epubcheck") / "libexec" / "epubcheck.jar",
    ]
    for loc in locations:
        if loc.exists():
            return str(loc)
    return None


def _check_java_available() -> bool:
    """Check if Java is available."""
    try:
        subprocess.run(["java", "-version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


def _check_epubcheck_available() -> bool:
    """Check if EPUBCheck is available."""
    return _find_epubcheck() is not None and _check_java_available()


def build_epub_with_pandoc(
    project: "NWProject",
    output_path: Path,
    pandoc_args: list[str] | None = None,
) -> tuple[bool, str]:
    """Build EPUB from project using Pandoc.

    Args:
        project: The project to convert.
        output_path: Path to write EPUB to.
        pandoc_args: Additional Pandoc arguments.

    Returns:
        Tuple of (success, output_path_or_error).
    """
    from umbraedit.formats.toPandocJson import toPandocJson

    try:
        # Generate Pandoc JSON
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            json_path = tmpdir_path / "manuscript.json"

            # Generate Pandoc JSON
            json_output = toPandocJson(project, json_path)

            # Build Pandoc command
            cmd = [
                "pandoc",
                str(json_path),
                "-o", str(output_path),
                "--from=json",
                "--to=epub3",
            ]

            # Add cover image if available
            # TODO: Get cover from project metadata
            # cmd.extend(["--cover-image", cover_path])

            # Add metadata
            # Pandoc reads metadata from JSON

            # Add CSS
            css_path = Path(__file__).parent.parent / "styles" / "epub.css"
            if css_path.exists():
                cmd.extend(["--css", str(css_path)])

            # Add any extra args
            if pandoc_args:
                cmd.extend(pandoc_args)

            # Run Pandoc
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode != 0:
                return False, f"Pandoc failed: {result.stderr}"

            # Verify EPUB was created
            if not output_path.exists():
                return False, "EPUB file was not created"

            return True, str(output_path)

    except subprocess.TimeoutExpired:
        return False, "Pandoc timed out"
    except Exception as e:
        logger.exception("Pandoc EPUB generation failed")
        return False, f"Pandoc failed: {e}"


def build_epub_validated(
    project: "NWProject",
    output_path: Path,
    epubcheck_jar: str | None = None,
) -> tuple[bool, str]:
    """Build EPUB with Pandoc and validate with EPUBCheck.

    Args:
        project: The project to convert.
        output_path: Path to write EPUB to.
        epubcheck_jar: Optional path to EPUBCheck JAR.

    Returns:
        Tuple of (success, output_path_or_error).
    """
    # Build EPUB with Pandoc
    success, result = build_epub_with_pandoc(project, output_path)
    if not success:
        return False, result

    epub_path = Path(result)

    # Validate with EPUBCheck
    is_valid, errors, warnings = validate_epub(epub_path, epubcheck_jar)
    if not is_valid:
        # Remove invalid EPUB
        try:
            epub_path.unlink()
        except Exception:
            pass
        return False, f"EPUBCheck validation failed: {'; '.join(errors)}"

    logger.info("EPUB validated successfully: %s", output_path)
    return True, str(output_path)