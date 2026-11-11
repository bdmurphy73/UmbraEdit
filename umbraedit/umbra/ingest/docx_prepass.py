"""
UmbraEdit - DOCX Pre-pass Stage
================================

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
import zipfile

from dataclasses import dataclass, field
from typing import Any

from lxml import etree  # type: ignore[import]

from umbraedit.umbra.ingest.docx_intake import IntakeResult

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


@dataclass(frozen=True)
class ParagraphRecord:
    """A record of a single paragraph from the pre-pass."""

    index: int
    text: str
    style_id: str
    style_name: str
    alignment: str | None = None
    outline_level: int | None = None
    page_break_before: bool = False
    section_break: str | None = None
    list_membership: str | None = None
    image_refs: list[str] = field(default_factory=list)
    run_formatting: list[dict[str, Any]] = field(default_factory=list)
    footnote_refs: list[str] = field(default_factory=list)
    comment_refs: list[str] = field(default_factory=list)
    bookmark_starts: list[str] = field(default_factory=list)
    bookmark_ends: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PrepassResult:
    """Result of the pre-pass stage."""

    paragraphs: list[ParagraphRecord]
    styles: dict[str, dict[str, Any]]  # style_id -> {name, type, based_on, next, ...}
    numbering: dict[str, Any]
    comments: dict[str, dict[str, Any]]  # comment_id -> {author, date, text}
    footnotes: dict[str, str]  # footnote_id -> text
    doc_props: dict[str, Any]  # core properties
    relationships: dict[str, str]  # rId -> target
    images: list[dict[str, Any]]  # list of image info dicts with rid, filename, data, mime


def _extract_text(elem: etree._Element) -> str:
    """Extract all text from an lxml element."""
    return "".join(elem.itertext())


def _parse_style_name(style_elem: etree._Element) -> tuple[str, str]:
    """Parse style element to get (style_id, style_name)."""
    style_id = style_elem.get(f"{{{W_NS}}}styleId", "")
    name_elem = style_elem.find(f".//{{{W_NS}}}name")
    style_name = name_elem.get(f"{{{W_NS}}}val", "") if name_elem is not None else ""
    return style_id, style_name


def _parse_run_formatting(run: etree._Element) -> list[dict[str, Any]]:
    """Extract formatting from a run element."""
    formatting = []
    rpr = run.find(f".//{{{W_NS}}}rPr")
    if rpr is None:
        return formatting

    for child in rpr:
        tag = child.tag
        if tag.endswith("b"):  # bold
            formatting.append({"type": "bold", "value": True})
        elif tag.endswith("i"):  # italic
            formatting.append({"type": "italic", "value": True})
        elif tag.endswith("u"):  # underline
            formatting.append({"type": "underline", "value": child.get(f"{{{W_NS}}}val", "single")})
        elif tag.endswith("strike"):  # strikethrough
            formatting.append({"type": "strike", "value": True})
        elif tag.endswith("sz"):  # font size
            formatting.append({"type": "font_size", "value": child.get(f"{{{W_NS}}}val", "")})
        elif tag.endswith("rFonts"):  # font family
            formatting.append({"type": "font_family", "value": child.get(f"{{{W_NS}}}ascii", "")})
        elif tag.endswith("color"):  # font color
            formatting.append({"type": "color", "value": child.get(f"{{{W_NS}}}val", "")})
        elif tag.endswith("highlight"):  # highlight
            formatting.append({"type": "highlight", "value": child.get(f"{{{W_NS}}}val", "")})
        elif tag.endswith("smallCaps"):  # small caps
            formatting.append({"type": "small_caps", "value": True})
        elif tag.endswith("caps"):  # all caps
            formatting.append({"type": "all_caps", "value": True})
        elif tag.endswith("vertAlign"):  # superscript/subscript
            formatting.append({"type": "vert_align", "value": child.get(f"{{{W_NS}}}val", "")})

    return formatting


class DocxPrepass:
    """Pre-pass stage: read DOCX XML and extract paragraph records."""

    @staticmethod
    def _guess_mime(filename: str) -> str:
        """Guess MIME type from filename extension."""
        from pathlib import Path
        ext = Path(filename).suffix.lower()
        mime_map = {
            ".jpeg": "image/jpeg",
            ".jpg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".tiff": "image/tiff",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }
        return mime_map.get(ext, "application/octet-stream")
    """Pre-pass stage: read DOCX XML and extract paragraph records."""

    def process(self, intake: IntakeResult) -> PrepassResult:
        """Run the pre-pass on a DOCX file."""
        logger.info("Pre-pass: reading %s", intake.file_path)

        with zipfile.ZipFile(intake.file_path, "r") as zf:
            # Read styles.xml
            styles = self._parse_styles(zf)

            # Read numbering.xml
            numbering = self._parse_numbering(zf)

            # Read comments.xml
            comments = self._parse_comments(zf)

            # Read footnotes.xml
            footnotes = self._parse_footnotes(zf)

            # Read docProps/core.xml
            doc_props = self._parse_doc_props(zf)

            # Read document.xml.rels
            relationships = self._parse_relationships(zf)

            # Parse document.xml paragraphs
            paragraphs = self._parse_document(
                zf,
                styles,
                numbering,
                relationships,
            )

            # Extract images from relationships
            images = self._extract_images(zf, relationships)

        return PrepassResult(
            paragraphs=paragraphs,
            styles=styles,
            numbering=numbering,
            comments=comments,
            footnotes=footnotes,
            doc_props=doc_props,
            relationships=relationships,
            images=images,
        )

    def _parse_styles(self, zf: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
        """Parse styles.xml into a dict."""
        styles: dict[str, dict[str, Any]] = {}
        try:
            content = zf.read("word/styles.xml")
            root = etree.fromstring(content)
        except (KeyError, etree.XMLSyntaxError):
            return styles

        for style in root.findall(f".//{{{W_NS}}}style"):
            style_id, style_name = _parse_style_name(style)
            if not style_id:
                continue

            style_info = {
                "id": style_id,
                "name": style_name,
                "type": style.get(f"{{{W_NS}}}type", "paragraph"),
                "based_on": None,
                "next": None,
                "link": None,
                "ui_priority": None,
                "hidden": False,
                "locked": False,
            }

            # Parse style properties
            for child in style:
                tag = child.tag
                if tag.endswith("basedOn"):
                    style_info["based_on"] = child.get(f"{{{W_NS}}}val")
                elif tag.endswith("next"):
                    style_info["next"] = child.get(f"{{{W_NS}}}val")
                elif tag.endswith("link"):
                    style_info["link"] = child.get(f"{{{W_NS}}}val")
                elif tag.endswith("uiPriority"):
                    style_info["ui_priority"] = child.get(f"{{{W_NS}}}val")
                elif tag.endswith("hidden"):
                    style_info["hidden"] = child.get(f"{{{W_NS}}}val") == "true"
                elif tag.endswith("locked"):
                    style_info["locked"] = child.get(f"{{{W_NS}}}val") == "true"
                elif tag.endswith("pPr"):  # paragraph properties
                    style_info["pPr"] = self._parse_paragraph_properties(child)
                elif tag.endswith("rPr"):  # run properties
                    style_info["rPr"] = self._parse_run_properties(child)

            styles[style_id] = style_info

        return styles

    def _parse_paragraph_properties(self, elem: etree._Element) -> dict[str, Any]:
        """Extract paragraph properties from pPr element."""
        props: dict[str, Any] = {}
        for child in elem:
            tag = child.tag
            if tag.endswith("jc"):  # alignment
                props["alignment"] = child.get(f"{{{W_NS}}}val")
            elif tag.endswith("outlineLvl"):  # outline level
                props["outline_level"] = int(child.get(f"{{{W_NS}}}val", 0))
            elif tag.endswith("pageBreakBefore"):
                props["page_break_before"] = True
            elif tag.endswith("sectPr"):  # section properties
                props["section_break"] = self._parse_section_properties(child)
            elif tag.endswith("numPr"):  # numbering
                num_id = child.find(f".//{{{W_NS}}}numId")
                if num_id is not None:
                    props["num_id"] = num_id.get(f"{{{W_NS}}}val")
        return props

    def _parse_run_properties(self, elem: etree._Element) -> dict[str, Any]:
        """Extract run properties from rPr element."""
        props: dict[str, Any] = {}
        for child in elem:
            tag = child.tag
            if tag.endswith("b"):
                props["bold"] = True
            elif tag.endswith("i"):
                props["italic"] = True
            elif tag.endswith("u"):
                props["underline"] = child.get(f"{{{W_NS}}}val", "single")
            elif tag.endswith("strike"):
                props["strike"] = True
            elif tag.endswith("sz"):
                props["font_size"] = child.get(f"{{{W_NS}}}val")
            elif tag.endswith("rFonts"):
                props["font_family"] = child.get(f"{{{W_NS}}}ascii")
            elif tag.endswith("color"):
                props["color"] = child.get(f"{{{W_NS}}}val")
            elif tag.endswith("highlight"):
                props["highlight"] = child.get(f"{{{W_NS}}}val")
            elif tag.endswith("smallCaps"):
                props["small_caps"] = True
            elif tag.endswith("caps"):
                props["all_caps"] = True
            elif tag.endswith("vertAlign"):
                props["vert_align"] = child.get(f"{{{W_NS}}}val")
        return props

    def _parse_section_properties(self, elem: etree._Element) -> str | None:
        """Extract section break type from sectPr."""
        for child in elem:
            if child.tag.endswith("type"):
                return child.get(f"{{{W_NS}}}val")
        return None

    def _parse_numbering(self, zf: zipfile.ZipFile) -> dict[str, Any]:
        """Parse numbering.xml."""
        numbering: dict[str, Any] = {}
        try:
            content = zf.read("word/numbering.xml")
            root = etree.fromstring(content)
        except (KeyError, etree.XMLSyntaxError):
            return numbering

        # Parse abstractNum definitions
        abstract_nums: dict[str, Any] = {}
        for abstract_num in root.findall(f".//{{{W_NS}}}abstractNum"):
            an_id = abstract_num.get(f"{{{W_NS}}}abstractNumId")
            if not an_id:
                continue
            abstract_nums[an_id] = self._parse_abstract_num(abstract_num)

        # Parse num instances
        for num in root.findall(f".//{{{W_NS}}}num"):
            num_id = num.get(f"{{{W_NS}}}numId")
            if not num_id:
                continue
            abstract_ref = num.find(f".//{{{W_NS}}}abstractNumId")
            if abstract_ref is not None:
                an_id = abstract_ref.get(f"{{{W_NS}}}val")
                numbering[num_id] = {
                    "abstract_num_id": an_id,
                    "levels": abstract_nums.get(an_id, {}),
                }

        return numbering

    def _parse_abstract_num(self, abstract_num: etree._Element) -> dict[int, dict[str, Any]]:
        """Parse an abstractNum element."""
        levels: dict[int, dict[str, Any]] = {}
        for lvl in abstract_num.findall(f".//{{{W_NS}}}lvl"):
            lvl_idx = lvl.get(f"{{{W_NS}}}ilvl")
            if lvl_idx is None:
                continue
            idx = int(lvl_idx)
            levels[idx] = {
                "start": lvl.find(f".//{{{W_NS}}}start"),
                "num_fmt": lvl.find(f".//{{{W_NS}}}numFmt"),
                "lvl_text": lvl.find(f".//{{{W_NS}}}lvlText"),
                "lvl_pic_bullet": lvl.find(f".//{{{W_NS}}}lvlPicBulletId"),
            }
        return levels

    def _parse_comments(self, zf: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
        """Parse comments.xml."""
        comments: dict[str, dict[str, Any]] = {}
        try:
            content = zf.read("word/comments.xml")
            root = etree.fromstring(content)
        except (KeyError, etree.XMLSyntaxError):
            return comments

        for comment in root.findall(f".//{{{W_NS}}}comment"):
            cmt_id = comment.get(f"{{{W_NS}}}id")
            if not cmt_id:
                continue
            author = comment.get(f"{{{W_NS}}}author", "Unknown")
            date = comment.get(f"{{{W_NS}}}date", "")
            text = _extract_text(comment)
            comments[cmt_id] = {
                "author": author,
                "date": date,
                "text": text,
            }
        return comments

    def _parse_footnotes(self, zf: zipfile.ZipFile) -> dict[str, str]:
        """Parse footnotes.xml."""
        footnotes: dict[str, str] = {}
        try:
            content = zf.read("word/footnotes.xml")
            root = etree.fromstring(content)
        except (KeyError, etree.XMLSyntaxError):
            return footnotes

        for footnote in root.findall(f".//{{{W_NS}}}footnote"):
            fn_id = footnote.get(f"{{{W_NS}}}id")
            if not fn_id:
                continue
            fn_type = footnote.get(f"{{{W_NS}}}type", "")
            if fn_type in ("separator", "continuationSeparator"):
                continue
            text = _extract_text(footnote)
            footnotes[fn_id] = text
        return footnotes

    def _parse_doc_props(self, zf: zipfile.ZipFile) -> dict[str, Any]:
        """Parse docProps/core.xml."""
        props: dict[str, Any] = {}
        try:
            content = zf.read("docProps/core.xml")
            root = etree.fromstring(content)
        except (KeyError, etree.XMLSyntaxError):
            return props

        for child in root:
            # Remove namespace
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag in ("title", "subject", "creator", "keywords", "description",
                       "lastModifiedBy", "revision", "created", "modified",
                       "category", "contentStatus", "language"):
                props[tag] = child.text

        return props

    def _parse_relationships(self, zf: zipfile.ZipFile) -> dict[str, str]:
        """Parse document.xml.rels."""
        rels: dict[str, str] = {}
        try:
            content = zf.read("word/_rels/document.xml.rels")
            root = etree.fromstring(content)
        except (KeyError, etree.XMLSyntaxError):
            return rels

        rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        for rel in root.findall(f".//{{{rel_ns}}}Relationship"):
            rid = rel.get("Id", "")
            target = rel.get("Target", "")
            if rid and target:
                rels[rid] = target
        return rels

    def _extract_images(self, zf: zipfile.ZipFile, relationships: dict[str, str]) -> list[dict[str, Any]]:
        """Extract image information from relationships."""
        images: list[dict[str, Any]] = []
        for rid, target in relationships.items():
            if "image" in target.lower():
                target_path = f"word/{target}" if not target.startswith("word/") else target
                try:
                    data = zf.read(target_path)
                    mime = self._guess_mime(target)
                    images.append({
                        "rid": rid,
                        "filename": target,
                        "data": data,
                        "mime": mime,
                    })
                except KeyError:
                    logger.warning("Could not read image: %s", target_path)
        return images

    def _parse_document(
        self,
        zf: zipfile.ZipFile,
        styles: dict[str, dict[str, Any]],
        numbering: dict[str, Any],
        relationships: dict[str, str],
    ) -> list[ParagraphRecord]:
        """Parse document.xml into paragraph records."""
        paragraphs: list[ParagraphRecord] = []
        try:
            content = zf.read("word/document.xml")
            root = etree.fromstring(content)
        except (KeyError, etree.XMLSyntaxError):
            return paragraphs

        body = root.find(f".//{{{W_NS}}}body")
        if body is None:
            return paragraphs

        for idx, para in enumerate(body.findall(f".//{{{W_NS}}}p")):
            record = self._parse_paragraph(
                para,
                idx,
                styles,
                numbering,
                relationships,
            )
            if record:
                paragraphs.append(record)

        return paragraphs

    def _parse_paragraph(
        self,
        para: etree._Element,
        idx: int,
        styles: dict[str, dict[str, Any]],
        numbering: dict[str, Any],
        relationships: dict[str, str],
    ) -> ParagraphRecord | None:
        """Parse a single paragraph element."""
        # Get paragraph properties
        ppr = para.find(f".//{{{W_NS}}}pPr")
        style_id = ""
        style_name = ""
        alignment = None
        outline_level = None
        page_break_before = False
        section_break = None
        list_membership = None
        bookmark_starts: list[str] = []
        bookmark_ends: list[str] = []

        if ppr is not None:
            # Style
            pstyle = ppr.find(f".//{{{W_NS}}}pStyle")
            if pstyle is not None:
                style_id = pstyle.get(f"{{{W_NS}}}val", "")
                style_info = styles.get(style_id, {})
                style_name = style_info.get("name", "")

            # Alignment
            jc = ppr.find(f".//{{{W_NS}}}jc")
            if jc is not None:
                alignment = jc.get(f"{{{W_NS}}}val")

            # Outline level (from paragraph properties)
            olvl = ppr.find(f".//{{{W_NS}}}outlineLvl")
            if olvl is not None:
                outline_level = int(olvl.get(f"{{{W_NS}}}val", 0))

            # Page break before
            if ppr.find(f".//{{{W_NS}}}pageBreakBefore") is not None:
                page_break_before = True

            # Section break
            sect_pr = ppr.find(f".//{{{W_NS}}}sectPr")
            if sect_pr is not None:
                type_elem = sect_pr.find(f".//{{{W_NS}}}type")
                if type_elem is not None:
                    section_break = type_elem.get(f"{{{W_NS}}}val")

            # Numbering/list
            num_pr = ppr.find(f".//{{{W_NS}}}numPr")
            if num_pr is not None:
                num_id_elem = num_pr.find(f".//{{{W_NS}}}numId")
                if num_id_elem is not None:
                    num_id = num_id_elem.get(f"{{{W_NS}}}val")
                    if num_id and num_id in numbering:
                        list_membership = f"list:{num_id}"

            # Bookmarks
            for bm_start in ppr.findall(f".//{{{W_NS}}}bookmarkStart"):
                name = bm_start.get(f"{{{W_NS}}}name")
                if name:
                    bookmark_starts.append(name)
            for bm_end in ppr.findall(f".//{{{W_NS}}}bookmarkEnd"):
                name = bm_end.get(f"{{{W_NS}}}name")
                if name:
                    bookmark_ends.append(name)

        # If outline_level not set from paragraph, check style's pPr
        if outline_level is None and style_id and style_id in styles:
            style_ppr = styles[style_id].get("pPr", {})
            if "outline_level" in style_ppr:
                outline_level = style_ppr["outline_level"]

        # Extract text and run formatting
        text_parts: list[str] = []
        image_refs: list[str] = []
        run_formatting: list[dict[str, Any]] = []
        footnote_refs: list[str] = []
        comment_refs: list[str] = []

        for run in para.findall(f".//{{{W_NS}}}r"):
            # Check for image
            drawing = run.find(f".//{{{W_NS}}}drawing")
            if drawing is not None:
                blip = drawing.find(f".//{{{W_NS}}}blip")
                if blip is not None:
                    embed = blip.get(f"{{{R_NS}}}embed")
                    if embed:
                        image_refs.append(embed)
                        text_parts.append(f"[IMAGE:{embed}]")

            # Check for footnote reference
            fn_ref = run.find(f".//{{{W_NS}}}footnoteReference")
            if fn_ref is not None:
                fn_id = fn_ref.get(f"{{{W_NS}}}id", "")
                if fn_id:
                    footnote_refs.append(fn_id)
                    text_parts.append(f"[FOOTNOTE:{fn_id}]")

            # Check for comment reference
            cmt_ref = run.find(f".//{{{W_NS}}}commentReference")
            if cmt_ref is not None:
                cmt_id = cmt_ref.get(f"{{{W_NS}}}id", "")
                if cmt_id:
                    comment_refs.append(cmt_id)
                    text_parts.append(f"[COMMENT:{cmt_id}]")

            # Extract text
            for t_elem in run.findall(f".//{{{W_NS}}}t"):
                t_text = t_elem.text or ""
                # Check for xml:space preserve
                space = t_elem.get("{http://www.w3.org/XML/1998/namespace}space")
                if space == "preserve":
                    text_parts.append(t_text)
                else:
                    text_parts.append(t_text)

            # Run formatting
            run_fmt = _parse_run_formatting(run)
            if run_fmt:
                run_formatting.extend(run_fmt)

            # Check for line break
            if run.find(f".//{{{W_NS}}}br") is not None:
                text_parts.append("\n")

            # Check for tab
            if run.find(f".//{{{W_NS}}}tab") is not None:
                text_parts.append("    ")

        full_text = "".join(text_parts).strip()

        return ParagraphRecord(
            index=idx,
            text=full_text,
            style_id=style_id,
            style_name=style_name,
            alignment=alignment,
            outline_level=outline_level,
            page_break_before=page_break_before,
            section_break=section_break,
            list_membership=list_membership,
            image_refs=image_refs,
            run_formatting=run_formatting,
            footnote_refs=footnote_refs,
            comment_refs=comment_refs,
            bookmark_starts=bookmark_starts,
            bookmark_ends=bookmark_ends,
        )
