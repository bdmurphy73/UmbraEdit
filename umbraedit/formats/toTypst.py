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

import logging
import re
import shutil
import subprocess
import tempfile

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from umbraedit.formats.shared import BlockFmt, BlockTyp, TextFmt
from umbraedit.formats.tokenizer import Tokenizer
from umbraedit.umbra.metadata import Metadata, loadMetadata
from umbraedit.umbra.paths import assetsDir

if TYPE_CHECKING:  # pragma: no cover
    from umbraedit.core.project import NWProject
    from umbraedit.formats.shared import T_Formats

logger = logging.getLogger(__name__)

# Default Typst template for print
DEFAULT_TYPST_TEMPLATE = r"""
// UmbraEdit print template
// =========================

// Page setup
#set page(
  paper: ({{trim_width}} + 2 * {{gutter}}, {{trim_height}}),
  margin: ({{margin_top}}, {{margin_inner}} + {{gutter}}, {{margin_bottom}}, {{margin_outer}} + {{gutter}}),
)

// Typography
#set text(font: "{{font_family}}", size: {{font_size}}pt, lang: "{{hyphenation_lang}}")
#set par(justify: true, leading: {{line_height}})
#set heading(numbering: "1.1")

// Embedded fonts (OFL)
{% for font in embedded_fonts %}
#let {{font.name}} = @font("{{font.path}}")
{% endfor %}

// Main content
{{content}}
"""

# Template Syntax
# ================

RX_TEMPLATE_VAR = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\}\}"
)
RX_TEMPLATE_LOOP = re.compile(
    r"\{%\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([A-Za-z_][A-Za-z0-9_]*)\s*%\}"
    r"(.*?)"
    r"\{%\s*endfor\s*%\}",
    re.DOTALL,
)


