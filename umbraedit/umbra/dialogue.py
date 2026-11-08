"""UmbraEdit - Dialogue Span Detector.

This file is a part of UmbraEdit, a fork of novelWriter.
Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
Detects dialogue spans in a paragraph using the project's dialogue
settings (quote style, alternate symbols, dash style).
"""  # noqa

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


# Quote style constants (matching config.py dialogStyle values)
QUOTE_CURLY = 0
QUOTE_STRAIGHT = 1
QUOTE_GERMAN = 2
QUOTE_FRENCH = 3
QUOTE_DASH = 4


@dataclass
class DialogueConfig:
    """Dialogue detection configuration from the app settings."""

    quoteStyle: int = QUOTE_CURLY
    allowOpenEnd: bool = True
    altSymbols: str = ""
    dashStyle: bool = False


# Quote pairs for each style
QUOTE_PAIRS: dict[int, tuple[str, str]] = {
    QUOTE_CURLY: ("\u201c", "\u201d"),
    QUOTE_STRAIGHT: ('"', '"'),
    QUOTE_GERMAN: ("\u201e", "\u201c"),
    QUOTE_FRENCH: ("\u00ab", "\u00bb"),
    QUOTE_DASH: ("\u2014", "\u2014"),
}


class Span(NamedTuple):
    """A dialogue or narration span within a paragraph."""

    start: int
    end: int
    kind: str  # "dialogue" | "narration"


def findDialogueSpans(paragraph: str, config: DialogueConfig) -> list[Span]:
    """Find dialogue and narration spans in a paragraph.

    Returns a list of (start, end, kind) tuples. kind is "dialogue" or
    "narration". The spans cover the entire paragraph.

    Handles:
    - The configured quote style (curly, straight, German, French, dash)
    - Unclosed quotes at the end (continues to end of paragraph)
    - Alternate dialogue symbols
    - Dash-style dialogue (em-dash at line start)
    """
    openChar, closeChar = QUOTE_PAIRS.get(config.quoteStyle, QUOTE_PAIRS[QUOTE_CURLY])
    altOpen, altClose = _parseAltSymbols(config.altSymbols)

    spans: list[Span] = []
    pos = 0
    length = len(paragraph)

    while pos < length:
        # Find the next dialogue opener
        openIdx = _findOpener(paragraph, pos, openChar, altOpen, config)

        if openIdx < 0:
            # No more openers; rest is narration
            if pos < length:
                spans.append(Span(pos, length, "narration"))
            break

        # Narration before the dialogue
        if openIdx > pos:
            spans.append(Span(pos, openIdx, "narration"))

        # Find the closer
        closeIdx = paragraph.find(closeChar, openIdx + len(openChar))
        if closeIdx < 0:
            # Unclosed quote: extends to end of paragraph
            if config.allowOpenEnd:
                spans.append(Span(openIdx, length, "dialogue"))
            else:
                spans.append(Span(openIdx, length, "narration"))
            break

        # Dialogue span (from opener to closer inclusive)
        dialogueEnd = closeIdx + len(closeChar)
        spans.append(Span(openIdx, dialogueEnd, "dialogue"))
        pos = dialogueEnd

    # Merge adjacent same-kind spans
    merged: list[Span] = []
    for span in spans:
        if merged and merged[-1].kind == span.kind and merged[-1].end == span.start:
            merged[-1] = Span(merged[-1].start, span.end, span.kind)
        else:
            merged.append(span)

    return merged


def _findOpener(text: str, pos: int, openChar: str, altOpen: str, config: DialogueConfig) -> int:
    """Find the next dialogue opener in the text starting from pos."""
    results = []

    idx = text.find(openChar, pos)
    if idx >= 0:
        results.append(idx)

    if altOpen:
        idx = text.find(altOpen, pos)
        if idx >= 0:
            results.append(idx)

    if config.dashStyle:
        # Dash dialogue: em-dash followed by space at start of a line
        for lineStart in _lineStarts(text, pos):
            if lineStart + 1 < len(text) and text[lineStart:lineStart + 2] in ("\u2014 ", "\u2013 "):
                results.append(lineStart)

    if not results:
        return -1
    return min(results)


def _parseAltSymbols(altSymbols: str) -> tuple[str, str]:
    """Parse alternate dialogue symbols from the setting string."""
    if not altSymbols or len(altSymbols) < 2:
        return "", ""
    return altSymbols[0], altSymbols[-1]


def _lineStarts(text: str, fromPos: int) -> list[int]:
    """Return the positions of line starts in the text."""
    starts = []
    pos = text.find("\n", fromPos)
    while pos >= 0:
        starts.append(pos + 1)
        pos = text.find("\n", pos + 1)
    return starts
