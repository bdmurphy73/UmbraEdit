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

import json
import logging
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.formats.tokenizer import Tokenizer
from umbraedit.umbra.edition import EditionDoc, EditionInfo, loadEdition, saveEdition
from umbraedit.umbra.guide import parseGuideDoc
from umbraedit.umbra.paths import jobsDir, promptsDir
from umbraedit.umbra.settings import umbraSettings
from umbraedit.umbra.units import UnitKind, iterUnits

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def toPandocJson(project: "NWProject", output_path: Path | None = None) -> str:
    """Convert a project to Pandoc JSON AST.

    Args:
        project: The project to convert.
        output_path: Optional path to write JSON to.

    Returns:
        The Pandoc JSON AST as a string.
    """
    tokenizer = ToPandocJson(project)
    tokenizer.tokenizeText()
    json_ast = tokenizer.to_json()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_ast, encoding="utf-8")

    return json_ast


class ToPandocJson(Tokenizer):
    """Core: Pandoc JSON AST Writer.

    Converts the manuscript to Pandoc's JSON AST format.
    """

    __slots__ = (
        "_project",
        "_metadata",
        "_blocks",
    )

    def __init__(self, project: "NWProject") -> None:
        super().__init__(project)
        self._project = project
        self._metadata = project.metadata if hasattr(project, "metadata") else None

    def tokenizeText(self) -> None:
        """Override tokenizeText to build Pandoc JSON."""
        super().tokenizeText()

    def to_json(self) -> str:
        """Convert internal blocks to Pandoc JSON AST."""
        # Build Pandoc document structure
        doc = {
            "pandoc-api-version": [1, 23, 1],
            "meta": self._build_meta(),
            "blocks": self._blocks_to_pandoc(),
        }
        return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))

    def _build_meta(self) -> dict[str, Any]:
        """Build Pandoc metadata."""
        meta = {}
        if self._metadata:
            book = self._metadata.book
            for key, value in book.items():
                if value:
                    meta[key] = {"t": "MetaString", "c": str(value)}
        return meta

    def _blocks_to_pandoc(self) -> list[dict[str, Any]]:
        """Convert internal blocks to Pandoc blocks."""
        blocks = []

        for block in self._blocks:
            block_type = block[0]

            if block_type == 1:  # TITLE
                blocks.append({"t": "Header", "c": [1, ["", [], []], [{"t": "Str", "c": block[2]}]]})
            elif block_type == 2:  # PART
                blocks.append({"t": "Header", "c": [1, ["", [], []], [{"t": "Str", "c": block[2]}]]})
            elif block_type in (3, 4, 5, 6):  # HEAD1-4
                level = block_type - 3 + 2  # HEAD1 -> level 2
                blocks.append({"t": "Header", "c": [level, ["", [], []], [{"t": "Str", "c": block[2]}]]})
            elif block_type == 7:  # SCENE_SEP
                blocks.append({"t": "HorizontalRule", "c": []})
            elif block_type == 8:  # TEXT
                blocks.append(self._inline_to_pandoc(block[2]))
            elif block_type == 9:  # LIST_U
                blocks.append(self._list_to_pandoc(block[2], False))
            elif block_type == 10:  # LIST_O
                blocks.append(self._list_to_pandoc(block[2], True))
            elif block_type == 11:  # FOOTNOTE
                blocks.append(self._footnote_to_pandoc(block[2]))
            elif block_type == 12:  # IMG
                blocks.append(self._image_to_pandoc(block[2]))
            elif block_type == 13:  # TABLE
                blocks.append(self._table_to_pandoc(block[2]))
            elif block_type == 14:  # PAGE_BREAK
                blocks.append({"t": "RawBlock", "c": ["latex", "\\newpage"]})

        return blocks

    def _inline_to_pandoc(self, text: str) -> dict[str, Any]:
        """Convert inline formatting to Pandoc inlines."""
        # Simple conversion - split by formatting markers
        inlines = []
        # This is a simplified version
        inlines.append({"t": "Str", "c": text})
        return {"t": "Para", "c": inlines}

    def _list_to_pandoc(self, items: list, ordered: bool) -> dict[str, Any]:
        """Convert list to Pandoc list."""
        pandoc_items = []
        for item in items:
            pandoc_items.append([{"t": "Plain", "c": [{"t": "Str", "c": item}]}])
        return {"t": "OrderedList" if ordered else "BulletList", "c": pandoc_items}

    def _footnote_to_pandoc(self, footnote: dict) -> dict[str, Any]:
        """Convert footnote to Pandoc footnote."""
        return {"t": "Note", "c": [{"t": "Plain", "c": [{"t": "Str", "c": footnote.get("text", "")}]}]}

    def _image_to_pandoc(self, image: dict) -> dict[str, Any]:
        """Convert image to Pandoc image."""
        return {"t": "Image", "c": [["", [], []], [], [image.get("filename", ""), image.get("alt", "")]]}

    def _table_to_pandoc(self, table: dict) -> dict[str, Any]:
        """Convert table to Pandoc table."""
        return {"t": "Table", "c": [[], [], [], [], []]}


if __name__ == "__main__":
    pass