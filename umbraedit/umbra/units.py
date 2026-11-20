"""UmbraEdit - Document Unit Parser.

This file is a part of UmbraEdit, a fork of novelWriter.
Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
Splits a document into logical units for the audio pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Optional, Union

from umbraedit.umbra.voiceline import VoiceData, isVoiceLine, parseVoiceLine

if TYPE_CHECKING:
    from collections.abc import Iterator


class UnitKind(IntEnum):
    HEADING = 1
    PARAGRAPH = 2
    COMMENT = 3
    KEYWORD = 4
    BLANK = 5


@dataclass
class Unit:
    kind: UnitKind
    lines: list[str]
    startLine: int
    voice: Optional[VoiceData] = None
    orphanVoice: bool = False


def stripFrontMatter(text: str) -> str:
    """Remove the document meta data header from a document text.

    The header is a TOML block at the very top of the document,
    delimited by `+++` lines. If the document has no header, the text
    is returned unchanged.
    """
    if not text.startswith("+++"):
        return text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].strip() == "+++":
            return "\n".join(lines[i + 1:])
    return text


def iterUnits(text: str) -> Iterator[Unit]:
    """Split a document into logical units."""
    lines = text.split("\n")
    currentVoice: Optional[VoiceData] = None
    i = 0
    # The document meta data header, if present, is not a content unit
    if lines and lines[0].strip() == "+++":
        i = 1
        while i < len(lines) and lines[i].strip() != "+++":
            i += 1
        i += 1
    while i < len(lines):
        line = lines[i]
        lineNo = i + 1
        if not line.strip():
            if currentVoice is not None:
                yield Unit(UnitKind.BLANK, [line], lineNo, voice=currentVoice, orphanVoice=True)
                currentVoice = None
            else:
                yield Unit(UnitKind.BLANK, [line], lineNo)
            i += 1
            continue
        if isVoiceLine(line):
            currentVoice = parseVoiceLine(line)
            if i + 1 >= len(lines) or not lines[i + 1].strip():
                yield Unit(UnitKind.PARAGRAPH, [line], lineNo, voice=currentVoice, orphanVoice=True)
                currentVoice = None
            i += 1
            continue
        if line.startswith("#"):
            yield Unit(UnitKind.HEADING, [line], lineNo)
            i += 1
            continue
        if line.startswith("@"):
            yield Unit(UnitKind.KEYWORD, [line], lineNo)
            i += 1
            continue
        if line.startswith("%"):
            yield Unit(UnitKind.COMMENT, [line], lineNo)
            i += 1
            continue
        paraLines = [line]
        j = i + 1
        while j < len(lines):
            nextLine = lines[j]
            if not nextLine.strip() or nextLine.startswith(("#", "@", "%")):
                break
            paraLines.append(nextLine)
            j += 1
        yield Unit(UnitKind.PARAGRAPH, paraLines, lineNo, voice=currentVoice)
        currentVoice = None
        i = j
