"""
UmbraEdit - Typst Print PDF Formatter
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.formats.tokenizer import Tokenizer
from umbraedit.formats.shared import BlockFmt, BlockTyp, T_Block, T_Formats, T_Note, TextFmt
from umbraedit.umbra.metadata import loadMetadata
from umbraedit.umbra.paths import assetsDir

if TYPE_CHECKING:  # pragma: no cover
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)

# Default Typst template for print
DEFAULT_TYPST_TEMPLATE = r"""
#import "@preview/page-numbering:0.1.0" as pn
#import "@preview/footnotes:0.1.0" as ft

// Configuration
#let trim-size = ({{trim_width}}, {{trim_height}})
#let gutter = {{gutter}}
#let margin-inner = {{margin_inner}}
#let margin-outer = {{margin_outer}}
#let margin-top = {{margin_top}}
#let margin-bottom = {{margin_bottom}}
#let font-family = "{{font_family}}"
#let font-size = {{font_size}}pt
#let line-height = {{line_height}}
#let hyphenation-lang = "{{hyphenation_lang}}"
#let running-headers = {{running_headers}}

// Page setup
#set page(
  paper: (trim-size.x + 2 * gutter, trim-size.y),
  margin: (margin-top, margin-inner + gutter, margin-bottom, margin-outer + gutter),
  footer: if running-headers {
    context pn.get-page-info().number != 0 => [
      #if pn.get-page-info().number % 2 == 0 {
        #align(center)[#pn.get-page-info().number] #h(1fr) #context header.left
      } else {
        #context header.right #h(1fr) #align(center)[#pn.get-page-info().number]
      }
    ]
  } else { none }
)

// Typography
#set text(font: font-family, size: font-size, lang: hyphenation-lang)
#set par(justify: true, first-line-indent: 1.5em, leading: line-height)
#set page(numbering: "1", number-align: center)
#set heading(numbering: "1.1", outlined: true)
#set heading(outline: (depth: 3))

// Font setup
#let font-family = (
  "{{font_family}}",
  fallback: ("DejaVu Serif", "Liberation Serif", "Noto Serif", "Times New Roman", "serif")
)

// Chapter openings on recto (odd pages)
#let chapter-break = {
  #if context.page() % 2 == 0 { pagebreak() }
  pagebreak(to: "odd")
  set page(numbering: "1", number-align: center)
}

// Front matter roman numerals
#let front-matter = {
  set page(numbering: "(i)", number-align: center)
}

// Chapter openings on recto with drop distance
#show heading.where(level: 1): it => {
  #if !context("first-chapter").or(false) {
    pagebreak(to: "odd")
  }
  context first-chapter = true
  set block(below: 2.5em)
  it
}

// Scene break ornament
#show raw.where(block: true): it => {
  if it.text == "***" or it.text == "---" or it.text == "###" {
    #align(center)[#text(size: 1.5em)[***]]
  } else { it }
}

// Page break as raw block with class
#show raw.where(block: true): it => {
  if it.text.contains("pagebreak") {
    pagebreak()
  } else { it }
}

// Footnotes
#show ft.note: it => ft.note(it)

// Embedded fonts (OFL)
{% for font in embedded_fonts %}
#let {{font.family | replace(" ", "_") | replace("-", "_")}} = @font("{{font.path}}")
{% endfor %}

