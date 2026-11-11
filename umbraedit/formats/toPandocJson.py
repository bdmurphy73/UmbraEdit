"""
UmbraEdit - Pandoc JSON AST Tokenizer
======================================

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
import re
import subprocess
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.formats.tokenizer import Tokenizer
from umbraedit.formats.shared import BlockFmt, BlockTyp, T_Block, T_Formats, T_Note, TextFmt
from umbraedit.umbra.metadata import loadMetadata
from umbraedit.umbra.paths import assetsDir

if TYPE_CHECKING:  # pragma: no cover
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)

# Pandoc JSON AST types
PandocMeta = dict[str, Any]
PandocBlock = dict[str, Any]
PandocInline = dict[str, Any]


@dataclass
class PandocAST:
    """Pandoc JSON AST document."""
    meta: PandocMeta
    blocks: list[PandocBlock]


class ToPandocJson(Tokenizer):
    """Core: Pandoc JSON AST Writer.

    Extends the Tokenizer class to output Pandoc JSON AST (api-version
    of the installed Pandoc) from the same token stream as the other
    writers.
    """

    __slots__ = (
        "_project",
        "_pandoc_version",
        "_api_version",
        "_metadata",
    )

    def __init__(self, project: NWProject) -> None:
        super().__init__(project)
        self._project = project
        self._pandoc_version = ""
        self._api_version = ""
        self._metadata = loadMetadata(self._project.storage.storagePath)
        self._detect_pandoc_version()

    def _detect_pandoc_version(self) -> None:
        """Detect Pandoc version and API version."""
        try:
            result = subprocess.run(
                ["pandoc", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            lines = result.stdout.strip().split("\n")
            if lines:
                self._pandoc_version = lines[0].strip()
                # Extract version number
                version_match = re.search(r"pandoc\s+(\d+\.\d+\.\d+)", self._pandoc_version)
                if version_match:
                    version = version_match.group(1)
                    major, minor, patch = map(int, version.split("."))
                    # Pandoc API version follows major.minor
                    self._api_version = f"{major}.{minor}"
        except Exception as e:
            logger.warning("Failed to detect Pandoc version: %s", e)
            self._pandoc_version = "unknown"
            self._api_version = "1.23"  # Default fallback

    def _get_pandoc_api_version(self) -> str:
        """Return the Pandoc API version."""
        return self._api_version

    def _get_metadata(self) -> PandocMeta:
        """Build Pandoc metadata from project metadata."""
        meta = self._metadata
        pandoc_meta: PandocMeta = {}

        # Title
        if meta.book.get("title"):
            pandoc_meta["title"] = [{"t": "MetaInlines", "c": [{"t": "Str", "c": meta.book["title"]}]}]

        # Authors
        if meta.book.get("author"):
            authors = meta.book["author"].split(",")
            pandoc_meta["author"] = [
                {"t": "MetaInlines", "c": [{"t": "Str", "c": a.strip()}]}
                for a in authors if a.strip()
            ]

        # Language
        lang = meta.book.get("language", "en")
        pandoc_meta["lang"] = lang

        # Date
        if meta.book.get("date"):
            pandoc_meta["date"] = [{"t": "MetaInlines", "c": [{"t": "Str", "c": meta.book["date"]}]}]

        # Subjects/Keywords
        if meta.book.get("keywords"):
            keywords = [k.strip() for k in meta.book["keywords"].split(",") if k.strip()]
            if keywords:
                pandoc_meta["subject"] = [{"t": "MetaInlines", "c": [{"t": "Str", "c": k}]} for k in keywords]

        # Description
        if meta.book.get("description"):
            pandoc_meta["description"] = [{"t": "MetaInlines", "c": [{"t": "Str", "c": meta.book["description"]}]}]

        # ISBN
        if meta.book.get("isbn"):
            pandoc_meta["isbn"] = [{"t": "MetaInlines", "c": [{"t": "Str", "c": meta.book["isbn"]}]}]

        # Custom metadata
        for key, value in meta.custom.items():
            if value:
                pandoc_meta[key] = [{"t": "MetaInlines", "c": [{"t": "Str", "c": value}]}]

        return pandoc_meta

    def tokenizeText(self) -> None:
        """Override tokenizeText to build Pandoc JSON AST."""
        # First run the standard tokenization
        super().tokenizeText()

        # Convert blocks to Pandoc JSON AST
        blocks = self._blocks_to_pandoc()

        # Build final AST
        ast = PandocAST(
            meta=self._get_metadata(),
            blocks=blocks,
        )

        # Convert to JSON with Pandoc API version
        output = {
            "pandoc-api-version": [int(v) for v in self._api_version.split(".")],
            "meta": ast.meta,
            "blocks": ast.blocks,
        }

        # Write JSON output
        self._text = json.dumps(output, separators=(",", ":"), sort_keys=True, ensure_ascii=False)

    def _blocks_to_pandoc(self) -> list[PandocBlock]:
        """Convert internal blocks to Pandoc JSON AST blocks."""
        blocks: list[PandocBlock] = []

        for block in self._blocks:
            block_type = block[0]

            if block_type == BlockTyp.TITLE:
                blocks.append(self._title_to_pandoc(block[2]))
            elif block_type == BlockTyp.PART:
                blocks.append(self._heading_to_pandoc(block[2], 1))
            elif block_type == BlockTyp.HEAD1:
                blocks.append(self._heading_to_pandoc(block[2], 2))
            elif block_type == BlockTyp.HEAD2:
                blocks.append(self._heading_to_pandoc(block[2], 3))
            elif block_type == BlockTyp.HEAD3:
                blocks.append(self._heading_to_pandoc(block[2], 4))
            elif block_type == BlockTyp.HEAD4:
                blocks.append(self._heading_to_pandoc(block[2], 5))
            elif block_type == BlockTyp.SCENE_SEP:
                blocks.append({"t": "HorizontalRule", "c": [], "a": ["scene-break"]})
            elif block_type == BlockTyp.TEXT:
                blocks.extend(self._text_to_pandoc(block[2]))
            elif block_type == BlockTyp.LIST_U:
                blocks.append(self._list_to_pandoc(block[2], False))
            elif block_type == BlockTyp.LIST_O:
                blocks.append(self._list_to_pandoc(block[2], True))
            elif block_type == BlockTyp.FOOTNOTE:
                blocks.append(self._footnote_to_pandoc(block[2]))
            elif block_type == BlockTyp.COMMENT:
                # Skip comments in Pandoc output
                pass
            elif block_type == BlockTyp.NOTE:
                # Handle notes as footnotes or similar
                pass
            elif block_type == BlockTyp.IMG:
                blocks.append(self._image_to_pandoc(block[2]))
            elif block_type == BlockTyp.TABLE:
                blocks.append(self._table_to_pandoc(block[2]))
            elif block_type == BlockTyp.PAGE_BREAK:
                blocks.append({"t": "RawBlock", "c": ["openxml", '<w:p><w:r><w:br w:type="page"/></w:r></w:p>']})
            elif block_type == BlockTyp.HRULE:
                blocks.append({"t": "HorizontalRule", "c": []})

        return blocks

    def _inline_to_pandoc(self, text: str) -> list[PandocInline]:
        """Convert text with inline formatting to Pandoc inlines."""
        # This is a simplified version - real implementation would parse
        # the TextFmt markers and convert to Pandoc inlines
        # For now, return plain text
        if not text:
            return [{"t": "Str", "c": ""}]
        return [{"t": "Str", "c": text}]

    def _text_to_pandoc(self, text: str) -> list[PandocBlock]:
        """Convert plain text paragraph to Pandoc Para."""
        if not text.strip():
            return []
        inlines = self._inline_to_pandoc(text)
        return [{"t": "Para", "c": inlines}]

    def _title_to_pandoc(self, text: str) -> PandocBlock:
        """Convert title to Pandoc header level 1."""
        return {"t": "Header", "c": [1, [], self._inline_to_pandoc(text)]}

    def _heading_to_pandoc(self, text: str, level: int) -> PandocBlock:
        """Convert heading to Pandoc header."""
        return {"t": "Header", "c": [level, [], self._inline_to_pandoc(text)]}

    def _list_to_pandoc(self, items: list[str], ordered: bool) -> PandocBlock:
        """Convert list to Pandoc BulletList or OrderedList."""
        items_pandoc = []
        for item in items:
            items_pandoc.append([{"t": "Para", "c": self._inline_to_pandoc(item)}])
        if ordered:
            return {"t": "OrderedList", "c": [[1, "Decimal", "."], items_pandoc]}
        return {"t": "BulletList", "c": items_pandoc}

    def _footnote_to_pandoc(self, footnote: dict) -> PandocBlock:
        """Convert footnote to Pandoc Note."""
        # Simplified - would need proper footnote handling
        return {"t": "Note", "c": [{"t": "Para", "c": self._inline_to_pandoc(footnote.get("text", ""))}]}

    def _image_to_pandoc(self, image: dict) -> PandocBlock:
        """Convert image to Pandoc Figure."""
        src = image.get("src", "")
        alt = image.get("alt", "")
        return {"t": "Figure", "c": [[{"t": "Image", "c": [["", [], []], [alt, src]]}]]}

    def _table_to_pandoc(self, table: dict) -> PandocBlock:
        """Convert table to Pandoc Table."""
        # Simplified table conversion
        return {"t": "Table", "c": [[], [], [], []]}


def toPandocJson(project: "NWProject", output_path: Path | None = None) -> str:
    """Convert a project to Pandoc JSON AST.

    Args:
        project: The project to convert.
        output_path: Optional path to write JSON to. If None, returns string.

    Returns:
        JSON string of the Pandoc AST.
    """
    from umbraedit.formats.tokenizer import Tokenizer

    tokenizer = ToPandocJson(project)
    tokenizer.tokenizeText()
    json_output = tokenizer._text

    if output_path:
        output_path.write_text(json_output, encoding="utf-8")

    return json_output