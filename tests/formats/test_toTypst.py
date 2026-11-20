"""
UmbraEdit - Typst Format Tests
===============================

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

from pathlib import Path

import pytest

from umbraedit.core.project import NWProject
from umbraedit.formats.toTypst import ToTypst, renderTemplate

from tests.mocked import MockGuiMain


@pytest.mark.core
def testToTypst_ConvertHeaders(mockGUI: MockGuiMain):
    """Test header conversion in the ToTypst class."""
    project = NWProject()
    typ = ToTypst(project)

    typ._isNovel = False

    # Main Title
    typ._text = "#! Title\n"
    typ.tokenizeText()
    typ.doConvert()
    assert "#align(center)[Title]" in typ.typstSource

    # Heading 1 to 4
    for level, marker in enumerate(["# ", "## ", "### ", "#### "], start=1):
        typ._text = f"{marker}Title\n"
        typ.tokenizeText()
        typ.doConvert()
        assert f"{'=' * level} Title" in typ.typstSource


@pytest.mark.core
def testToTypst_ConvertText(mockGUI: MockGuiMain):
    """Test text conversion in the ToTypst class."""
    project = NWProject()
    typ = ToTypst(project)

    typ._isNovel = False

    # Plain text
    typ._text = "Hello World.\n"
    typ.tokenizeText()
    typ.doConvert()
    assert "Hello World." in typ.typstSource

    # Bold, italic and strikeout
    typ._text = "A **bold** and _italic_ and ~~struck~~ text.\n"
    typ.tokenizeText()
    typ.doConvert()
    assert "A *bold* and _italic_ and -struck- text." in typ.typstSource


@pytest.mark.core
def testToTypst_Template(mockGUI: MockGuiMain):
    """Test the Typst template renderer."""
    values = {
        "name": "UmbraEdit",
        "size": 12,
        "flag": True,
        "fonts": [{"name": "Book_Font", "path": "/tmp/book.otf"}],
    }
    assert renderTemplate("Hello {{name}}!", values) == "Hello UmbraEdit!"
    assert renderTemplate("Size: {{size}}", values) == "Size: 12"
    assert renderTemplate("Flag: {{flag}}", values) == "Flag: true"
    assert renderTemplate("Missing: {{nope}}", values) == "Missing: "

    # Loops
    template = '{% for font in fonts %}#let {{font.name}} = @font("{{font.path}}")\n{% endfor %}'
    assert renderTemplate(template, values) == '#let Book_Font = @font("/tmp/book.otf")\n'

    # An empty loop produces no output
    assert renderTemplate("{% for font in fonts %}x{% endfor %}", {"fonts": []}) == ""


@pytest.mark.core
def testToTypst_SaveDocument(mockGUI: MockGuiMain, tmp_path: Path):
    """Test that the ToTypst class writes a PDF file."""
    project = NWProject()
    typ = ToTypst(project)

    typ._isNovel = False
    typ._text = "#! My Novel\n\nSome text.\n"
    typ.tokenizeText()
    typ.doConvert()

    outPath = tmp_path / "novel.pdf"
    typ.saveDocument(outPath)

    assert outPath.is_file()
    assert outPath.stat().st_size > 0