// Main content
{{content}}
"""

@dataclass
class TypstConfig:
    """Configuration for Typst output."""
    trim_width: str = "152mm"  # 6x9 inches
    trim_height: str = "229mm"
    gutter: str = "6mm"
    margin_inner: str = "15mm"
    margin_outer: str = "15mm"
    margin_top: str = "20mm"
    margin_bottom: str = "20mm"
    font_family: str = "Libertinus Serif"
    font_size: int = 11
    line_height: float = 1.25
    hyphenation_lang: str = "en-US"
    running_headers: bool = True
    embedded_fonts: list[dict] = field(default_factory=list)


class ToTypst(Tokenizer):
    """Core: Typst Print PDF Writer.

    Converts the manuscript to Typst source, compiles with Typst,
    and produces a print-ready PDF.
    """

    __slots__ = (
        "_project",
        "_config",
        "_template",
        "_metadata",
        "_assets_dir",
    )

    def __init__(self, project: "NWProject", config: TypstConfig | None = None) -> None:
        super().__init__(project)
        self._project = project
        self._config = config or TypstConfig()
        self._metadata = loadMetadata(self._project.storage.storagePath)
        self._assets_dir = assetsDir(self._project.storage.storagePath)
        self._template = self._load_template()

    def _load_template(self) -> str:
        """Load Typst template from project or use default."""
        template_path = self._project.storage.storagePath / "umbra" / "templates" / "print.typ"
        if template_path.is_file():
            try:
                return template_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to load custom template: %s", e)
        return DEFAULT_TYPST_TEMPLATE

    def _get_metadata(self) -> dict[str, Any]:
        """Extract metadata for template."""
        meta = self._metadata
        return {
            "title": meta.book.get("title", ""),
            "author": meta.book.get("author", ""),
            "language": meta.book.get("language", "en"),
            "isbn": meta.book.get("isbn", ""),
        }

    def _build_typst_config(self) -> dict[str, Any]:
        """Build configuration dictionary for template."""
        meta = self._metadata
        cfg = self._config

        # Get trim size from edition metadata
        trim_size = "152mm x 229mm"  # 6x9 inches default
        if meta.book.get("trim_size"):
            trim_size = meta.book["trim_size"]

        width, height = "152mm", "229mm"
        if "x" in trim_size:
            parts = trim_size.split("x")
            width = parts[0].strip() + "mm"
            height = parts[1].strip() + "mm"
        else:
            width, height = "152mm", "229mm"

        # Get edition-specific margins
        gutter = cfg.gutter
        margin_inner = cfg.margin_inner
        margin_outer = cfg.margin_outer

        # Get font configuration
        font_family = cfg.font_family
        if meta.book.get("font_family"):
            font_family = meta.book["font_family"]

        # Get embedded fonts from assets
        embedded_fonts = []
        assets_dir = assetsDir(self._project.storage.storagePath)
        for asset_file in assets_dir.glob("*.otf"):
            try:
                # Could parse font metadata here
                pass
            except Exception:
                pass

        return {
            "trim_width": width,
            "trim_height": height,
            "gutter": gutter,
            "margin_inner": margin_inner,
            "margin_outer": margin_outer,
            "margin_top": cfg.margin_top,
            "margin_bottom": cfg.margin_bottom,
            "font_family": font_family,
            "font_size": cfg.font_size,
            "line_height": cfg.line_height,
            "hyphenation_lang": cfg.hyphenation_lang,
            "running_headers": str(cfg.running_headers).lower(),
            "embedded_fonts": embedded_fonts,
            "content": "",  # Will be filled in
        }

    def tokenizeText(self) -> None:
        """Override tokenizeText to build Typst source."""
        super().tokenizeText()

        # Build Typst source from blocks
        typst_source = self._blocks_to_typst()

        # Get template and render
        config = self._build_typst_config()
        config["content"] = typst_source

        # Render template
        from string import Template
        template = Template(self._template)
        typst_source = template.safe_substitute(config)

        # Write Typst source to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".typ", delete=False, encoding="utf-8") as f:
            f.write(typst_source)
            typst_path = f.name

        # Compile with Typst
        pdf_path = self._compile_typst(typst_path)

        # Copy PDF to output
        if hasattr(self, "_output_path") and self._output_path:
            import shutil
            shutil.copy2(pdf_path, self._output_path)

        # Clean up
        os.unlink(typst_path)
        os.unlink(pdf_path)

    def _blocks_to_typst(self) -> str:
        """Convert internal blocks to Typst source."""
        lines: list[str] = []

        for block in self._blocks:
            block_type = block[0]

            if block_type == BlockTyp.TITLE:
                lines.append(f"#title[{block[2]}]")
            elif block_type == BlockTyp.PART:
                lines.append(f"#part[{block[2]}]")
            elif block_type in (BlockTyp.HEAD1, BlockTyp.HEAD2, BlockTyp.HEAD3, BlockTyp.HEAD4):
                level = block[0] - BlockTyp.HEAD1 + 1
                lines.append(f"{'#' * (level + 1)} {block[2]}")
            elif block_type == BlockTyp.SCENE_SEP:
                lines.append("***")
            elif block_type == BlockTyp.TEXT:
                lines.append(self._inline_to_typst(block[2]))
            elif block_type == BlockTyp.SCENE_SEP:
                lines.append("***")
            elif block_type == BlockTyp.LIST_U:
                lines.append(self._list_to_typst(block[2], False))
            elif block_type == BlockTyp.LIST_O:
                lines.append(self._list_to_typst(block[2], True))
            elif block_type == BlockTyp.FOOTNOTE:
                lines.append(self._footnote_to_typst(block[2]))
            elif block_type == BlockTyp.IMG:
                lines.append(self._image_to_typst(block[2]))
            elif block_type == BlockTyp.TABLE:
                lines.append(self._table_to_typst(block[2]))
            elif block_type == BlockTyp.PAGE_BREAK:
                lines.append("#pagebreak()")

        return "\n\n".join(lines)

    def _inline_to_typst(self, text: str) -> str:
        """Convert inline formatting to Typst markup."""
        # Convert markdown-style formatting to Typst
        text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)  # Bold
        text = re.sub(r"__(.+?)__", r"_\1_", text)  # Italic
        text = re.sub(r"~~(.+?)~~", r"~~\1~~", text)  # Strikethrough
        text = re.sub(r"==(.+?)==", r"`\1`", text)  # Highlight/Mark
        return text

    def _convert_footnotes(self, text: str, footnotes: dict[str, str]) -> str:
        """Convert [FOOTNOTE:id] markers to Typst footnote syntax."""
        def replace_fn(match: re.Match) -> str:
            fn_id = match.group(1)
            fn_text = footnotes.get(fn_id, f"[footnote {fn_id} not found]")
            return f"#footnote[{fn_id}]\n%Footnote.{fn_id}: {fn_text}"

        return re.sub(r"\[FOOTNOTE:([^\]]+)\]", replace_fn, text)

    def _convert_comments(self, text: str, comments: dict[str, dict[str, Any]]) -> str:
        """Convert [COMMENT:id] markers to comment lines."""
        def replace_cmt(match: re.Match) -> str:
            cmt_id = match.group(1)
            cmt = comments.get(cmt_id, {})
            author = cmt.get("author", "Unknown")
            cmt_text = cmt.get("text", "")
            return f"% {author}: {cmt_text}"

        return re.sub(r"\[COMMENT:([^\]]+)\]", replace_cmt, text)

    def _convert_images(self, text: str, images: list[dict[str, Any]]) -> str:
        """Convert [IMAGE:rid] markers to [image:...] lines."""
        def replace_img(match: re.Match) -> str:
            rid = match.group(1)
            for img in images:
                if img.get("rid") == rid:
                    alt = img.get("alt", img.get("filename", "image"))
                    return f'[image:{img["filename"]}|{alt}]'
            return f"[image:missing:{rid}]"

        return re.sub(r"\[IMAGE:([^\]]+)\]", replace_img, text)


def toTypst(project: "NWProject", output_path: Path | None = None, config: TypstConfig | None = None) -> str:
    """Convert a project to Typst source and compile to PDF.

    Args:
        project: The project to convert.
        output_path: Optional path to write PDF to.
        config: Optional configuration for Typst output.

    Returns:
        Path to the generated PDF file.
    """
    tokenizer = ToTypst(project, config)
    if output_path:
        tokenizer._output_path = output_path
    tokenizer.tokenizeText()
    return str(output_path) if output_path else ""