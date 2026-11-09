"""
UmbraEdit - Tone, Narration Voice and Attribution
==================================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Resolution logic for dialogue tone, narration tone, point-of-view
narration speaker, attribution drops, and utterance overrides. Qt-free.
"""  # noqa

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Any

from umbraedit.umbra.voiceline import VoiceData, isVoiceLine, parseVoiceLine

# Default tone key and intensity
DEFAULT_TONE_KEY = "neutral"
DEFAULT_TONE_INTENSITY = 2

# Tone regex: key or key:intensity
_TONE_RE = re.compile(r"^([A-Za-z0-9_]+)(?::([123]))?$")

# Attribution modes
ATTR_INHERIT = "inherit"
ATTR_DROP = "drop"
ATTR_KEEP = "keep"
ATTR_PROPOSAL = "proposal"


@dataclass(frozen=True)
class ToneRef:
    """A tone reference: key plus optional intensity (1-3, default 2)."""

    key: str
    intensity: int = DEFAULT_TONE_INTENSITY

    def __str__(self) -> str:
        """Render the tone as ``key`` or ``key:intensity``."""
        if self.intensity == DEFAULT_TONE_INTENSITY:
            return self.key
        return f"{self.key}:{self.intensity}"


def parseTone(text: str) -> ToneRef | None:
    """Parse a tone value ``key`` or ``key:1|2|3``.

    Returns None when the value is not a valid tone.
    """
    match = _TONE_RE.match(text.strip())
    if not match:
        return None
    key, intensity = match.group(1), match.group(2)
    return ToneRef(key=key, intensity=int(intensity) if intensity else DEFAULT_TONE_INTENSITY)


def toneNeutral() -> ToneRef:
    """Return the default neutral tone at intensity 2."""
    return ToneRef(key=DEFAULT_TONE_KEY, intensity=DEFAULT_TONE_INTENSITY)


@dataclass
class UnitVoice:
    """Voice metadata attached to a paragraph unit.

    Attributes:
        tone: Dialogue tone, when set on the paragraph.
        ntone: Narration tone, when set on the paragraph.
        sceneTone: Scene default narration tone (from scope=scene line),
            when set.

    """

    tone: ToneRef | None = None
    ntone: ToneRef | None = None
    sceneTone: ToneRef | None = None


def parseUnitVoice(text: str) -> UnitVoice:
    """Extract tone/ntone/scene tone from a paragraph's ``%Voice:`` line."""
    tone: ToneRef | None = None
    ntone: ToneRef | None = None
    sceneTone: ToneRef | None = None
    for line in text.split("\n"):
        if not isVoiceLine(line):
            continue
        voice = parseVoiceLine(line)
        if voice is None:
            continue
        if voice.tone:
            parsed = parseTone(voice.tone)
            if parsed is not None:
                tone = parsed
        if voice.ntone:
            parsed = parseTone(voice.ntone)
            if parsed is not None:
                ntone = parsed
                if voice.scope == "scene":
                    sceneTone = parsed
    return UnitVoice(tone=tone, ntone=ntone, sceneTone=sceneTone)


def effectiveDialogueTone(unit: UnitVoice, sceneVoice: UnitVoice) -> ToneRef:
    """R3: effective dialogue tone = unit.tone or neutral:2."""
    if unit.tone is not None:
        return unit.tone
    return toneNeutral()


def effectiveNarrationTone(unit: UnitVoice, sceneVoice: UnitVoice) -> ToneRef:
    """R3: effective narration tone = unit.ntone or sceneVoice.ntone or
    neutral:2.
    """
    if unit.ntone is not None:
        return unit.ntone
    if sceneVoice.ntone is not None:
        return sceneVoice.ntone
    return toneNeutral()


def narrationSpeaker(sceneHandle: str, index: Any) -> str:
    """R3: the @pov tag of the scene if set, else "narrator".

    Reuses the existing @pov keyword; takes the first pov tag found on
    the scene document.
    """
    if index is None:
        return "narrator"
    row = index.getEntity(sceneHandle) if hasattr(index, "getEntity") else None
    if row is not None:
        pov = row.attrs.get("pov", "")
        if pov:
            return pov.partition("|")[0].strip() or "narrator"
    return "narrator"


##
#  Attribution (R5/R6)
##

_ATTR_OPEN_RE = re.compile(r"\[attr(?::(inherit|drop|keep|proposal))?\]")
_ATTR_CLOSE_RE = re.compile(r"\[/attr\]")


