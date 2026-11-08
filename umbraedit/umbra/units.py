"""UmbraEdit - Document Unit Parser.

This file is a part of UmbraEdit, a fork of novelWriter.
Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
Splits a document into logical units for the audio pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import IntEnum

from umbraedit.umbra.voiceline import VoiceData, isVoiceLine, parseVoiceLine


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
    voice: VoiceData | None = None
    orphanVoice: bool = False


def iterUnits(text: str) -> Iterator[Unit]:
    """Split a document into logical units."""
    lines = text.split("\n")
    currentVoice: VoiceData | None = None
    i = 0
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
            if not nextLine.strip() or nextLine.startswith("#") or nextLine.startswith("@") or nextLine.startswith("%"):
                break
            paraLines.append(nextLine)
            j += 1
        yield Unit(UnitKind.PARAGRAPH, paraLines, lineNo, voice=currentVoice)
        currentVoice = None
        i = j
