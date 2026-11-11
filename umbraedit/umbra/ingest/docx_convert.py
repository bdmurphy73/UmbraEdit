"""
UmbraEdit - DOCX Convert Stage
===============================

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

import logging
import subprocess
import tempfile

from dataclasses import dataclass, field
from pathlib import Path

from umbraedit.umbra.ingest.docx_intake import IntakeResult
from umbraedit.umbra.ingest.docx_prepass import ParagraphRecord, PrepassResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConvertResult:
    """Result of the convert stage."""

    markdown: str
    pandoc_paragraphs: list[str]  # Raw Pandoc output paragraphs
    media_dir: Path | None = None
    warnings: list[str] = field(default_factory=list)


class DocxConvert:
    """Convert stage: run Pandoc to get Markdown, map to pre-pass paragraphs."""

    def __init__(self) -> None:
        self._media_dir: Path | None = None

    def process(
        self,
        intake: IntakeResult,
        prepass: PrepassResult,
        output_dir: Path | None = None,
    ) -> ConvertResult:
        """Run Pandoc and map output to pre-pass paragraphs."""
        logger.info("Convert: running Pandoc on %s", intake.file_path)

        # Create media extraction directory
        if output_dir:
            self._media_dir = output_dir / "media"
        else:
            self._media_dir = Path(tempfile.mkdtemp(prefix="umbra-ingest-media-"))
        self._media_dir.mkdir(parents=True, exist_ok=True)

        # Run Pandoc
        markdown, warnings = self._run_pandoc(intake.file_path)

        # Split markdown into paragraphs
        pandoc_paragraphs = self._split_markdown_paragraphs(markdown)

        # Map Pandoc paragraphs to pre-pass records
        mapped = self._map_paragraphs(prepass.paragraphs, pandoc_paragraphs)

        return ConvertResult(
            markdown=markdown,
            pandoc_paragraphs=pandoc_paragraphs,
            media_dir=self._media_dir,
            warnings=warnings,
        )

    def _run_pandoc(self, file_path: Path) -> tuple[str, list[str]]:
        """Run Pandoc on the DOCX file."""
        warnings: list[str] = []

        cmd = [
            "pandoc",
            "--from", "docx",
            "--to", "markdown",
            "--wrap=none",
            f"--extract-media={self._media_dir}",
            "--track-changes=accept",
            str(file_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
            markdown = result.stdout
            if result.stderr:
                for line in result.stderr.strip().split("\n"):
                    if line.strip():
                        warnings.append(f"Pandoc: {line.strip()}")
        except subprocess.TimeoutExpired:
            warnings.append("Pandoc timed out after 300 seconds")
            markdown = ""
        except subprocess.CalledProcessError as e:
            warnings.append(f"Pandoc failed with exit code {e.returncode}: {e.stderr}")
            markdown = ""
        except FileNotFoundError:
            warnings.append("Pandoc not found in PATH")
            markdown = ""

        return markdown, warnings

    def _split_markdown_paragraphs(self, markdown: str) -> list[str]:
        """Split markdown into logical paragraphs."""
        # Split by blank lines, but keep headings with their content
        paragraphs: list[str] = []
        current: list[str] = []

        for line in markdown.split("\n"):
            stripped = line.strip()

            # Heading starts a new paragraph
            if stripped.startswith("#"):
                if current:
                    paragraphs.append("\n".join(current).strip())
                    current = []
                current.append(line)
            elif not stripped:
                # Blank line - end current paragraph if not empty
                if current:
                    paragraphs.append("\n".join(current).strip())
                    current = []
            else:
                current.append(line)

        if current:
            paragraphs.append("\n".join(current).strip())

        return paragraphs

    def _map_paragraphs(
        self,
        prepass_paras: list[ParagraphRecord],
        pandoc_paras: list[str],
    ) -> list[tuple[ParagraphRecord, str | None]]:
        """Map pre-pass paragraphs to Pandoc output by order and text similarity."""
        mapped: list[tuple[ParagraphRecord, str | None]] = []

        # Simple mapping by index - assumes same order
        # In production, this could use fuzzy matching for robustness
        for i, prepass_para in enumerate(prepass_paras):
            if i < len(pandoc_paras):
                mapped.append((prepass_para, pandoc_paras[i]))
            else:
                mapped.append((prepass_para, None))

        return mapped
