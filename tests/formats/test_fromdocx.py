"""
UmbraEdit - Word DOCX Import Parser Tests
==========================================

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

from pathlib import Path

import pytest

from umbraedit.formats.fromdocx import (
    LEVEL_CHAPTER,
    LEVEL_FRONT,
    LEVEL_SCENE,
    FromDocxDocument,
    _cleanHeading,
    _styleKey,
)

from tests.helpers import makeDocx


@pytest.mark.core
def testFromDocx_StyleKey():
    """Test the normalisation of Word style names."""
    assert _styleKey("Heading1") == "heading1"
    assert _styleKey("heading 1") == "heading1"
    assert _styleKey("WAChapter") == "wachapter"
    assert _styleKey("WASection") == "wasection"
    assert _styleKey("No Spacing") == "nospacing"


@pytest.mark.core
def testFromDocx_CleanHeading():
    """Test the cleaning of heading text."""
    assert _cleanHeading("A Chapter") == "A Chapter"
    assert _cleanHeading("  A Chapter  ") == "A Chapter"
    assert _cleanHeading("A Chapter[COMMENT:7]") == "A Chapter"
    assert _cleanHeading("A Chapter[FOOTNOTE:3]") == "A Chapter"
    assert _cleanHeading("<<<>>> A Scene") == "A Scene"
    assert _cleanHeading("<<<>>>") == ""


@pytest.mark.core
def testFromDocx_InvalidFile(tmp_path: Path):
    """Test that a non-DOCX file is rejected."""
    path = tmp_path / "notadocx.txt"
    path.write_text("This is not a Word document.", encoding="utf-8")
    with pytest.raises(ValueError):
        FromDocxDocument(path).parse()


@pytest.mark.core
def testFromDocx_EmptyDocument(tmp_path: Path):
    """Test that a document without content parses to no scenes."""
    path = makeDocx(tmp_path / "empty.docx", [])
    result = FromDocxDocument(path).parse()
    assert result.scenes == []
    assert result.title == ""
    assert result.author == ""


@pytest.mark.core
def testFromDocx_DocProps(tmp_path: Path):
    """Test that the document properties are used as a fallback."""
    path = makeDocx(
        tmp_path / "props.docx",
        [("Some text", None)],
        title="The Title",
        author="The Author",
    )
    result = FromDocxDocument(path).parse()
    assert result.title == "The Title"
    assert result.author == "The Author"
    assert len(result.scenes) == 1
    assert result.scenes[0].is_front is True
    assert result.scenes[0].level == LEVEL_FRONT


@pytest.mark.core
def testFromDocx_Headings(tmp_path: Path):
    """Test that standard Word headings map to chapters and scenes."""
    path = makeDocx(
        tmp_path / "novel.docx",
        [
            ("My Novel", "Title"),
            ("Jane Doe", "Subtitle"),
            ("Chapter One", "Heading1"),
            ("The first paragraph of the chapter.", None),
            ("Scene One", "Heading2"),
            ("The first scene.", None),
            ("Scene Two", "Heading2"),
            ("The second scene.", None),
            ("Chapter Two", "Heading1"),
            ("Another chapter.", None),
        ],
    )
    result = FromDocxDocument(path).parse()

    # The title and author come from the document body
    assert result.title == "My Novel"
    assert result.author == "Jane Doe"

    # There should be a title page, two chapters and two scenes
    assert len(result.scenes) == 5

    title = result.scenes[0]
    assert title.heading == "My Novel"
    assert title.is_front is True
    assert title.level == LEVEL_FRONT

    chapter = result.scenes[1]
    assert chapter.heading == "Chapter One"
    assert chapter.is_chapter is True
    assert chapter.level == LEVEL_CHAPTER
    assert "first paragraph" in chapter.text

    scene = result.scenes[2]
    assert scene.heading == "Scene One"
    assert scene.is_chapter is False
    assert scene.level == LEVEL_SCENE
    assert "first scene" in scene.text

    scene = result.scenes[3]
    assert scene.heading == "Scene Two"

    chapter = result.scenes[4]
    assert chapter.heading == "Chapter Two"
    assert chapter.is_chapter is True
    assert "Another chapter." in chapter.text


@pytest.mark.core
def testFromDocx_CustomStyles(tmp_path: Path):
    """Test that the custom styles used by some templates are handled."""
    path = makeDocx(
        tmp_path / "custom.docx",
        [
            ("Chapter One", "WAChapter"),
            ("Chapter text.", "WANrmlPgr"),
            ("", "WASection"),
            ("Scene text.", "WANChpPgr"),
        ],
    )
    result = FromDocxDocument(path).parse()
    assert len(result.scenes) == 2

    chapter = result.scenes[0]
    assert chapter.heading == "Chapter One"
    assert chapter.is_chapter is True
    assert "Chapter text." in chapter.text

    scene = result.scenes[1]
    assert scene.heading == "Chapter One - Scene 1"
    assert scene.is_chapter is False
    assert "Scene text." in scene.text


@pytest.mark.core
def testFromDocx_SceneMarker(tmp_path: Path):
    """Test that a scene marker with a name is used as the heading."""
    path = makeDocx(
        tmp_path / "marker.docx",
        [
            ("Chapter One", "WAChapter"),
            ("Chapter text.", "WANrmlPgr"),
            ("<<<>>> Singh POV", "WASection"),
            ("Scene text.", "WANrmlPgr"),
        ],
    )
    result = FromDocxDocument(path).parse()
    assert len(result.scenes) == 2
    assert result.scenes[1].heading == "Singh POV"


@pytest.mark.core
def testFromDocx_EmptyBlocksDropped(tmp_path: Path):
    """Test that blocks without text are not included."""
    path = makeDocx(
        tmp_path / "empty.docx",
        [
            ("", None),
            ("Chapter One", "WAChapter"),
            ("", "WASection"),
            ("Chapter Two", "WAChapter"),
            ("Text.", None),
        ],
    )
    result = FromDocxDocument(path).parse()
    assert len(result.scenes) == 1
    assert result.scenes[0].heading == "Chapter Two"


@pytest.mark.core
def testFromDocx_Comments(tmp_path: Path):
    """Test that comments are inserted into the text as synopsis comments."""
    path = makeDocx(
        tmp_path / "comments.docx",
        [
            ("Chapter One", "Heading1"),
            ("The first paragraph.", None),
            ("The second paragraph.", None),
        ],
        comments=[
            (1, "1", "Check this paragraph"),
            (2, "2", "And this one too"),
        ],
    )
    result = FromDocxDocument(path).parse()

    # The comments must not be converted into notes
    assert result.notes == []

    # Both comments must be captured and anchored to their paragraph
    assert len(result.comments) == 2
    assert result.comments[0].cmt_id == "1"
    assert result.comments[0].author == "Test Author"
    assert result.comments[0].text == "Check this paragraph"
    assert result.comments[0].paragraph == 1
    assert result.comments[1].paragraph == 2

    # The comment must be on the line just before the paragraph it is
    # anchored to, and use the synopsis keyword
    scene = result.scenes[0]
    assert scene.text == (
        "%Synopsis: Test Author: Check this paragraph\n"
        "\n"
        "The first paragraph.\n"
        "\n"
        "%Synopsis: Test Author: And this one too\n"
        "\n"
        "The second paragraph."
    )
    assert len(scene.comments) == 2


@pytest.mark.core
def testFromDocx_CommentOnHeading(tmp_path: Path):
    """Test that a comment on a heading is placed before the heading."""
    path = makeDocx(
        tmp_path / "heading.docx",
        [
            ("Chapter One", "Heading1"),
            ("Some text.", None),
        ],
        comments=[(0, "1", "Chapter note")],
    )
    result = FromDocxDocument(path).parse()
    scene = result.scenes[0]
    assert scene.preamble == ["%Synopsis: Test Author: Chapter note", ""]
    assert scene.text == "Some text."


@pytest.mark.core
def testFromDocx_UnanchoredComment(tmp_path: Path):
    """Test that a comment with no anchor is reported, but not inserted."""
    path = makeDocx(
        tmp_path / "loose.docx",
        [
            ("Chapter One", "Heading1"),
            ("Some text.", None),
        ],
        comments=[(5, "1", "Nowhere")],
    )
    result = FromDocxDocument(path).parse()
    assert len(result.comments) == 1
    assert result.comments[0].paragraph == -1
    assert result.scenes[0].text == "Some text."


@pytest.mark.core
def testFromDocx_Images(tmp_path: Path):
    """Test that images are given an ID and a position marker."""
    path = makeDocx(
        tmp_path / "images.docx",
        [
            ("Chapter One", "Heading1"),
            ("A paragraph with an image.", None),
            ("Another paragraph.", None),
        ],
        images={1: "rId9"},
    )
    result = FromDocxDocument(path).parse()

    # There must be one image, with a stable ID
    assert len(result.images) == 1
    image = result.images[0]
    assert image.img_id.startswith("img_")
    assert image.img_id.endswith("_001")
    assert image.rid == "rId9"
    assert image.mime == "image/png"
    assert image.paragraph == 1
    assert image.offset == 0
    assert image.context == "A paragraph with an image."

    # The text must hold a marker with the ID and the position
    scene = result.scenes[0]
    assert scene.text == (
        f"%Image: {image.img_id} paragraph=1 offset=0 "
        'context="A paragraph with an image."\n'
        "A paragraph with an image.\n"
        "\n"
        "Another paragraph."
    )

    # The image must not be turned into a note
    assert result.notes == []


@pytest.mark.core
def testFromDocx_ImageIDsAreUnique(tmp_path: Path):
    """Test that each image occurrence gets its own ID."""
    path = makeDocx(
        tmp_path / "images.docx",
        [
            ("Chapter One", "Heading1"),
            ("First image.", None),
            ("Second image.", None),
        ],
        images={1: "rId9", 2: "rId9"},
    )
    result = FromDocxDocument(path).parse()
    assert len(result.images) == 2
    assert result.images[0].img_id != result.images[1].img_id
    assert result.images[0].img_id.endswith("_001")
    assert result.images[1].img_id.endswith("_002")
    # The hash of the content must be the same
    assert result.images[0].img_id[4:12] == result.images[1].img_id[4:12]
