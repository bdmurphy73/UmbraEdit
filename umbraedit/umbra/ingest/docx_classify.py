"""
UmbraEdit - DOCX Classify Stage
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
import re

from dataclasses import dataclass, field
from enum import Enum

from umbraedit.umbra.ingest.docx_convert import ConvertResult
from umbraedit.umbra.ingest.docx_prepass import ParagraphRecord, PrepassResult

logger = logging.getLogger(__name__)


class BlockKind(Enum):
    """Classification of a document block."""

    FRONT_MATTER = "front_matter"
    CHAPTER = "chapter"
    SCENE = "scene"
    BODY = "body"
    BACK_MATTER = "back_matter"
    NOTE = "note"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DocumentBlock:
    """A classified document block."""

    kind: BlockKind
    level: int = 0
    title: str = ""
    text: str = ""
    source_paragraphs: list[int] = field(default_factory=list)
    page_type: str | None = None  # For front/back matter


@dataclass(frozen=True)
class ClassifyResult:
    """Result of the classify stage."""

    blocks: list[DocumentBlock]
    chapter_count: int = 0
    scene_count: int = 0
    front_matter_count: int = 0
    back_matter_count: int = 0
    warnings: list[str] = field(default_factory=list)


# Keywords for front/back matter classification
FRONT_MATTER_KEYWORDS = {
    "title page": ["title", "author", "by"],
    "copyright": ["copyright", "©", "all rights reserved", "isbn"],
    "dedication": ["dedication", "dedicated to", "for "],
    "epigraph": ["epigraph", "quote"],
    "table of contents": ["contents", "table of contents"],
    "foreword": ["foreword"],
    "preface": ["preface"],
    "acknowledgments": ["acknowledgments", "acknowledgements"],
    "introduction": ["introduction"],
    "prologue": ["prologue"],
}

BACK_MATTER_KEYWORDS = {
    "epilogue": ["epilogue"],
    "afterword": ["afterword"],
    "about the author": ["about the author", "author bio", "biography"],
    "acknowledgments": ["acknowledgments", "acknowledgements"],
    "appendix": ["appendix"],
    "glossary": ["glossary"],
    "bibliography": ["bibliography", "references", "works cited"],
    "index": ["index"],
    "also by": ["also by", "other books by"],
}


def _normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_chapter_heading(text: str, style_name: str, outline_level: int | None) -> tuple[bool, int]:
    """Determine if a paragraph is a chapter heading.

    Returns (is_chapter, level)
    """
    # Check outline level first
    if outline_level is not None and 0 <= outline_level <= 3:
        return True, outline_level + 1

    # Check style name
    style_lower = style_name.lower()
    if "heading" in style_lower:
        # Try to extract number from "Heading 1", "Heading 2", etc.
        match = re.search(r"heading\s*(\d+)", style_lower)
        if match:
            return True, int(match.group(1))
        return True, 1

    # Check for "Chapter" or "Part" keywords
    text_lower = text.lower().strip()
    if re.match(r"^(chapter|part)\s+\d+", text_lower):
        return True, 1
    if re.match(r"^(chapter|part)\s+[ivxlcdm]+", text_lower, re.IGNORECASE):
        return True, 1

    # Scored guess: short line, centered/bold, followed by blank
    if len(text) < 100 and text.strip() and not text.endswith("."):
        # Could be a heading
        return True, 1

    return False, 0


def _classify_front_matter(text: str, title: str) -> str | None:
    """Classify front matter type."""
    normalized = _normalize_text(text)

    for page_type, keywords in FRONT_MATTER_KEYWORDS.items():
        for kw in keywords:
            if kw in normalized:
                return page_type
    return None


def _classify_back_matter(text: str) -> str | None:
    """Classify back matter type."""
    normalized = _normalize_text(text)

    for page_type, keywords in BACK_MATTER_KEYWORDS.items():
        for kw in keywords:
            if kw in normalized:
                return page_type
    return None


class DocxClassify:
    """Classify stage: classify each block as heading, front matter, body, etc."""

    def process(
        self,
        prepass: PrepassResult,
        convert: ConvertResult,
    ) -> ClassifyResult:
        """Classify all blocks in the document."""
        logger.info("Classify: analyzing %d paragraphs", len(prepass.paragraphs))

        blocks: list[DocumentBlock] = []
        warnings: list[str] = []

        # Track state
        in_front_matter = True
        in_back_matter = False
        chapter_count = 0
        scene_count = 0
        front_matter_count = 0
        back_matter_count = 0

        # Get Pandoc output for each paragraph (we'll use prepass paragraphs)
        # Since we don't have direct mapping, we'll use prepass text
        for idx, para in enumerate(prepass.paragraphs):
            text = para.text.strip()
            if not text:
                continue

            # Check for chapter heading
            is_chapter, level = _is_chapter_heading(
                text, para.style_name, para.outline_level
            )

            if is_chapter and in_front_matter:
                # First chapter ends front matter
                in_front_matter = False

            if is_chapter:
                chapter_count += 1
                blocks.append(DocumentBlock(
                    kind=BlockKind.CHAPTER,
                    level=level,
                    title=text,
                    text=text,
                    source_paragraphs=[idx],
                ))
                continue

            # Check for scene break
            if self._is_scene_break(text, para):
                scene_count += 1
                blocks.append(DocumentBlock(
                    kind=BlockKind.SCENE,
                    level=level,
                    title=f"Scene {scene_count}",
                    text=text,
                    source_paragraphs=[idx],
                ))
                continue

            # Check front matter
            if in_front_matter:
                page_type = _classify_front_matter(text, prepass.doc_props.get("title", ""))
                if page_type:
                    front_matter_count += 1
                    blocks.append(DocumentBlock(
                        kind=BlockKind.FRONT_MATTER,
                        level=0,
                        title=page_type.replace("_", " ").title(),
                        text=text,
                        source_paragraphs=[idx],
                        page_type=page_type,
                    ))
                    continue

            # Check back matter
            if not in_front_matter and not in_back_matter:
                page_type = _classify_back_matter(text)
                if page_type:
                    in_back_matter = True
                    back_matter_count += 1
                    blocks.append(DocumentBlock(
                        kind=BlockKind.BACK_MATTER,
                        level=0,
                        title=page_type.replace("_", " ").title(),
                        text=text,
                        source_paragraphs=[idx],
                        page_type=page_type,
                    ))
                    continue

            if in_back_matter:
                back_matter_count += 1
                blocks.append(DocumentBlock(
                    kind=BlockKind.BACK_MATTER,
                    level=0,
                    title="Back Matter",
                    text=text,
                    source_paragraphs=[idx],
                ))
                continue

            # Default to body
            blocks.append(DocumentBlock(
                kind=BlockKind.BODY,
                level=0,
                title="",
                text=text,
                source_paragraphs=[idx],
            ))

        # Check for no chapters
        if chapter_count == 0:
            warnings.append("No chapter headings found (ingestNoHeadings)")

        # Check for empty scenes
        for block in blocks:
            if block.kind == BlockKind.SCENE and not block.text.strip():
                warnings.append(f"Empty scene at paragraph {block.source_paragraphs}")

        return ClassifyResult(
            blocks=blocks,
            chapter_count=chapter_count,
            scene_count=scene_count,
            front_matter_count=front_matter_count,
            back_matter_count=back_matter_count,
            warnings=warnings,
        )

    def _is_scene_break(self, text: str, para: ParagraphRecord) -> bool:
        """Check if a paragraph is a scene break."""
        # Explicit scene break markers
        stripped = text.strip()
        if stripped in ("***", "* * *", "###", "---"):
            return True

        # Centered ornaments
        if para.alignment == "center" and len(stripped) < 20:
            # Check for common ornaments
            if re.match(r"^[\*\~\-\+\•\♦\★\☆\❖\✦]+$", stripped):
                return True

        # Empty paragraph with section break
        if not stripped and para.section_break:
            return True

        return False
