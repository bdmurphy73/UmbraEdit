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

# Dublin Core namespaces, used by the core document properties
DC_NS = "http://purl.org/dc/elements/1.1/"


def _wtag(tag: str) -> str:
    """Return the namespaced tag for the w namespace."""
    return f"{{{W_NS}}}{tag}"


def _rtag(tag: str) -> str:
    """Return the namespaced tag for the r namespace."""
    return f"{{{R_NS}}}{tag}"


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


def _styleKey(style: str) -> str:
    """Normalise a Word paragraph style name for style map lookups."""
    return re.sub(r"[\s\-_]+", "", style).lower()


def _cleanHeading(text: str) -> str:
    """Clean up a heading string by stripping markers and extra spaces."""
    text = _MARKER.sub("", text)
    text = _ANGLE.sub("", text)
    return " ".join(text.split())


@dataclass
class ImportImage:
    """Information about an image found in the Word document."""

    rid: str
    filename: str
    data: bytes
    mime: str


@dataclass
class ImportNote:
    """A note capturing a non-translatable item from the Word document."""

    note_type: str       # "image", "header", "footer", "comment", "footnote"
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


@dataclass
class _Block:
    """Internal container for a block of parsed document content."""

    role: str
    heading: str
    level: int
    style: str = "Normal"
    lines: list[str] = field(default_factory=list)


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
    comments: list[str] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)


