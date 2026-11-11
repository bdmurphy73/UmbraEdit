"""
UmbraEdit - Translation Guide
=============================

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
from typing import Any, ClassVar

from umbraedit.constants import nwKeyWords

logger = logging.getLogger(__name__)

# Regular expressions for parsing guide documents
GUIDE_KEY_RE = re.compile(r"@guide:\s*(\w+)")
CHAPTER_RE = re.compile(r"@chapter:\s*(\S+)")
SRCHASH_RE = re.compile(r"@srchash:\s*([a-f0-9]{16})")
STATUS_RE = re.compile(r"@status:\s*(\w+)")
LANG_RE = re.compile(r"@lang:\s*(\S+)")

# Para note pattern
PARA_NOTE_RE = re.compile(
    r"%Para:\s*(\d+)\s+h=([a-f0-9]{8})(?:\s+src=(machine|human))?(?:\n|$)",
    re.MULTILINE,
)

# Para note field pattern
PARA_FIELD_RE = re.compile(
    r"^(Intent|Subtext|Register|Do not translate literally|Cultural):\s*(.+)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ParaNote:
    """A paragraph note from a guide analysis document."""

    index: int
    hash8: str
    source: str | None = None
    intent: str = ""
    subtext: str = ""
    register: str = ""
    do_not_translate: list[str] = field(default_factory=list)
    cultural: str = ""


@dataclass(frozen=True)
class GuideDoc:
    """A parsed guide document."""

    kind: str  # analysis, style, glossary, language, note
    chapter: str | None = None
    srchash: str | None = None
    status: str = "draft"  # draft, approved
    lang: str | None = None
    body: str = ""
    para_notes: list[ParaNote] = field(default_factory=list)

    def get_keyword_lines(self) -> list[str]:
        """Generate the keyword lines for this guide document."""
        lines = []
        lines.append(f"@guide: {self.kind}")
        if self.chapter:
            lines.append(f"@chapter: {self.chapter}")
        if self.srchash:
            lines.append(f"@srchash: {self.srchash}")
        if self.status:
            lines.append(f"@status: {self.status}")
        if self.lang:
            lines.append(f"@lang: {self.lang}")
        return lines


class GuideParser:
    """Parser for guide documents."""

    KNOWN_KINDS: ClassVar[set[str]] = {"analysis", "style", "glossary", "language", "note"}

    @classmethod
    def parse(cls, text: str) -> GuideDoc:
        """Parse a guide document text into a GuideDoc object."""
        lines = text.splitlines()
        kind = "note"
        chapter: str | None = None
        srchash: str | None = None
        status = "draft"
        lang: str | None = None
        body_lines: list[str] = []
        in_body = False

        for line in lines:
            stripped = line.strip()
            if not in_body:
                # Check for keyword lines
                if stripped.startswith("@guide:"):
                    kind = stripped[7:].strip()
                elif stripped.startswith("@chapter:"):
                    chapter = stripped[9:].strip()
                elif stripped.startswith("@srchash:"):
                    srchash = stripped[9:].strip()
                elif stripped.startswith("@status:"):
                    status = stripped[8:].strip()
                elif stripped.startswith("@lang:"):
                    lang = stripped[6:].strip()
                elif stripped == "":
                    continue
                elif stripped.startswith("#") or not stripped.startswith("@"):
                    # Start of body content
                    in_body = True
                    body_lines.append(line)
                else:
                    # Unknown keyword line, treat as body
                    in_body = True
                    body_lines.append(line)
            else:
                body_lines.append(line)

        body = "\n".join(body_lines).strip()

        # Parse paragraph notes from body
        para_notes = cls._parse_para_notes(body)

        return GuideDoc(
            kind=kind,
            chapter=chapter,
            srchash=srchash,
            status=status,
            lang=lang,
            body=body,
            para_notes=para_notes,
        )

    @classmethod
    def _parse_para_notes(cls, text: str) -> list[ParaNote]:
        """Parse %Para: blocks from text."""
        notes: list[ParaNote] = []

        for match in PARA_NOTE_RE.finditer(text):
            index = int(match.group(1))
            hash8 = match.group(2)
            source = match.group(3) if match.group(3) else None

            # Find the end of this para note block
            start = match.end()
            next_match = PARA_NOTE_RE.search(text, start)
            end = next_match.start() if next_match else len(text)
            block_text = text[start:end]

            # Parse fields from the block
            intent = ""
            subtext = ""
            register = ""
            do_not_translate: list[str] = []
            cultural = ""

            for field_match in PARA_FIELD_RE.finditer(block_text):
                field_name = field_match.group(1)
                field_value = field_match.group(2).strip()
                if field_name == "Intent":
                    intent = field_value
                elif field_name == "Subtext":
                    subtext = field_value
                elif field_name == "Register":
                    register = field_value
                elif field_name == "Do not translate literally":
                    do_not_translate.append(field_value)
                elif field_name == "Cultural":
                    cultural = field_value

            note = ParaNote(
                index=index,
                hash8=hash8,
                source=source,
                intent=intent,
                subtext=subtext,
                register=register,
                do_not_translate=do_not_translate,
                cultural=cultural,
            )
            notes.append(note)

        return notes


def parseGuideDoc(text: str) -> GuideDoc:
    """Parse a guide document text into a GuideDoc object."""
    return GuideParser.parse(text)


def formatGuideDoc(doc: GuideDoc) -> str:
    """Format a GuideDoc object back to canonical text representation."""
    lines = doc.get_keyword_lines()
    lines.append("")  # Empty line before body
    lines.append(doc.body)
    return "\n".join(lines)


def parseParaNotes(text: str) -> list[ParaNote]:
    """Parse %Para: blocks from text."""
    return GuideParser._parse_para_notes(text)


def analysisStatus(
    chapterHandle: str, project: Any
) -> str:
    """Determine the status of an analysis for a chapter.

    Returns one of: missing, draft, stale, approved
    """
    # This is a simplified stub
    # Full implementation would check the guide documents
    return "missing"


def staleParaNotes(chapterHandle: str, project: Any) -> list[ParaNote]:
    """List stale paragraph notes for a chapter."""
    return []


@dataclass(frozen=True)
class ChapterRef:
    """Reference to a chapter with its documents."""

    title: str
    handles: list[str]
    canonicalTextHash: str


def chapterOf(handle: str, project: Any) -> ChapterRef | None:
    """Get chapter reference for a document handle."""
    # This is a stub
    return None


# Guide document kinds
GUIDE_KINDS = {"analysis", "style", "glossary", "language", "note"}


def isGuideKeyword(keyword: str) -> bool:
    """Check if a keyword is a guide-specific keyword."""
    guide_keywords = {
        nwKeyWords.GUIDE_KEY,
        nwKeyWords.CHAPTER_KEY,
        nwKeyWords.SRCHASH_KEY,
        nwKeyWords.STATUS_KEY,
        nwKeyWords.LANG_KEY,
    }
    return keyword in guide_keywords


def isGuideRootKeyword(keyword: str) -> bool:
    """Check if a keyword is only allowed in the Guide root."""
    return isGuideKeyword(keyword)
