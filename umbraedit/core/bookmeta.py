"""
UmbraEdit - Book Metadata Builder
=================================

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

import logging

from typing import TYPE_CHECKING

from umbraedit.constants import nwItemClass, nwItemLayout, nwKeyWords

if TYPE_CHECKING:
    from umbraedit.core.project import NWProject

logger = logging.getLogger(__name__)


class BookMetaBuilder:
    """Tool: Build the book metadata structure of a project.

    The metadata is a level 1 item in the project tree, and the items
    describing the metadata are level 2 items below it. A book
    manuscript is published in several output formats, so the metadata
    is split into two groups.

    The first group is the information that is common to all formats.
    It is kept in a single text document that uses metadata keywords,
    like @Blurb, @BISAC and @SrchTerm.

    The second group is the information that is specific to each output
    format. Each format gets a cover image document and an ISBN
    document of its own, titled "epub cover", "print cover", and so on.
    """

    # The output formats a book manuscript is published in
    FORMATS: tuple[str, ...] = ("epub", "print", "audio")

    # Labels for the metadata items
    ROOT_LABEL = "Metadata"
    COMMON_LABEL = "Book Metadata"
    COVER_LABEL = "{0} cover"
    ISBN_LABEL = "{0} ISBN"

    # Icon styles for the metadata items
    ICON_TEXT = "prj_document:file"
    ICON_IMAGE = "prj_document:image"

    def __init__(self, project: NWProject) -> None:
        self._project = project

    ##
    #  Methods
    ##

    def build(self, title: str = "", author: str = "") -> str:
        """Create the metadata root and its child documents.

        The handle of the metadata root is returned. If the project
        already has a metadata root, it is returned as is.
        """
        if root := self._project.tree.findRoot(nwItemClass.METADATA):
            return root

        root = self._project.newRoot(nwItemClass.METADATA)
        if not root:
            logger.error("Could not create the metadata root")
            return ""

        self._addCommon(root, title, author)
        for fmt in self.FORMATS:
            self._addCover(root, fmt)
            self._addIsbn(root, fmt)

        return root

    ##
    #  Internal Functions
    ##

    def _addCommon(self, root: str, title: str, author: str) -> None:
        """Add the document holding the metadata common to all formats."""
        lines = [
            f"# {self.COMMON_LABEL}",
            "",
            "@tag: BookMetadata",
            "",
            "%Short: Metadata for the book manuscript.",
            "",
            f"{nwKeyWords.TITLE_KEY}: {title}",
            f"{nwKeyWords.SUBTITLE_KEY}:",
            f"{nwKeyWords.AUTHOR_KEY}: {author}",
            f"{nwKeyWords.SERIES_KEY}:",
            f"{nwKeyWords.PUBLISHER_KEY}:",
            f"{nwKeyWords.BLURB_KEY}:",
            f"{nwKeyWords.BISAC_KEY}:",
            f"{nwKeyWords.SRCHTERM_KEY}:",
        ]
        self._writeNote(root, self.COMMON_LABEL, self.ICON_TEXT, lines)

    def _addCover(self, root: str, fmt: str) -> None:
        """Add the cover image document for an output format."""
        label = self.COVER_LABEL.format(fmt)
        lines = [
            f"# {label}",
            "",
            "%Short: Cover image for the {0} format.".format(fmt),
            "",
            "Add the cover image for this format to the assets/img folder of",
            "the project, and record the file name below.",
            "",
            f"{nwKeyWords.COVER_KEY}: assets/img/{fmt}_cover.png",
        ]
        self._writeNote(root, label, self.ICON_IMAGE, lines)

    def _addIsbn(self, root: str, fmt: str) -> None:
        """Add the ISBN document for an output format."""
        label = self.ISBN_LABEL.format(fmt)
        lines = [
            f"# {label}",
            "",
            "%Short: ISBN for the {0} format.".format(fmt),
            "",
            f"{nwKeyWords.ISBN_KEY}:",
        ]
        self._writeNote(root, label, self.ICON_TEXT, lines)

    def _writeNote(self, root: str, label: str, icon: str, lines: list[str]) -> str | None:
        """Write a metadata document below the metadata root."""
        handle = self._project.newFile(label, root)
        if not handle:
            logger.error("Could not create metadata document '%s'", label)
            return None

        item = self._project.tree[handle]
        if item is None:  # pragma: no cover
            return None

        item.setLayout(nwItemLayout.NOTE)
        item.setIconStyle(icon)

        text = "\n".join(lines).rstrip() + "\n"
        self._project.storage.getDocument(handle).writeDocument(text)

        return handle
