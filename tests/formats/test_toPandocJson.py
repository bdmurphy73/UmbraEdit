"""
UmbraEdit - Pandoc JSON Format Tests
====================================

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

import json

from pathlib import Path

import pytest

from umbraedit.core.project import NWProject
from umbraedit.formats.toPandocJson import ToPandocJson

from tests.mocked import MockGuiMain


@pytest.mark.core
def testToPandocJson_ConvertHeaders(mockGUI: MockGuiMain):
    """Test header conversion in the ToPandocJson class."""
    project = NWProject()
    pan = ToPandocJson(project)

    pan._isNovel = False

    # Main Title
    pan._text = "#! Title\n"
    pan.tokenizeText()
    pan.doConvert()
    assert {"t": "Header", "c": [1, ["", [], []], [{"t": "Str", "c": "Title"}]]} in pan._pandocBlocks

    # Heading 1 to 4
    for level, marker in enumerate(["# ", "## ", "### ", "#### "], start=2):
        pan._text = f"{marker}Title\n"
        pan.tokenizeText()
        pan.doConvert()
        assert {
            "t": "Header", "c": [level, ["", [], []], [{"t": "Str", "c": "Title"}]]
        } in pan._pandocBlocks


@pytest.mark.core
def testToPandocJson_ConvertText(mockGUI: MockGuiMain):
    """Test text conversion in the ToPandocJson class."""
    project = NWProject()
    pan = ToPandocJson(project)

    pan._isNovel = False

    pan._text = "Hello **World**.\n"
    pan.tokenizeText()
    pan.doConvert()
    assert {
        "t": "Para", "c": [
            {"t": "Str", "c": "Hello "},
            {"t": "Strong", "c": [{"t": "Str", "c": "World"}]},
            {"t": "Str", "c": "."},
        ]
    } in pan._pandocBlocks


@pytest.mark.core
def testToPandocJson_GetJson(mockGUI: MockGuiMain):
    """Test the JSON output of the ToPandocJson class."""
    project = NWProject()
    pan = ToPandocJson(project)

    pan._isNovel = False
    pan._text = "Hello World.\n"
    pan.tokenizeText()
    pan.doConvert()

    data = json.loads(pan.getJson())
    assert "pandoc-api-version" in data
    assert "meta" in data
    assert data["blocks"] == [{"t": "Para", "c": [{"t": "Str", "c": "Hello World."}]}]


@pytest.mark.core
def testToPandocJson_SaveDocument(mockGUI: MockGuiMain, tmp_path: Path):
    """Test that the ToPandocJson class writes a JSON file."""
    project = NWProject()
    pan = ToPandocJson(project)

    pan._isNovel = False
    pan._text = "Hello World.\n"
    pan.tokenizeText()
    pan.doConvert()

    outPath = tmp_path / "novel.json"
    pan.saveDocument(outPath)

    assert outPath.is_file()
    data = json.loads(outPath.read_text(encoding="utf-8"))
    assert data["blocks"] == [{"t": "Para", "c": [{"t": "Str", "c": "Hello World."}]}]