@dataclass(frozen=True)
class AttrSpan:
    """One attribution span in a paragraph.

    Attributes:
        start: Start offset in the paragraph text.
        end: End offset (exclusive) in the paragraph text.
        inner: The inner text between the tags.
        mode: ``inherit``, ``drop``, ``keep`` or ``proposal``.

    """

    start: int
    end: int
    inner: str
    mode: str


def parseAttrSpans(paragraph: str) -> list[AttrSpan]:
    """Parse all ``[attr]``/``[attr:drop]``/``[attr:keep]``/``[attr:proposal]``
    spans in a paragraph.

    Returns spans sorted by start offset. Unmatched open tags are
    skipped.
    """
    spans: list[AttrSpan] = []
    stack: list[tuple[int, int, str]] = []  # (open tag start, inner start, mode)
    for m in _ATTR_OPEN_RE.finditer(paragraph):
        mode = m.group(1) or ATTR_INHERIT
        stack.append((m.start(), m.end(), mode))
    for m in _ATTR_CLOSE_RE.finditer(paragraph):
        if not stack:
            continue
        start, innerStart, mode = stack.pop(0)
        spans.append(AttrSpan(start=start, end=m.end(), inner=paragraph[innerStart : m.start()], mode=mode))
    spans.sort(key=lambda s: s.start)
    return spans


def effectiveDrop(span: AttrSpan, speaker: Any = None, settings: Any = None) -> bool:
    """R6: effective drop for an attribution span.

    - span value if drop or keep
    - else the speaker's ``@attr: drop_attrib`` if yes or no
    - else the project setting ``audio.dropAttributions`` (default false)
    """
    if span.mode == ATTR_DROP:
        return True
    if span.mode == ATTR_KEEP:
        return False
    # inherit: consult the speaker's drop_attrib attribute
    dropAttrib = ""
    if speaker is not None:
        attrs = getattr(speaker, "attrs", {}) or {}
        dropAttrib = attrs.get("drop_attrib", "")
    if dropAttrib == "yes":
        return True
    if dropAttrib == "no":
        return False
    return _dropAttributionsSetting(settings)


def _dropAttributionsSetting(settings: Any) -> bool:
    """Read the audio.dropAttributions project setting (default false)."""
    if settings is None:
        return False
    try:
        return bool(settings.getBool("audio.dropAttributions", False))
    except Exception:
        return False


##
#  Utterance override (R8)
##

_UTT_OPEN_RE = re.compile(r"\[utt:([^\]]*)\]")


@dataclass(frozen=True)
class UtteranceSpan:
    """One ``[utt:...]`` override span.

    Attributes:
        start: Start offset in the paragraph text.
        end: End offset (exclusive) in the paragraph text.
        inner: The inner text between the tags.
        spk: Override speaker tag, when set.
        tone: Override tone, when set.

    """

    start: int
    end: int
    inner: str
    spk: str | None = None
    tone: ToneRef | None = None


def parseUttSpans(paragraph: str) -> list[UtteranceSpan]:
    """Parse all ``[utt:spk=...;tone=...]`` override spans."""
    spans: list[UtteranceSpan] = []
    for m in _UTT_OPEN_RE.finditer(paragraph):
        close = paragraph.find("[/utt]", m.end())
        if close < 0:
            continue
        paramsText = m.group(1)
        spk: str | None = None
        tone: ToneRef | None = None
        for param in paramsText.split(";"):
            if "=" not in param:
                continue
            key, _, value = param.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "spk":
                spk = value or None
            elif key == "tone":
                parsed = parseTone(value)
                if parsed is not None:
                    tone = parsed
        spans.append(
            UtteranceSpan(
                start=m.start(),
                end=close + len("[/utt]"),
                inner=paragraph[m.end() : close],
                spk=spk,
                tone=tone,
            )
        )
    spans.sort(key=lambda s: s.start)
    return spans


def effectiveUtteranceSpeaker(paragraphVoice: VoiceData | None, uttSpan: UtteranceSpan | None) -> str | None:
    """R8: resolution order for an utterance speaker.

    utt span speaker, then paragraph voice spk, then None.
    """
    if uttSpan is not None and uttSpan.spk:
        return uttSpan.spk
    if paragraphVoice is not None and paragraphVoice.spk:
        return paragraphVoice.spk
    return None
