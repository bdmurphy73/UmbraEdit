"""
UmbraEdit - Word DOCX/DOCM Import Converter
============================================

This file is a part of UmbraEdit.

Copyright (C) 2018 Veronica Berglyd Olsen and UmbraEdit contributors.

Additional Copyright (C) 2026 B.D. Murphy.
Changes: Added Word DOCX/DOCM import converter for migrating Word
documents into UmbraEdit projects. Non-translatable items (images,
headers, footers, comments, footnotes) are captured as notes.

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
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZipFile, is_zipfile

from umbraedit import CONFIG
from umbraedit.constants import (
    nwShortcode,
    nwStyles,
)
from umbraedit.enum import nwItemClass, nwItemLayout

if TYPE_CHECKING:
    from pathlib import Path as _Path

logger = logging.getLogger(__name__)

# WordprocessingML namespace
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _wtag(tag: str) -> str:
    """Return the namespaced tag for the w namespace."""
    return f"{{{W_NS}}}{tag}"


def _rtag(tag: str) -> str:
    """Return the namespaced tag for the r namespace."""
    return f"{{{R_NS}}}{tag}"


# Mapping of Word paragraph styles to UmbraEdit heading levels
# Style name -> (UmbraEdit heading level, is chapter)
STYLE_MAP: dict[str, tuple[int, bool]] = {
    "Title": (0, False),      # Book title (front matter)
    "Subtitle": (0, False),   # Subtitle (front matter)
    "WAChapter": (1, True),   # Chapter heading -> new chapter folder
    "WAChpNrm": (3, False),   # Chapter-normal text (scene content)
    "WANChpPgr": (3, False),  # Chapter paragraph (scene content)
    "WANrmlPgr": (3, False),  # Normal paragraph (scene content)
    "WASection": (4, False),  # Section break within a chapter
    "NoSpacing": (3, False),  # Normal paragraph
    "TOC1": (3, False),       # Table of contents entry
    "TOCHeading": (2, False), # TOC heading
}


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
    data: bytes | None = None  # Raw image data, if applicable
    mime: str | None = None    # MIME type, if applicable


@dataclass
class ImportScene:
    """A scene document entry from the Word document."""

    heading: str
    level: int
    text: str
    style: str
    is_chapter: bool = False  # True if this is a chapter heading (folder)


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

    __slots__ = ("_file_path", "_zip", "_result", "_rels", "_images", "_headers", "_footers")

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._zip: ZipFile | None = None
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

        # Track current chapter/scene
        current_chapter: str | None = None
        current_text: list[str] = []
        current_style: str | None = None
        current_level: int = 0

        def save_current_chapter() -> None:
            """Save the accumulated chapter content as an ImportScene."""
            nonlocal current_chapter, current_text, current_style, current_level
            if current_chapter is None:
                return
            # Split text at >>> section breaks into multiple scenes
            full_text = "\n".join(current_text)
            parts = full_text.split(">>>")
            for idx, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                if idx == 0:
                    # First part gets the chapter heading
                    scene_heading = current_chapter
                else:
                    # Subsequent parts are scenes within the chapter
                    scene_heading = f"{current_chapter} - Scene {idx}"
                self._result.scenes.append(
                    ImportScene(
                        heading=scene_heading,
                        level=current_level,
                        text=part,
                        style=current_style or "Normal",
                        is_chapter=(idx == 0),  # Only first part is the chapter folder
                    )
                )
            current_chapter = None
            current_text = []
            current_style = None
            current_level = 0

        for para in body.findall(_wtag("p")):
            para_result = self._parse_paragraph(para)
            if para_result is None:
                continue

            style = para_result["style"]
            text = para_result["text"]
            level, is_chapter = STYLE_MAP.get(style, (3, False))

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

            # Handle chapter headings - start a new chapter
            if is_chapter:
                # Save previous chapter if any
                save_current_chapter()

                # Clean up chapter heading - remove comment/footnote markers
                clean_heading = re.sub(r"\[(?:COMMENT|FOOTNOTE):\w+\]", "", text.strip())
                current_chapter = clean_heading or f"Chapter {len(self._result.scenes) + 1}"
                current_text = []
                current_style = style
                current_level = level

                # Add chapter title
                if text.strip():
                    current_text.append(f"# {text.strip()}")
                    current_text.append("")

            # Handle section breaks - split into separate scenes
            elif style == "WASection":
                current_text.append(">>>")
                current_text.append("")

            # Handle title/subtitle (front matter)
            elif style in ("Title", "Subtitle"):
                if not self._result.title and style == "Title":
                    self._result.title = text.strip()
                elif style == "Subtitle" and not self._result.author:
                    self._result.author = text.strip()
                current_text.append(f"{'#' * (level + 1)} {text.strip()}")
                current_text.append("")

            # Regular content paragraphs
            else:
                if text.strip():
                    current_text.append(text)
                    current_text.append("")

        # Save the last chapter
        save_current_chapter()

        # If no chapters were found, treat all content as one scene
        if not self._result.scenes and current_text:
            self._result.scenes.append(
                ImportScene(
                    heading="Imported Content",
                    level=3,
                    text="\n".join(current_text),
                    style="Normal",
                    is_chapter=False,
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

    def _parse_paragraph(self, para: ET.Element) -> dict | None:
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
