"""
UmbraEdit - Word DOCX/DOCM Import Converter
============================================

This file is a part of UmbraEdit.

Copyright (C) 2018 Veronica Berglyd Olsen and UmbraEdit contributors.

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

import hashlib
import logging
import re
import xml.etree.ElementTree as ET

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from zipfile import ZipFile, is_zipfile

from umbraedit.constants import (
    nwShortcode,
)

logger = logging.getLogger(__name__)

# WordprocessingML namespace
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# DrawingML namespace, used by the image references in Word drawings
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

# VML namespace, used by legacy image references
V_NS = "urn:schemas-microsoft-com:vml"

# Dublin Core namespaces, used by the core document properties
DC_NS = "http://purl.org/dc/elements/1.1/"


def _wtag(tag: str) -> str:
    """Return the namespaced tag for the w namespace."""
    return f"{{{W_NS}}}{tag}"


def _rtag(tag: str) -> str:
    """Return the namespaced tag for the r namespace."""
    return f"{{{R_NS}}}{tag}"


def _atag(tag: str) -> str:
    """Return the namespaced tag for the DrawingML namespace."""
    return f"{{{A_NS}}}{tag}"


def _vtag(tag: str) -> str:
    """Return the namespaced tag for the VML namespace."""
    return f"{{{V_NS}}}{tag}"


def _dtag(tag: str) -> str:
    """Return the namespaced tag for the dc namespace."""
    return f"{{{DC_NS}}}{tag}"


# Mapping of Word paragraph styles to UmbraEdit content roles.
#
# The style names are normalised with _styleKey() before the lookup, so
# the keys below are lower case and stripped of spaces, dashes and
# underscores.
#
# Roles:
#   "title"    -> the document title, opens a front matter block
#   "subtitle" -> the author name, appended to the current block
#   "chapter"  -> opens a new chapter
#   "scene"    -> opens a new scene inside the current chapter
#   "body"     -> regular body text
#
# Any style not listed here is treated as body text.
STYLE_MAP: dict[str, str] = {
    "title": "title",
    "subtitle": "subtitle",
    "tocheading": "chapter",
    "wachapter": "chapter",
    "heading1": "chapter",
    "wasection": "scene",
    "heading2": "scene",
}

# Heading levels used for the imported documents. These correspond to the
# novelWriter heading levels, where H1 is the title page, H2 is a chapter,
# and H3 is a scene.
LEVEL_FRONT = 0
LEVEL_CHAPTER = 1
LEVEL_SCENE = 2

# Markers used in the source document for comments, footnotes and images
_MARKER = re.compile(r"\[(?:COMMENT|FOOTNOTE|IMAGE)[^\]]*\]")

# Angle bracket markers, often used by authors to mark scene breaks
_ANGLE = re.compile(r"^[<>\s]+|[<>\s]+$")

# The keyword used to embed a Word comment into the text of a document.
# The comment is placed on the line just before the paragraph it was
# anchored to in the Word document.
COMMENT_KEY = "%Synopsis:"

# The keyword used to mark the position of an image in a text document.
# The image ID is followed by position information that a formatter can
# use to place the image later.
IMAGE_KEY = "%Image:"

# The number of characters of context text captured for an image marker
IMAGE_CONTEXT = 30


def _styleKey(style: str) -> str:
    """Normalise a Word paragraph style name for style map lookups."""
    return re.sub(r"[\s\-_]+", "", style).lower()


def _cleanHeading(text: str) -> str:
    """Clean up a heading string by stripping markers and extra spaces."""
    text = _MARKER.sub("", text)
    text = _ANGLE.sub("", text)
    return " ".join(text.split())


def _flatten(text: str) -> str:
    """Collapse a text into a single line with single spaces."""
    return " ".join(text.split())


def _quoteText(text: str) -> str:
    """Make a text safe to include in a double quoted marker value."""
    return _flatten(text).replace('"', "'")


@dataclass
class ImportImage:
    """Information about an image found in the Word document."""

    rid: str
    filename: str
    data: bytes
    mime: str
    img_id: str = ""       # Stable ID of the image, like "img_1a2b3c4d_001"
    paragraph: int = -1    # Index of the paragraph the image is in
    offset: int = 0        # Character offset of the image in the paragraph
    context: str = ""      # Text surrounding the image in the paragraph


@dataclass
class ImportComment:
    """A Word comment, and the paragraph it is anchored to."""

    cmt_id: str
    author: str
    date: str
    text: str
    paragraph: int = -1    # Index of the anchor paragraph, -1 if not anchored


@dataclass
class ImportNote:
    """A note capturing a non-translatable item from the Word document."""

    note_type: str       # "header", "footer", "footnote"
    source: str          # Where it came from (e.g., "header1.xml", "paragraph 42")
    text: str            # Captured text description
    data: Optional[bytes] = None  # Raw image data, if applicable
    mime: Optional[str] = None    # MIME type, if applicable


@dataclass
class ImportScene:
    """A scene document entry from the Word document."""

    heading: str
    level: int
    text: str
    style: str
    is_chapter: bool = False  # True if this is a chapter heading
    is_front: bool = False    # True if this is front matter
    preamble: list[str] = field(default_factory=list)      # Lines before the heading
    images: list[ImportImage] = field(default_factory=list)  # Images in the document
    comments: list[ImportComment] = field(default_factory=list)  # Anchored comments


@dataclass
class _Block:
    """Internal container for a block of parsed document content."""

    role: str
    heading: str
    level: int
    style: str = "Normal"
    lines: list[str] = field(default_factory=list)
    preamble: list[str] = field(default_factory=list)
    images: list[ImportImage] = field(default_factory=list)
    comments: list[ImportComment] = field(default_factory=list)


@dataclass
class ImportResult:
    """Result of parsing a Word DOCX/DOCM file."""

    title: str = ""
    author: str = ""
    scenes: list[ImportScene] = field(default_factory=list)
    notes: list[ImportNote] = field(default_factory=list)
    images: list[ImportImage] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    footers: list[str] = field(default_factory=list)
    comments: list[ImportComment] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)


class FromDocxDocument:
    """Core: Convert a Word DOCX/DOCM file into UmbraEdit import data.

    Parses the WordprocessingML XML inside a .docm or .docx file and
    extracts text content, headings, and non-translatable items
    (images, headers, footers, comments, footnotes) into notes.
    """

    __slots__ = (
        "_anchored",
        "_comments",
        "_file_path",
        "_footers",
        "_headers",
        "_imageCount",
        "_images",
        "_rels",
        "_result",
        "_zip",
    )

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._zip: Optional[ZipFile] = None
        self._result = ImportResult()
        self._rels: dict[str, str] = {}
        self._images: dict[str, ImportImage] = {}
        self._headers: dict[str, str] = {}
        self._footers: dict[str, str] = {}
        self._comments: dict[str, ImportComment] = {}
        self._anchored: set[str] = set()
        self._imageCount = 0

    ##
    #  Public API
    ##

    def parse(self) -> ImportResult:
        """Parse the Word document and return the import result."""
        if not is_zipfile(self._file_path):
            raise ValueError(f"Not a valid ZIP/DOCX file: {self._file_path}")

        self._zip = ZipFile(self._file_path)

        try:
            self._load_relationships()
            self._load_headers_footers()
            self._parse_comments()
            self._parse_document()
            self._parse_footnotes()
            self._load_docprops()
        finally:
            self._zip.close()
            self._zip = None

        return self._result

    ##
    #  Internal Loading
    ##

    def _read_xml(self, name: str) -> str:
        """Read and return an XML file from the ZIP archive."""
        if self._zip is None:
            return ""
        try:
            return self._zip.read(name).decode("utf-8")
        except KeyError:
            logger.warning("File not found in DOCX: %s", name)
            return ""

    def _load_docprops(self) -> None:
        """Load the core document properties.

        These are only used as a fallback for the title and author, as
        the values in the document body are usually more accurate.
        """
        xml_text = self._read_xml("docProps/core.xml")
        if not xml_text:
            return
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.warning("Could not parse docProps/core.xml")
            return

        title = root.findtext(_dtag("title")) or ""
        creator = root.findtext(_dtag("creator")) or ""
        if title and not self._result.title:
            self._result.title = " ".join(title.split())
        if creator and not self._result.author:
            self._result.author = " ".join(creator.split())

    def _load_relationships(self) -> None:
        """Load document relationships (maps rIds to targets)."""
        xml_text = self._read_xml("word/_rels/document.xml.rels")
        if not xml_text:
            return
        root = ET.fromstring(xml_text)
        for rel in root.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
            rid = rel.get("Id", "")
            target = rel.get("Target", "")
            rel_type = rel.get("Type", "")
            self._rels[rid] = target
            # Cache image data
            if "image" in rel_type:
                target_path = f"word/{target}" if not target.startswith("word/") else target
                try:
                    data = self._zip.read(target_path)  # type: ignore[union-attr]
                    mime = self._guess_mime(target)
                    self._images[rid] = ImportImage(
                        rid=rid, filename=target, data=data, mime=mime
                    )
                except KeyError:
                    logger.warning("Could not read image: %s", target_path)

    def _load_headers_footers(self) -> None:
        """Load header and footer XML files."""
        for rid, target in self._rels.items():
            if "header" in target and target.endswith(".xml"):
                target_path = f"word/{target}" if not target.startswith("word/") else target
                try:
                    xml_text = self._read_xml(target_path)
                    text = self._extract_text_from_xml(xml_text)
                    if text.strip():
                        self._result.headers.append(text)
                        self._headers[rid] = text
                except ET.ParseError:
                    logger.warning("Could not parse header: %s", target)
            elif "footer" in target and target.endswith(".xml"):
                target_path = f"word/{target}" if not target.startswith("word/") else target
                try:
                    xml_text = self._read_xml(target_path)
                    text = self._extract_text_from_xml(xml_text)
                    if text.strip():
                        self._result.footers.append(text)
                        self._footers[rid] = text
                except ET.ParseError:
                    logger.warning("Could not parse footer: %s", target)

    def _parse_document(self) -> None:
        """Parse the main document.xml content."""
        xml_text = self._read_xml("word/document.xml")
        if not xml_text:
            return

        root = ET.fromstring(xml_text)
        body = root.find(_wtag("body"))
        if body is None:
            return

        # The document is parsed into a flat list of blocks. Each block
        # becomes one project document when the project is created.
        blocks: list[_Block] = []
        current: Optional[_Block] = None
        chapterHeading = ""
        sceneCount = 0
        paraIndex = -1

        def closeBlock() -> None:
            """Close the current block and add it to the block list."""
            nonlocal current
            if current is not None:
                blocks.append(current)
                current = None

        for para in body.findall(_wtag("p")):
            paraIndex += 1
            para_result = self._parse_paragraph(para, paraIndex)
            if para_result is None:
                continue

            style = para_result["style"]
            text = para_result["text"]
            role = STYLE_MAP.get(_styleKey(style), "body")

            # Comments and images are represented by marker lines that
            # are inserted just before the paragraph they belong to.
            markers = self._markerLines(para_result)

            # Handle the document title. It opens a front matter block,
            # and is also used as the project title.
            if role == "title":
                title = _cleanHeading(text)
                if title and not self._result.title:
                    self._result.title = title
                closeBlock()
                current = _Block("front", title or "Title Page", LEVEL_FRONT, style)
                current.preamble.extend(markers)
                current.images.extend(para_result["images"])
                current.comments.extend(para_result["comments"])
                continue

            # Handle the subtitle. It is the author name, and is kept as
            # a line of text in the current block.
            if role == "subtitle":
                subtitle = _cleanHeading(text)
                if subtitle and not self._result.author:
                    self._result.author = subtitle
                if current is None:
                    current = _Block("front", "Title Page", LEVEL_FRONT, style)
                current.lines.extend(markers)
                if subtitle:
                    current.lines.append(subtitle)
                    current.lines.append("")
                current.images.extend(para_result["images"])
                current.comments.extend(para_result["comments"])
                continue

            # Handle chapter headings. These open a new chapter.
            if role == "chapter":
                heading = _cleanHeading(text)
                closeBlock()
                chapterHeading = heading or f"Chapter {len(blocks) + 1}"
                sceneCount = 0
                current = _Block("chapter", chapterHeading, LEVEL_CHAPTER, style)
                current.preamble.extend(markers)
                current.images.extend(para_result["images"])
                current.comments.extend(para_result["comments"])
                continue

            # Handle scene breaks. These open a new scene in the current
            # chapter. The text of the break itself is used as the scene
            # heading when it contains anything but markers.
            if role == "scene":
                heading = _cleanHeading(text)
                closeBlock()
                sceneCount += 1
                if not heading:
                    heading = f"{chapterHeading} - Scene {sceneCount}" if chapterHeading else f"Scene {sceneCount}"
                current = _Block("scene", heading, LEVEL_SCENE, style)
                current.preamble.extend(markers)
                current.images.extend(para_result["images"])
                current.comments.extend(para_result["comments"])
                continue

            # Regular content paragraphs
            if text.strip() or markers:
                if current is None:
                    current = _Block("front", "Front Matter", LEVEL_FRONT, style)
                current.lines.extend(markers)
                if text.strip():
                    current.lines.append(text)
                    current.lines.append("")
                elif para_result["images"]:
                    # An image only paragraph is separated from the next
                    current.lines.append("")
                current.images.extend(para_result["images"])
                current.comments.extend(para_result["comments"])

        # Save the last block
        closeBlock()

        # Convert the blocks into scenes. Blocks without any text are
        # dropped, as they only hold empty section breaks.
        for block in blocks:
            text = "\n".join(block.lines).strip()
            if not text and not block.preamble and not block.images:
                continue
            self._result.scenes.append(
                ImportScene(
                    heading=block.heading,
                    level=block.level,
                    text=text,
                    style=block.style,
                    is_chapter=(block.role == "chapter"),
                    is_front=(block.role == "front"),
                    preamble=block.preamble,
                    images=block.images,
                    comments=block.comments,
                )
            )

        # Add header/footer notes
        for htext in self._result.headers:
            note = ImportNote(
                note_type="header",
                source="document header",
                text=htext,
            )
            self._result.notes.append(note)

        for ftext in self._result.footers:
            note = ImportNote(
                note_type="footer",
                source="document footer",
                text=ftext,
            )
            self._result.notes.append(note)

        # Collect all comments, and flag the ones that could not be
        # anchored to a paragraph in the document
        for comment in self._comments.values():
            self._result.comments.append(comment)

        # Collect all images that are actually used in the document
        for scene in self._result.scenes:
            self._result.images.extend(scene.images)

    def _parse_paragraph(self, para: ET.Element, index: int) -> Optional[dict]:
        """Parse a single paragraph element and return its content."""
        # Get paragraph style
        style = "Normal"
        ppr = para.find(_wtag("pPr"))
        if ppr is not None:
            pstyle = ppr.find(_wtag("pStyle"))
            if pstyle is not None:
                style = pstyle.get(f"{{{W_NS}}}val", "Normal")

        # Extract text from all runs
        text_parts: list[str] = []
        image_rids: list[str] = []
        image_offsets: list[int] = []
        footnote_ids: list[str] = []
        text_len = 0

        for run in para.iter(_wtag("r")):
            # Check for image. Images are referenced from a DrawingML
            # blip element, or from a legacy VML image element.
            embed = ""
            drawing = run.find(_wtag("drawing"))
            if drawing is not None:
                blip = drawing.find(".//" + _atag("blip"))
                if blip is not None:
                    embed = blip.get(_rtag("embed")) or blip.get(_rtag("link")) or ""
            else:
                pict = run.find(_wtag("pict"))
                if pict is not None:
                    image = pict.find(".//" + _vtag("imagedata"))
                    if image is not None:
                        embed = image.get(_rtag("id")) or ""
            if embed:
                image_rids.append(embed)
                image_offsets.append(text_len)

            # Check for footnote reference
            fn_ref = run.find(_wtag("footnoteReference"))
            if fn_ref is not None:
                fn_id = fn_ref.get(f"{{{W_NS}}}id", "")
                footnote_ids.append(fn_id)
                text_parts.append(f"[FOOTNOTE:{fn_id}]")
                text_len += len(text_parts[-1])

            # Extract text elements
            for t_elem in run.findall(_wtag("t")):
                t_text = t_elem.text or ""
                text_parts.append(t_text)
                text_len += len(t_text)

            # Check for line break
            if run.find(_wtag("br")) is not None:
                text_parts.append(nwShortcode.BREAK)
                text_len += len(nwShortcode.BREAK)

            # Check for tab
            if run.find(_wtag("tab")) is not None:
                text_parts.append("    ")
                text_len += 4

        full_text = "".join(text_parts)

        # Resolve the comments anchored to this paragraph
        comments = self._anchorComments(para, index)

        # Build the image entries for this paragraph
        images: list[ImportImage] = []
        for rid, offset in zip(image_rids, image_offsets):
            base = self._images.get(rid)
            if base is None:
                logger.warning("Image '%s' is missing from the document", rid)
                continue
            context = self._contextText(full_text, offset)
            images.append(
                ImportImage(
                    rid=base.rid,
                    filename=base.filename,
                    data=base.data,
                    mime=base.mime,
                    img_id=self._makeImageId(base.data),
                    paragraph=index,
                    offset=offset,
                    context=context,
                )
            )

        return {
            "style": style,
            "text": full_text,
            "images": images,
            "footnotes": footnote_ids,
            "comments": comments,
        }

    def _anchorComments(self, para: ET.Element, index: int) -> list[ImportComment]:
        """Return the comments anchored to a paragraph.

        A comment is anchored to the paragraph where its comment range
        starts. If the comment has no range, but only a reference, it is
        anchored to the paragraph holding the reference.
        """
        anchors: list[str] = []
        for tag in ("commentRangeStart", "commentReference"):
            for elem in para.iter(_wtag(tag)):
                cmt_id = elem.get(f"{{{W_NS}}}id", "")
                if cmt_id and cmt_id not in anchors:
                    anchors.append(cmt_id)

        comments: list[ImportComment] = []
        for cmt_id in anchors:
            if cmt_id in self._anchored:
                continue
            comment = self._comments.get(cmt_id)
            if comment is None:
                continue
            comment.paragraph = index
            self._anchored.add(cmt_id)
            comments.append(comment)

        return comments

    def _markerLines(self, para_result: dict) -> list[str]:
        """Return the marker lines for a paragraph.

        Comments are added as synopsis comments on the line just before
        the paragraph they are anchored to. Images are added as image
        markers with the image ID and the position of the image.
        """
        lines: list[str] = []
        for comment in para_result["comments"]:
            lines.append(f"{COMMENT_KEY} {self._commentText(comment)}")
            # Synopsis comments are separated from the text they precede
            lines.append("")
        for image in para_result["images"]:
            context = _quoteText(image.context)
            lines.append(
                f"{IMAGE_KEY} {image.img_id} "
                f"paragraph={image.paragraph} offset={image.offset} "
                f'context="{context}"'
            )
        return lines

    def _makeImageId(self, data: bytes) -> str:
        """Return a stable ID for an image."""
        self._imageCount += 1
        digest = hashlib.sha256(data).hexdigest()[:8]
        return f"img_{digest}_{self._imageCount:03d}"

    @staticmethod
    def _contextText(text: str, offset: int, width: int = IMAGE_CONTEXT) -> str:
        """Return the text surrounding a given offset in a paragraph."""
        start = max(0, offset - width)
        end = min(len(text), offset + width)
        return _flatten(text[start:end])

    @staticmethod
    def _commentText(comment: ImportComment) -> str:
        """Return the text of a comment as a single line."""
        text = _flatten(comment.text)
        author = _flatten(comment.author)
        if author and author.lower() != "unknown":
            return f"{author}: {text}" if text else f"{author}:"
        return text

    def _parse_comments(self) -> None:
        """Parse comments from comments.xml.

        The comments are not converted into documents. They are instead
        inserted into the text of the document at the position where they
        were anchored in the Word document.
        """
        xml_text = self._read_xml("word/comments.xml")
        if not xml_text:
            return
        try:
            root = ET.fromstring(xml_text)
            for comment in root.findall(_wtag("comment")):
                cmt_id = comment.get(f"{{{W_NS}}}id", "")
                author = comment.get(f"{{{W_NS}}}author", "Unknown")
                date = comment.get(f"{{{W_NS}}}date", "")
                text = self._extract_comment_text(comment)
                self._comments[cmt_id] = ImportComment(
                    cmt_id=cmt_id,
                    author=author,
                    date=date,
                    text=text,
                )
        except ET.ParseError:
            logger.warning("Could not parse comments.xml")

    def _extract_comment_text(self, element: ET.Element) -> str:
        """Extract the text of a comment element."""
        paras = element.findall(_wtag("p"))
        if paras:
            return " ".join(
                _flatten(self._extract_text_from_element(para)) for para in paras
            ).strip()
        return self._extract_text_from_element(element)

    def _parse_footnotes(self) -> None:
        """Parse footnotes from footnotes.xml."""
        xml_text = self._read_xml("word/footnotes.xml")
        if not xml_text:
            return
        try:
            root = ET.fromstring(xml_text)
            for footnote in root.findall(_wtag("footnote")):
                fn_id = footnote.get(f"{{{W_NS}}}id", "")
                fn_type = footnote.get(f"{{{W_NS}}}type", "")
                if fn_type in ("separator", "continuationSeparator"):
                    continue
                text = self._extract_text_from_element(footnote)
                note = ImportNote(
                    note_type="footnote",
                    source=f"footnote id={fn_id}",
                    text=text,
                )
                self._result.notes.append(note)
                self._result.footnotes.append(text)
        except ET.ParseError:
            logger.warning("Could not parse footnotes.xml")

    def _extract_text_from_xml(self, xml_text: str) -> str:
        """Extract all text from an XML string."""
        try:
            root = ET.fromstring(xml_text)
            return self._extract_text_from_element(root)
        except ET.ParseError:
            return ""

    def _extract_text_from_element(self, element: ET.Element) -> str:
        """Recursively extract all text from an XML element."""
        parts: list[str] = []
        if element.text:
            parts.append(element.text)
        for child in element:
            parts.append(self._extract_text_from_element(child))
            if child.tail:
                parts.append(child.tail)
        return "".join(parts)

    @staticmethod
    def _guess_mime(filename: str) -> str:
        """Guess MIME type from filename extension."""
        ext = Path(filename).suffix.lower()
        mime_map = {
            ".jpeg": "image/jpeg",
            ".jpg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".tiff": "image/tiff",
            ".bmp": "image/bmp",
        }
        return mime_map.get(ext, "application/octet-stream")
