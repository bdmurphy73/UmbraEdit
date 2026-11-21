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
import subprocess

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from umbraedit.formats.shared import BlockTyp, TextFmt
from umbraedit.formats.tokenizer import Tokenizer
from umbraedit.umbra.metadata import Metadata, loadMetadata

if TYPE_CHECKING:  # pragma: no cover
    from pathlib import Path

    from umbraedit.core.project import NWProject
    from umbraedit.formats.shared import T_Formats

logger = logging.getLogger(__name__)

# Pandoc JSON AST types
PandocMeta = dict[str, Any]
PandocBlock = dict[str, Any]
PandocInline = dict[str, Any]

# Inline format codes mapped to Pandoc node kinds
PANDOC_OPENER: dict[TextFmt, str] = {
    TextFmt.B_B: "strong",
    TextFmt.I_B: "emph",
    TextFmt.D_B: "strike",
    TextFmt.U_B: "underline",
    TextFmt.SUP_B: "superscript",
    TextFmt.SUB_B: "subscript",
    TextFmt.M_B: "span",
    TextFmt.COL_B: "span",
    TextFmt.ANM_B: "anchor",
    TextFmt.ARF_B: "anchor",
    TextFmt.HRF_B: "link",
}

PANDOC_CLOSER: dict[TextFmt, str] = {
    TextFmt.B_E: "strong",
    TextFmt.I_E: "emph",
    TextFmt.D_E: "strike",
    TextFmt.U_E: "underline",
    TextFmt.SUP_E: "superscript",
    TextFmt.SUB_E: "subscript",
    TextFmt.M_E: "span",
    TextFmt.COL_E: "span",
    TextFmt.ARF_E: "anchor",
    TextFmt.HRF_E: "link",
}


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
        "_api_version",
        "_metadata",
        "_pandocBlocks",
        "_pandoc_version",
        "_project",
    )

    def __init__(self, project: NWProject) -> None:
        super().__init__(project)
        self._project = project
        self._pandoc_version = ""
        self._api_version = ""
        self._pandocBlocks: list[PandocBlock] = []
        storagePath = self._project.storage.storagePath
        self._metadata = loadMetadata(storagePath) if storagePath else Metadata()
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
        except Exception as e:
            logger.warning("Failed to detect Pandoc version: %s", e)
            self._pandoc_version = "unknown"

        # Ask Pandoc itself for the JSON AST API version. This is the
        # only reliable way to get the exact version, as it is not the
        # same as the Pandoc release version.
        try:
            probe = subprocess.run(
                ["pandoc", "--from=markdown", "--to=json"],
                input="",
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            version = json.loads(probe.stdout).get("pandoc-api-version", [])
            if version:
                self._api_version = ".".join(str(v) for v in version)
        except Exception as e:
            logger.warning("Failed to detect Pandoc API version: %s", e)
            if not self._api_version:
                self._api_version = "1.23"  # Default fallback

    def _get_pandoc_api_version(self) -> str:
        """Return the Pandoc API version."""
        return self._api_version

    def _get_metadata(self) -> PandocMeta:
        """Build Pandoc metadata from project metadata."""
        meta = self._metadata
        pandoc_meta: PandocMeta = {}

        def metaString(value: str) -> PandocMeta:
            """Return a Pandoc MetaInlines object for a string."""
            return {"t": "MetaInlines", "c": [{"t": "Str", "c": value}]}

        # Title
        if meta.book.get("title"):
            pandoc_meta["title"] = metaString(meta.book["title"])

        # Authors
        if meta.book.get("author"):
            authors = meta.book["author"].split(",")
            pandoc_meta["author"] = [
                {"t": "MetaInlines", "c": [{"t": "Str", "c": a.strip()}]} for a in authors if a.strip()
            ]

        # Language
        lang = meta.book.get("language", "en")
        pandoc_meta["lang"] = metaString(lang)

        # Date
        if meta.book.get("date"):
            pandoc_meta["date"] = metaString(meta.book["date"])

        # Subjects/Keywords
        if meta.book.get("keywords"):
            keywords = [k.strip() for k in meta.book["keywords"].split(",") if k.strip()]
            if keywords:
                pandoc_meta["subject"] = [{"t": "MetaInlines", "c": [{"t": "Str", "c": k}]} for k in keywords]

        # Description
        if meta.book.get("description"):
            pandoc_meta["description"] = metaString(meta.book["description"])

        # ISBN
        if meta.book.get("isbn"):
            pandoc_meta["isbn"] = metaString(meta.book["isbn"])

        # Custom metadata
        for key, value in meta.custom.items():
            if value:
                pandoc_meta[key] = metaString(value)

        return pandoc_meta

    ##
    #  Class Methods
    ##

    def tokenizeText(self) -> None:
        """Tokenise the current document.

        The Pandoc blocks are generated in ``doConvert()`` so that they
        are built in the same way as for the other document writers.
        """
        super().tokenizeText()

    def doConvert(self) -> None:
        """Convert the blocks of the current document to Pandoc JSON."""
        self._pandocBlocks.extend(self._blocks_to_pandoc())

    def closeDocument(self) -> None:
        """Run close document tasks. There is nothing to close."""

    def saveDocument(self, path: Path) -> None:
        """Save the Pandoc JSON AST to a file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.getJson(), encoding="utf-8")
        logger.info("Wrote file: %s", path)

    ##
    #  Internal Functions
    ##

    def getJson(self) -> str:
        """Return the Pandoc JSON AST of the manuscript."""
        ast = PandocAST(
            meta=self._get_metadata(),
            blocks=self._pandocBlocks,
        )
        output = {
            "pandoc-api-version": [int(v) for v in self._api_version.split(".")],
            "meta": ast.meta,
            "blocks": ast.blocks,
        }
        return json.dumps(output, separators=(",", ":"), sort_keys=True, ensure_ascii=False)

    def _blocks_to_pandoc(self) -> list[PandocBlock]:
        """Convert internal blocks to Pandoc JSON AST blocks."""
        blocks: list[PandocBlock] = []
        items: list[list[PandocBlock]] = []
        ordered = False

        for tType, _, tText, tFormat, _tStyle in self._blocks:
            if tType in (BlockTyp.LIST_U, BlockTyp.LIST_O):
                isOrdered = tType == BlockTyp.LIST_O
                if items and ordered != isOrdered:
                    blocks.append(self._list_block(items, ordered))
                    items = []
                ordered = isOrdered
                items.append([{"t": "Plain", "c": self._inline_to_pandoc(tText, tFormat)}])
                continue

            if items:
                blocks.append(self._list_block(items, ordered))
                items = []
                ordered = False

            if tType == BlockTyp.TITLE:
                blocks.append(self._heading_to_pandoc(tText, tFormat, 1))

            elif tType == BlockTyp.PART:
                blocks.append(self._heading_to_pandoc(tText, tFormat, 1))

            elif tType == BlockTyp.HEAD1:
                blocks.append(self._heading_to_pandoc(tText, tFormat, 2))

            elif tType == BlockTyp.HEAD2:
                blocks.append(self._heading_to_pandoc(tText, tFormat, 3))

            elif tType == BlockTyp.HEAD3:
                blocks.append(self._heading_to_pandoc(tText, tFormat, 4))

            elif tType == BlockTyp.HEAD4:
                blocks.append(self._heading_to_pandoc(tText, tFormat, 5))

            elif tType == BlockTyp.SEP:
                blocks.append({"t": "HorizontalRule", "c": []})

            elif tType == BlockTyp.HRULE:
                blocks.append({"t": "HorizontalRule", "c": []})

            elif tType == BlockTyp.TEXT:
                blocks.extend(self._text_to_pandoc(tText, tFormat))

            elif tType == BlockTyp.KEYWORD:
                blocks.append({"t": "Para", "c": self._inline_to_pandoc(tText, tFormat)})

            elif tType in (BlockTyp.SUMMARY, BlockTyp.NOTE, BlockTyp.COMMENT):
                # Comments and notes are not included in the manuscript
                pass

            else:  # pragma: no cover
                pass

        if items:
            blocks.append(self._list_block(items, ordered))

        return blocks

    def _list_block(self, items: list[list[PandocBlock]], ordered: bool) -> PandocBlock:
        """Build a Pandoc list block from a list of items."""
        if ordered:
            return {"t": "OrderedList", "c": [[1, "Decimal", "."], items]}
        return {"t": "BulletList", "c": items}

    def _inline_to_pandoc(self, text: str, tFmt: T_Formats) -> list[PandocInline]:
        """Convert text with inline formatting to Pandoc inlines."""
        result: list[PandocInline] = []
        stack: list[dict[str, Any]] = [{"kind": "root", "items": result, "data": ""}]
        pos = 0

        for ePos, fmt, data in tFmt:
            if ePos > pos:
                chunk = text[pos:ePos]
                if chunk:
                    stack[-1]["items"].append({"t": "Str", "c": chunk})
                pos = ePos

            if kind := PANDOC_OPENER.get(fmt):
                stack.append({"kind": kind, "items": [], "data": data})
                continue

            if kind := PANDOC_CLOSER.get(fmt):
                if len(stack) > 1:
                    entry = stack.pop()
                    stack[-1]["items"].append(self._pandocNode(entry))
                continue

            if fmt == TextFmt.FNOTE:
                if data in self._footnotes:
                    note = self._footnotes[data]
                    blocks = [{"t": "Para", "c": self._inline_to_pandoc(note[0], note[1])}]
                    stack[-1]["items"].append({"t": "Note", "c": blocks})
                else:
                    stack[-1]["items"].append({"t": "Note", "c": [{"t": "Para", "c": [{"t": "Str", "c": "ERR"}]}]})
                continue

            if fmt == TextFmt.FIELD:
                continue

            if fmt == TextFmt.STRIP:
                continue

            if fmt in (TextFmt.ERR_B, TextFmt.ERR_E):
                continue

        if pos < len(text):
            chunk = text[pos:]
            if chunk:
                stack[-1]["items"].append({"t": "Str", "c": chunk})

        return result

    def _pandocNode(self, entry: dict[str, Any]) -> PandocInline:
        """Build a Pandoc inline node from a format stack entry."""
        kind = entry["kind"]
        inner = entry["items"]
        data = entry["data"]
        if kind == "strong":
            return {"t": "Strong", "c": inner}
        if kind == "emph":
            return {"t": "Emph", "c": inner}
        if kind == "strike":
            return {"t": "Strikeout", "c": inner}
        if kind == "underline":
            return {"t": "Underline", "c": inner}
        if kind == "superscript":
            return {"t": "Superscript", "c": inner}
        if kind == "subscript":
            return {"t": "Subscript", "c": inner}
        if kind == "anchor":
            target = data if data.startswith("#") else f"#{data}"
            return {"t": "Link", "c": [[["", [], []], inner, target]]}
        if kind == "link":
            return {"t": "Link", "c": [[["", [], []], inner, data]]}
        return {"t": "Span", "c": [["", [], []], inner, []]}

    def _text_to_pandoc(self, text: str, tFmt: T_Formats) -> list[PandocBlock]:
        """Convert a plain text paragraph to Pandoc Para."""
        if not text.strip():
            return []
        inlines = self._inline_to_pandoc(text, tFmt)
        return [{"t": "Para", "c": inlines}]

    def _heading_to_pandoc(self, text: str, tFmt: T_Formats, level: int) -> PandocBlock:
        """Convert a heading to a Pandoc header."""
        return {"t": "Header", "c": [level, ["", [], []], self._inline_to_pandoc(text, tFmt)]}


def toPandocJson(project: NWProject, output_path: Optional[Path] = None) -> str:
    """Convert a project to Pandoc JSON AST.

    Args:
        project: The project to convert.
        output_path: Optional path to write JSON to. If None, returns string.

    Returns:
        JSON string of the Pandoc AST.

    """
    from umbraedit.enum import nwItemLayout

    tokenizer = ToPandocJson(project)
    tokenizer.initDocument()
    for item in project.tree:
        if item.isFileType() and item.itemLayout == nwItemLayout.DOCUMENT:
            tokenizer.setText(item.itemHandle)
            tokenizer.tokenizeText()
            tokenizer.doConvert()
    tokenizer.closeDocument()

    json_output = tokenizer.getJson()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_output, encoding="utf-8")

    return json_output