def _lookupValue(path: str, values: dict[str, Any]) -> str:
    """Look up a dotted path in a dictionary of template values."""
    parts = path.split(".")
    value: Any = values.get(parts[0], "")
    for part in parts[1:]:
        if isinstance(value, dict):
            value = value.get(part, "")
        else:
            value = getattr(value, part, "")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def renderTemplate(template: str, values: dict[str, Any]) -> str:
    """Render a Typst template.

    The template supports ``{{name}}`` substitutions and
    ``{% for item in list %}`` blocks. Dotted paths are supported for
    both, so ``{{item.name}}`` looks up the ``name`` key of the
    ``item`` dictionary. Unknown names are replaced with an empty
    string.
    """
    text = template
    for _ in range(8):
        match = RX_TEMPLATE_LOOP.search(text)
        if match is None:
            break
        varName, listName, body = match.group(1), match.group(2), match.group(3)
        items = values.get(listName, [])
        if not isinstance(items, (list, tuple)):
            items = []
        parts = []
        for item in items:
            scope = dict(values)
            scope[varName] = item
            parts.append(RX_TEMPLATE_VAR.sub(
                lambda m, s=scope: _lookupValue(m.group(1), s), body
            ))
        text = f"{text[:match.start()]}{''.join(parts)}{text[match.end():]}"
    return RX_TEMPLATE_VAR.sub(lambda m: _lookupValue(m.group(1), values), text)


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

    Converts the manuscript to Typst source, compiles it with Typst,
    and produces a print-ready PDF. If the Typst compiler is not
    available on the system, the PDF is generated with the Qt print
    engine instead.
    """

    __slots__ = (
        "_assetsDir",
        "_config",
        "_metadata",
        "_outputPath",
        "_plainText",
        "_project",
        "_template",
        "_typstSource",
    )

    def __init__(self, project: NWProject, config: Optional[TypstConfig] = None) -> None:
        super().__init__(project)
        self._project = project
        self._config = config or TypstConfig()
        storagePath = self._project.storage.storagePath
        self._metadata = loadMetadata(storagePath) if storagePath else Metadata()
        self._assetsDir = assetsDir(storagePath) if storagePath else Path()
        self._template = self._loadTemplate()
        self._outputPath: Optional[Path] = None
        self._plainText = ""
        self._typstSource = ""

    ##
    #  Properties
    ##

    @property
    def typstSource(self) -> str:
        """The Typst source of the manuscript built so far."""
        return self._typstSource

    ##
    #  Class Methods
    ##

    def tokenizeText(self) -> None:
        """Tokenise the current document.

        The Typst source is generated in ``doConvert()`` so that it is
        built in the same way as for the other document writers.
        """
        super().tokenizeText()

    def doConvert(self) -> None:
        """Convert the blocks of the current document to Typst."""
        source = self._blocksToTypst()
        if source:
            if self._typstSource:
                self._typstSource += "\n\n"
            self._typstSource += source
        if self._plainText:
            self._plainText += "\n\n"
        self._plainText += self._blocksToPlainText()

    def closeDocument(self) -> None:
        """Run close document tasks. There is nothing to close."""

    def saveDocument(self, path: Path) -> None:
        """Save the manuscript as a PDF file."""
        self._outputPath = path
        source = self.getTypstSource()
        exe = shutil.which("typst")
        if exe is not None:
            try:
                self._compileTypst(exe, source, path)
            except Exception as exc:
                logger.warning("Typst compilation failed, falling back to Qt: %s", exc)
            else:
                logger.info("Wrote file: %s", path)
                return
        else:
            logger.warning("Typst compiler not found, using the Qt PDF engine")
        self._savePdfFallback(path)
        logger.info("Wrote file: %s", path)

    ##
    #  Internal Functions
    ##

    def _loadTemplate(self) -> str:
        """Load the Typst template from the project, or use default."""
        storagePath = self._project.storage.storagePath
        if storagePath:
            templatePath = storagePath / "umbra" / "templates" / "print.typ"
            if templatePath.is_file():
                try:
                    return templatePath.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.warning("Failed to load custom template: %s", exc)
        return DEFAULT_TYPST_TEMPLATE

    def _getMetadata(self) -> dict[str, Any]:
        """Extract the metadata used by the template."""
        meta = self._metadata
        return {
            "title": meta.book.get("title", ""),
            "author": meta.book.get("author", ""),
            "language": meta.book.get("language", "en"),
            "isbn": meta.book.get("isbn", ""),
        }

    def _buildTypstConfig(self) -> dict[str, Any]:
        """Build the configuration dictionary for the template."""
        meta = self._metadata
        cfg = self._config

        # Get trim size from the book metadata
        trimSize = meta.book.get("trim_size") or ""
        if "x" in trimSize:
            parts = trimSize.split("x")
            width = parts[0].strip() + "mm"
            height = parts[1].strip() + "mm"
        else:
            width = cfg.trim_width
            height = cfg.trim_height

        # Font settings from the build settings take priority
        fontFamily = cfg.font_family
        fontSize = cfg.font_size
        if self._textFont is not None:
            if family := self._textFont.family():
                fontFamily = family
            if pointSize := self._textFont.pointSize():
                fontSize = pointSize
        if meta.book.get("font_family"):
            fontFamily = meta.book["font_family"]

        return {
            "trim_width": width,
            "trim_height": height,
            "gutter": cfg.gutter,
            "margin_inner": cfg.margin_inner,
            "margin_outer": cfg.margin_outer,
            "margin_top": cfg.margin_top,
            "margin_bottom": cfg.margin_bottom,
            "font_family": fontFamily.replace('"', ""),
            "font_size": fontSize,
            "line_height": self._lineHeight or cfg.line_height,
            "hyphenation_lang": cfg.hyphenation_lang,
            "running_headers": str(cfg.running_headers).lower(),
            "embedded_fonts": self._embeddedFonts(),
            "content": "",  # Filled in by the caller
        }

    def _embeddedFonts(self) -> list[dict[str, str]]:
        """Return the list of fonts embedded in the project assets."""
        fonts = []
        try:
            fontFiles = sorted(self._assetsDir.glob("*.otf"))
        except Exception:  # pragma: no cover
            return fonts
        for fontFile in fontFiles:
            fonts.append({
                "name": re.sub(r"\W+", "_", fontFile.stem),
                "path": str(fontFile),
            })
        return fonts

    def getTypstSource(self) -> str:
        """Return the rendered Typst source of the manuscript."""
        config = self._buildTypstConfig()
        config["content"] = self._typstSource
        return renderTemplate(self._template, config)

    def _compileTypst(self, exe: str, source: str, path: Path) -> None:
        """Compile the Typst source into a PDF file."""
        with tempfile.TemporaryDirectory(prefix="umbraedit-typst-") as tmpDir:
            srcPath = Path(tmpDir) / "manuscript.typ"
            pdfPath = Path(tmpDir) / "manuscript.pdf"
            srcPath.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [exe, "compile", str(srcPath), str(pdfPath)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Typst exited with {result.returncode}: {result.stderr.strip()}")
            shutil.copy2(pdfPath, path)

    def _savePdfFallback(self, path: Path) -> None:
        """Write the manuscript as a PDF using the Qt print engine.

        This is used when the Typst compiler is not available.
        """
        from PyQt6.QtCore import QMarginsF, QSizeF
        from PyQt6.QtGui import QFont, QPageLayout, QPageSize, QTextDocument
        from PyQt6.QtPrintSupport import QPrinter

        config = self._buildTypstConfig()
        width = self._parseLength(config["trim_width"])
        height = self._parseLength(config["trim_height"])

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(path))
        printer.setPageSize(QPageSize(
            QSizeF(width, height),
            QPageSize.Unit.Millimeter,
            "Trim",
            QPageSize.SizeMatchPolicy.ExactMatch,
        ))
        printer.setPageMargins(QMarginsF(
            self._parseLength(config["margin_top"]),
            self._parseLength(config["margin_inner"]),
            self._parseLength(config["margin_bottom"]),
            self._parseLength(config["margin_outer"]),
        ), QPageLayout.Unit.Millimeter)
        printer.setDocName(self._project.data.name)

        document = QTextDocument()
        document.setDefaultFont(QFont(config["font_family"], int(config["font_size"])))
        document.setPlainText(self._plainText)
        document.print(printer)

    @staticmethod
    def _parseLength(value: str) -> float:
        """Parse a length string into millimetres."""
        match = re.match(r"^\s*([0-9.]+)\s*mm", str(value))
        if match:
            return float(match.group(1))
        match = re.match(r"^\s*([0-9.]+)\s*in", str(value))
        if match:
            return float(match.group(1)) * 25.4
        return 0.0

    def _blocksToTypst(self) -> str:
        """Convert the blocks of the current document to Typst markup."""
        paras: list[str] = []
        items: list[str] = []
        nItem = 0

        for tType, _, tText, tFormat, tStyle in self._blocks:

            if tType in (BlockTyp.LIST_U, BlockTyp.LIST_O):
                if tType == BlockTyp.LIST_O:
                    nItem = 1 if tStyle & BlockFmt.LIST_S else nItem + 1
                    items.append(f"{nItem}. {self._formatText(tText, tFormat)}")
                else:
                    items.append(f"- {self._formatText(tText, tFormat)}")
                continue

            if items:
                paras.append("\n".join(items))
                items = []
                nItem = 0

            if tType == BlockTyp.TEXT:
                paras.append(self._formatText(tText, tFormat))

            elif tType in (BlockTyp.TITLE, BlockTyp.PART):
                paras.append(f"#align(center)[{self._formatText(tText, tFormat)}]")

            elif tType in (BlockTyp.HEAD1, BlockTyp.HEAD2, BlockTyp.HEAD3, BlockTyp.HEAD4):
                level = int(tType) - int(BlockTyp.HEAD1) + 1
                paras.append(f"{'=' * level} {self._formatText(tText, tFormat)}")

            elif tType == BlockTyp.SEP:
                paras.append("#align(center)[* * *]")

            elif tType == BlockTyp.HRULE:
                paras.append("#line(length: 100%)")

            elif tType == BlockTyp.SKIP:
                paras.append("#v(0.5em)")

            elif tType == BlockTyp.KEYWORD:
                paras.append(self._formatText(tText, tFormat))

            else:
                continue

        if items:
            paras.append("\n".join(items))

        return "\n\n".join(paras)

    def _blocksToPlainText(self) -> str:
        """Convert the blocks of the current document to plain text."""
        lines: list[str] = []
        for tType, _, tText, _, _ in self._blocks:
            if tType == BlockTyp.TEXT:
                lines.append(tText)
            elif tType in (BlockTyp.TITLE, BlockTyp.PART):
                lines.append(tText)
            elif tType in (BlockTyp.HEAD1, BlockTyp.HEAD2, BlockTyp.HEAD3, BlockTyp.HEAD4):
                level = int(tType) - int(BlockTyp.HEAD1) + 1
                lines.append(f"{'#' * level} {tText}")
            elif tType == BlockTyp.SEP:
                lines.append("* * *")
            elif tType == BlockTyp.HRULE:
                lines.append("----")
            elif tType == BlockTyp.SKIP:
                lines.append("")
            elif tType == BlockTyp.KEYWORD:
                lines.append(tText)
        return "\n".join(lines)

    def _formatText(self, text: str, tFmt: T_Formats) -> str:
        """Apply the text format map and convert it to Typst markup."""
        tags: list[tuple[int, str]] = []
        for pos, fmt, data in tFmt:
            if fmt == TextFmt.B_B:
                tags.append((pos, "*"))
            elif fmt == TextFmt.B_E:
                tags.append((pos, "*"))
            elif fmt == TextFmt.I_B:
                tags.append((pos, "_"))
            elif fmt == TextFmt.I_E:
                tags.append((pos, "_"))
            elif fmt == TextFmt.D_B:
                tags.append((pos, "-"))
            elif fmt == TextFmt.D_E:
                tags.append((pos, "-"))
            elif fmt == TextFmt.U_B:
                tags.append((pos, "#underline["))
            elif fmt == TextFmt.U_E:
                tags.append((pos, "]"))
            elif fmt == TextFmt.M_B:
                tags.append((pos, "#highlight["))
            elif fmt == TextFmt.M_E:
                tags.append((pos, "]"))
            elif fmt == TextFmt.SUP_B:
                tags.append((pos, "#super["))
            elif fmt == TextFmt.SUP_E:
                tags.append((pos, "]"))
            elif fmt == TextFmt.SUB_B:
                tags.append((pos, "#sub["))
            elif fmt == TextFmt.SUB_E:
                tags.append((pos, "]"))
            elif fmt == TextFmt.COL_B:
                tags.append((pos, "#text(fill: black)["))
            elif fmt == TextFmt.COL_E:
                tags.append((pos, "]"))
            elif fmt == TextFmt.ANM_B:
                tags.append((pos, f'#label("{data}")'))
            elif fmt == TextFmt.ARF_B:
                tags.append((pos, f"#link(<{data}>)["))
            elif fmt == TextFmt.ARF_E:
                tags.append((pos, "]"))
            elif fmt == TextFmt.HRF_B:
                tags.append((pos, f'#link("{data}")['))
            elif fmt == TextFmt.HRF_E:
                tags.append((pos, "]"))
            elif fmt == TextFmt.FNOTE:
                if data in self._footnotes:
                    note = self._footnotes[data]
                    tags.append((pos, f"#footnote[{self._formatText(note[0], note[1])}]"))
                else:
                    tags.append((pos, "#footnote[Missing footnote]"))
            elif fmt == TextFmt.FIELD:
                tags.append((pos, ""))
            elif fmt == TextFmt.STRIP:
                tags.append((pos, ""))
            elif fmt in (TextFmt.ERR_B, TextFmt.ERR_E):
                tags.append((pos, ""))

        # Insert all tags at their correct position, starting from the back
        temp = text
        for pos, tag in reversed(tags):
            temp = f"{temp[:pos]}{tag}{temp[pos:]}"

        return temp.replace("\n", " ")


def toTypst(
    project: NWProject,
    outputPath: Optional[Path] = None,
    config: Optional[TypstConfig] = None,
) -> tuple[bool, str]:
    """Convert a project to a print PDF.

    Args:
        project: The project to convert.
        outputPath: Optional path to write the PDF to.
        config: Optional configuration for Typst output.

    Returns:
        A tuple of (success, result), where result is the path to the
        generated file, or an error message.

    """
    from umbraedit.enum import nwItemLayout

    tokenizer = ToTypst(project, config)
    tokenizer.initDocument()
    for item in project.tree:
        if item.isFileType() and item.itemLayout == nwItemLayout.DOCUMENT:
            tokenizer.setText(item.itemHandle)
            tokenizer.tokenizeText()
            tokenizer.doConvert()
    tokenizer.closeDocument()

    if outputPath is None:
        return False, "No output path specified"

    try:
        tokenizer.saveDocument(outputPath)
    except Exception as exc:
        logger.exception("Print PDF generation failed")
        return False, str(exc)

    return True, str(outputPath)
