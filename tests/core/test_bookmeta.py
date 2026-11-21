"""
UmbraEdit - Book Metadata Tests
================================

This file is a part of UmbraEdit.

Copyright (C) 2022 Veronica Berglyd Olsen, B.D. Murphy and novelWriter contributors.

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

import pytest

from umbraedit.constants import nwItemClass, nwItemLayout, nwKeyWords
from umbraedit.core.bookmeta import BookMetaBuilder
from umbraedit.core.coretools import DocxImporter, ProjectBuilder
from umbraedit.core.project import NWProject

from tests.helpers import makeDocx
from tests.mocked import MockGuiMain

# The level 2 items that must exist below the Metadata root
EXPECTED_ITEMS = [
    ("Book Metadata", "prj_document:file"),
    ("epub cover", "prj_document:image"),
    ("epub ISBN", "prj_document:file"),
    ("print cover", "prj_document:image"),
    ("print ISBN", "prj_document:file"),
    ("audio cover", "prj_document:image"),
    ("audio ISBN", "prj_document:file"),
]

# The keywords of the metadata that is common to all output formats
COMMON_KEYS = [
    nwKeyWords.TITLE_KEY,
    nwKeyWords.SUBTITLE_KEY,
    nwKeyWords.AUTHOR_KEY,
    nwKeyWords.SERIES_KEY,
    nwKeyWords.PUBLISHER_KEY,
    nwKeyWords.BLURB_KEY,
    nwKeyWords.BISAC_KEY,
    nwKeyWords.SRCHTERM_KEY,
]


def checkMetadata(project: NWProject, title: str = "", author: str = "") -> None:
    """Check that the project has a Metadata root with the standard
    level 2 items below it.
    """
    root = project.tree.findRoot(nwItemClass.METADATA)
    assert root is not None

    item = project.tree[root]
    assert item is not None
    assert item.itemName == "Metadata"
    assert item.itemClass == nwItemClass.METADATA
    assert item.isRootType()

    node = project.tree.nodes[root]
    children = [(child.item.itemName, child.item.getMainIconStyle()) for child in node.children]
    assert children == EXPECTED_ITEMS

    # All the metadata documents are project notes
    for child in node.children:
        assert child.item.itemClass == nwItemClass.METADATA
        assert child.item.itemLayout == nwItemLayout.NOTE

    # The common metadata document uses the metadata keywords
    text = project.storage.getDocumentText(node.children[0].item.itemHandle)
    for key in COMMON_KEYS:
        assert f"{key}:" in text, f"Missing metadata keyword {key}"

    if title:
        assert f"{nwKeyWords.TITLE_KEY}: {title}" in text
    if author:
        assert f"{nwKeyWords.AUTHOR_KEY}: {author}" in text

    # Each format has a cover document and an ISBN document
    for child in node.children[1:]:
        text = project.storage.getDocumentText(child.item.itemHandle)
        if child.item.itemName.endswith("cover"):
            assert f"{nwKeyWords.COVER_KEY}:" in text
        else:
            assert f"{nwKeyWords.ISBN_KEY}:" in text


@pytest.mark.core
def testBookMeta_Builder(fncPath, mockGUI: MockGuiMain):
    """Build a metadata root directly in a project."""
    project = NWProject()
    assert project.storage.createNewProject(fncPath) is not None

    builder = BookMetaBuilder(project)
    root = builder.build("My Book", "Jane Doe")
    assert root != ""

    # Building it again returns the existing root
    assert builder.build("My Book", "Jane Doe") == root

    checkMetadata(project, "My Book", "Jane Doe")

    # The cover documents record the file name of the cover image
    cover = project.tree.nodes[root].children[1].item.itemHandle
    text = project.storage.getDocumentText(cover)
    assert f"{nwKeyWords.COVER_KEY}: assets/img/epub_cover.png" in text

    project.closeProject()


@pytest.mark.core
def testBookMeta_BlankProject(fncPath, mockGUI: MockGuiMain):
    """A new blank project has a metadata root."""
    data = {
        "name": "Test Project",
        "author": "Jane Doe",
        "language": -1,
        "path": fncPath,
        "sample": False,
        "template": None,
        "chapters": 0,
        "scenes": 0,
        "roots": [],
        "notes": False,
    }

    builder = ProjectBuilder()
    assert builder.buildProject(data) is True

    project = NWProject()
    assert project.openProject(fncPath) is True

    checkMetadata(project, "Test Project", "Jane Doe")

    # The metadata root is a level 1 item, right after the novel
    roots = [node.item.itemName for node in project.tree._model.root.children]
    assert roots[:2] == ["Novel", "Metadata"]

    project.closeProject()


@pytest.mark.core
def testBookMeta_SampleProject(fncPath, mockGUI: MockGuiMain):
    """The sample project has a metadata root."""
    data = {
        "name": "Test Sample",
        "author": "Jane Doe",
        "path": fncPath / "sample",
        "sample": True,
    }

    builder = ProjectBuilder()
    assert builder.buildProject(data) is True

    project = NWProject()
    assert project.openProject(fncPath / "sample") is True

    checkMetadata(project)

    # The sample values are filled in
    root = project.tree.findRoot(nwItemClass.METADATA)
    text = project.storage.getDocumentText(project.tree.nodes[root].children[0].item.itemHandle)  # type: ignore
    assert f"{nwKeyWords.TITLE_KEY}: UmbraEdit Sample" in text
    assert f"{nwKeyWords.BLURB_KEY}: A sample project" in text

    project.closeProject()


@pytest.mark.core
def testBookMeta_DocxImport(fncPath, mockGUI: MockGuiMain):
    """An imported project has a metadata root."""
    docxPath = makeDocx(
        fncPath / "novel.docx",
        [
            ("My Novel", "Title"),
            ("Chapter One", "Heading1"),
            ("The first paragraph of the chapter.", None),
        ],
        title="My Novel",
        author="Jane Doe",
    )

    projPath = fncPath / "imported"
    importer = DocxImporter()
    assert importer.importFile(docxPath, projPath) is True

    project = NWProject()
    assert project.openProject(projPath) is True

    checkMetadata(project, "My Novel", "Jane Doe")

    # The metadata root sits between the locations and research roots
    roots = [node.item.itemName for node in project.tree._model.root.children]
    assert roots == [
        "Novel",
        "Characters",
        "Locations",
        "Metadata",
        "Research",
        "Archive",
        "Trash",
    ]

    # There must be no orphaned files in the project
    assert project.tree.checkConsistency("Recovered") == (0, 0)

    project.closeProject()