class FromDocxDocument:
    """Core: Convert a Word DOCX/DOCM file into UmbraEdit import data.

    Parses the WordprocessingML XML inside a .docm or .docx file and
    extracts text content, headings, and non-translatable items
    (images, headers, footers, comments, footnotes) into notes.
    """

    __slots__ = ("_file_path", "_footers", "_headers", "_images", "_rels", "_result", "_zip")

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._zip: Optional[ZipFile] = None
        self._result = ImportResult()
        self._rels: dict[str, str] = {}
        self._images: dict[str, bytes] = {}
        self._headers: dict[str, str] = {}
        self._footers: dict[str, str] = {}

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
            self._parse_document()
            self._parse_comments()
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
                    self._images[rid] = data
                    self._result.images.append(
                        ImportImage(rid=rid, filename=target, data=data, mime=mime)
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

        def closeBlock() -> None:
            """Close the current block and add it to the block list."""
            nonlocal current
            if current is not None:
                blocks.append(current)
                current = None

        for para in body.findall(_wtag("p")):
            para_result = self._parse_paragraph(para)
            if para_result is None:
                continue

            style = para_result["style"]
            text = para_result["text"]
            role = STYLE_MAP.get(_styleKey(style), "body")

            # Collect non-translatable items as notes (images)
            if para_result["images"]:
                for img_rid in para_result["images"]:
                    img = next((i for i in self._result.images if i.rid == img_rid), None)
                    if img:
                        note = ImportNote(
                            note_type="image",
                            source=f"paragraph style={style}",
                            text=f"Image: {img.filename}",
                            data=img.data,
                            mime=img.mime,
                        )
                        self._result.notes.append(note)

            # Handle the document title. It opens a front matter block,
            # and is also used as the project title.
            if role == "title":
                title = _cleanHeading(text)
                if title and not self._result.title:
                    self._result.title = title
                closeBlock()
                current = _Block("front", title or "Title Page", LEVEL_FRONT, style)
                continue

            # Handle the subtitle. It is the author name, and is kept as
            # a line of text in the current block.
            if role == "subtitle":
                subtitle = _cleanHeading(text)
                if subtitle and not self._result.author:
                    self._result.author = subtitle
                if current is None:
                    current = _Block("front", "Title Page", LEVEL_FRONT, style)
                if subtitle:
                    current.lines.append(subtitle)
                    current.lines.append("")
                continue

            # Handle chapter headings. These open a new chapter.
            if role == "chapter":
                heading = _cleanHeading(text)
                closeBlock()
                chapterHeading = heading or f"Chapter {len(blocks) + 1}"
                sceneCount = 0
                current = _Block("chapter", chapterHeading, LEVEL_CHAPTER, style)
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
                continue

            # Regular content paragraphs
            if text.strip():
                if current is None:
                    current = _Block("front", "Front Matter", LEVEL_FRONT, style)
                current.lines.append(text)
                current.lines.append("")

        # Save the last block
        closeBlock()

        # Convert the blocks into scenes. Blocks without any text are
        # dropped, as they only hold empty section breaks.
        for block in blocks:
            text = "\n".join(block.lines).strip()
            if not text:
                continue
            self._result.scenes.append(
                ImportScene(
                    heading=block.heading,
                    level=block.level,
                    text=text,
                    style=block.style,
                    is_chapter=(block.role == "chapter"),
                    is_front=(block.role == "front"),
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

        # Add image notes for images found in the document
        for img in self._result.images:
            note = ImportNote(
                note_type="image",
                source=f"image file: {img.filename}",
                text=f"Image: {img.filename}",
                data=img.data,
                mime=img.mime,
            )
            self._result.notes.append(note)

    def _parse_paragraph(self, para: ET.Element) -> Optional[dict]:
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
        footnote_ids: list[str] = []
        comment_ids: list[str] = []

        for run in para.findall(_wtag("r")):
            # Check for image
            drawing = run.find(_wtag("drawing"))
            if drawing is not None:
                blip = drawing.find(".//" + _wtag("blip"))
                if blip is not None:
                    embed = blip.get(_rtag("embed"))
                    if embed:
                        image_rids.append(embed)
                        text_parts.append(f"[IMAGE:{embed}]")

            # Check for footnote reference
            fn_ref = run.find(_wtag("footnoteReference"))
            if fn_ref is not None:
                fn_id = fn_ref.get(f"{{{W_NS}}}id", "")
                footnote_ids.append(fn_id)
                text_parts.append(f"[FOOTNOTE:{fn_id}]")

            # Check for comment reference
            cmt_ref = run.find(_wtag("commentReference"))
            if cmt_ref is not None:
                cmt_id = cmt_ref.get(f"{{{W_NS}}}id", "")
                comment_ids.append(cmt_id)
                text_parts.append(f"[COMMENT:{cmt_id}]")

            # Extract text elements
            for t_elem in run.findall(_wtag("t")):
                t_text = t_elem.text or ""
                # Check for xml:space preserve
                if t_elem.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve":
                    text_parts.append(t_text)
                else:
                    text_parts.append(t_text)

            # Check for line break
            if run.find(_wtag("br")) is not None:
                text_parts.append(nwShortcode.BREAK)

            # Check for tab
            if run.find(_wtag("tab")) is not None:
                text_parts.append("    ")

        full_text = "".join(text_parts)

        return {
            "style": style,
            "text": full_text,
            "images": image_rids,
            "footnotes": footnote_ids,
            "comments": comment_ids,
        }

    def _parse_comments(self) -> None:
        """Parse comments from comments.xml."""
        xml_text = self._read_xml("word/comments.xml")
        if not xml_text:
            return
        try:
            root = ET.fromstring(xml_text)
            for comment in root.findall(_wtag("comment")):
                cmt_id = comment.get(f"{{{W_NS}}}id", "")
                author = comment.get(f"{{{W_NS}}}author", "Unknown")
                date = comment.get(f"{{{W_NS}}}date", "")
                text = self._extract_text_from_element(comment)
                note_text = f"Comment by {author} ({date}): {text}" if date else f"Comment by {author}: {text}"
                note = ImportNote(
                    note_type="comment",
                    source=f"comment id={cmt_id}",
                    text=note_text,
                )
                self._result.notes.append(note)
                self._result.comments.append(note_text)
        except ET.ParseError:
            logger.warning("Could not parse comments.xml")

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
