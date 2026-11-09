"""
UmbraEdit - Utterance Derivation
================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Derives spoken units (utterances) from a document's text and metadata:
dialogue spans (P05), narration, attributions (P10), and utterance
overrides (P08/P10). Each utterance carries its speaker, tone, voice
matrix code (P08), pronunciation spans (P07), and a content hash used
for audio staleness (P11). Qt-free.
"""  # noqa

from __future__ import annotations

import hashlib
import re

from dataclasses import dataclass, field
from typing import Any

from umbraedit.umbra.dialogue import DialogueConfig, Span, findDialogueSpans
from umbraedit.umbra.sheet import aliasNorm
from umbraedit.umbra.voice import (
    ATTR_INHERIT,
    AttrSpan,
    ToneRef,
    effectiveDrop,
    narrationSpeaker,
    parseAttrSpans,
    parseUnitVoice,
    parseUttSpans,
    toneNeutral,
)
from umbraedit.umbra.voiceline import VoiceData, isVoiceLine, parseVoiceLine

# Speaker for narration when no pov is set
NARRATOR_SPEAKER = "narrator"
UNKNOWN_SPEAKER = "unknown"


@dataclass
class Utterance:
    """One derived spoken unit.

    Attributes:
        id: Stable id ``u-<handle>-<para 4 digits>-<k>``.
        handle: Document handle.
        para: Zero-based paragraph index among text paragraphs.
        kind: ``dialogue``, ``narration``, ``attribution``, or ``thought``.
        speaker: Speaker tag, ``narrator``, ``~label``, or ``unknown``.
        text: The utterance text (shortcodes stripped).
        joinAfter: Text appended after this utterance so that joining
            ``text + joinAfter`` of all utterances of a paragraph rebuilds
            the paragraph (shortcodes removed) byte for byte.
        tone: Tone key.
        toneI: Tone intensity (1-3).
        lang: BCP 47 language code, when set.
        src: ``author`` or ``machine``.
        skip: ``null`` or ``"attribution`` when dropped from audio.
        attribution: True when this utterance is an attribution span.
        voice: The speaker's voice matrix code, or None.
        pron: Pronunciation spans from P07, offsets inside ``text``.
        hash: SHA-256 of ``kind|speaker|text|tone|toneI|lang|voice|pron``.

    """

    id: str
    handle: str
    para: int
    kind: str
    speaker: str
    text: str
    joinAfter: str
    tone: str
    toneI: int
    lang: str
    src: str
    skip: str | None
    attribution: bool
    voice: str | None
    pron: list[dict[str, str]] = field(default_factory=list)
    hash: str = ""

    def toDict(self) -> dict[str, Any]:
        """Return a JSON-serialisable record."""
        return {
            "id": self.id,
            "handle": self.handle,
            "para": self.para,
            "kind": self.kind,
            "speaker": self.speaker,
            "text": self.text,
            "joinAfter": self.joinAfter,
            "tone": self.tone,
            "toneI": self.toneI,
            "lang": self.lang,
            "src": self.src,
            "skip": self.skip,
            "attribution": self.attribution,
            "voice": self.voice,
            "pron": self.pron,
            "hash": self.hash,
        }


def _utteranceHash(
    kind: str,
    speaker: str,
    text: str,
    tone: str,
    toneI: int,
    lang: str,
    voice: str | None,
    pron: list[dict[str, str]],
) -> str:
    payload = "|".join([kind, speaker, text, tone, str(toneI), lang, voice or "", repr(pron)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _toneString(tr: ToneRef | None) -> str:
    return str(tr) if tr is not None else ""


def _voiceForSpeaker(speaker: str | None, index: Any, store: Any) -> str | None:
    """Return the voice matrix code for a speaker, or None."""
    if not speaker or speaker in (NARRATOR_SPEAKER, UNKNOWN_SPEAKER):
        return None
    if store is None or index is None:
        return None
    row = index.getEntity(speaker) if hasattr(index, "getEntity") else None
    if row is None:
        return None
    attrs = getattr(row, "attrs", {}) or {}
    return attrs.get("voice_matrix", None)


def _stripShortcodes(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Remove ``[attr]``/``[utt]`` shortcodes.

    Returns (cleaned text, list of (placeholder, original) pairs). The
    placeholders mark where shortcodes were removed so that joinAfter
    can reinsert them to preserve the join invariant.
    """
    removed: list[tuple[str, str]] = []

    def repl(m: re.Match[str]) -> str:
        placeholder = f"\u0000STRIP{len(removed)}\u0000"
        removed.append((placeholder, m.group(0)))
        return placeholder

    text = re.sub(
        r"\[(?:attr(?::\w+)?|utt:[^\]]*)\](.*?)\[/\w+\]",
        lambda m: repl(m) + m.group(1),
        text,
        flags=re.DOTALL,
    )
    text = text.replace("[/attr]", "\u0000").replace("[/utt]", "\u0000")
    return text, removed


def _restoreShortcodes(text: str, removed: list[tuple[str, str]]) -> str:
    """Reverse of _stripShortcodes."""
    for i in range(len(removed) - 1, -1, -1):
        placeholder, original = removed[i]
        try:
            open_close = original.index("]")
            close_slash = original.rfind("[/")
            if close_slash > open_close:
                inner = original[open_close + 1 : close_slash]
                text = text.replace(placeholder + inner, original, 1)
            else:
                text = text.replace(placeholder, original, 1)
        except ValueError:
            text = text.replace(placeholder, original, 1)
    return text


def _splitParagraphIntoSegments(text: str, dialogueSpans: list[Span]) -> list[tuple[int, int, str]]:
    """Split a paragraph into dialogue / attribution / narration segments.

    Returns a list of (start, end, kind) covering the whole text.
    Within a dialogue span, attribution spans become ``attribution``
    kind; everything else within is ``dialogue``. Outside dialogue
    spans is ``narration``.
    """
    segments: list[tuple[int, int, str]] = []
    attrSpans = parseAttrSpans(text)

    cursor = 0
    for dSpan in dialogueSpans:
        if dSpan.kind != "dialogue":
            continue
        if dSpan.start > cursor:
            segments.append((cursor, dSpan.start, "narration"))
            cursor = dSpan.start

        dCursor = dSpan.start
        for aSpan in attrSpans:
            if aSpan.start < dSpan.start or aSpan.end > dSpan.end:
                continue
            if aSpan.start > dCursor:
                segments.append((dCursor, aSpan.start, "dialogue"))
                dCursor = aSpan.start
            segments.append((aSpan.start, aSpan.end, "attribution"))
            dCursor = aSpan.end
        if dCursor < dSpan.end:
            segments.append((dCursor, dSpan.end, "dialogue"))
        cursor = dSpan.end

    if cursor < len(text):
        segments.append((cursor, len(text), "narration"))

    segments.sort(key=lambda s: s[0])
    return segments


def deriveUtterances(
    handle: str,
    text: str,
    project: Any,
    index: Any | None = None,
    settings: Any | None = None,
    store: Any | None = None,
) -> list[Utterance]:
    """R1: Derive utterances for one document.

    The join invariant holds: concatenating ``text + joinAfter`` of all
    utterances of a paragraph rebuilds the paragraph text (after
    removing shortcodes) byte for byte.
    """
    if index is None:
        index = project.index
    dialogueCfg = DialogueConfig()

    narrSpeaker = narrationSpeaker(handle, index)

    rawBlocks = re.split(r"\n\n+", text) if text else []
    utterances: list[Utterance] = []
    paraIndex = 0

    for block in rawBlocks:
        block = block.strip("\n")
        if not block.strip():
            continue

        voice: VoiceData | None = None
        lines = block.split("\n")
        bodyStart = 0
        for i, line in enumerate(lines):
            if isVoiceLine(line):
                voice = parseVoiceLine(line)
                bodyStart = i + 1
            else:
                break
        body = "\n".join(lines[bodyStart:])

        cleanBody, _removed = _stripShortcodes(body)

        unitVoice = parseUnitVoice(block)
        uttSpans = parseUttSpans(cleanBody)
        dialogueSpans = findDialogueSpans(cleanBody, dialogueCfg)

        spk = voice.spk if voice else None

        segments = _splitParagraphIntoSegments(cleanBody, dialogueSpans)

        k = 0
        lastDialogueSpeaker: str | None = None
        for i, (start, end, kind) in enumerate(segments):
            seg = cleanBody[start:end]
            if not seg.strip():
                continue

            stripped_seg = seg.strip()
            trailing_ws = seg[len(seg.rstrip()) :]

            if i + 1 < len(segments):
                next_start, next_end, _ = segments[i + 1]
                next_seg = cleanBody[next_start:next_end]
                leading_ws_next = next_seg[: len(next_seg) - len(next_seg.lstrip())] if next_seg.strip() else ""
            else:
                leading_ws_next = ""

            joinAfter = trailing_ws + leading_ws_next
            seg = stripped_seg

            if kind == "dialogue":
                uttSpan = next((u for u in uttSpans if u.start == start), None)
                speaker = uttSpan.spk if uttSpan and uttSpan.spk else (spk if spk else None)
                if speaker is None:
                    speaker = _speakerFromFollowingText(cleanBody, end, index) or lastDialogueSpeaker or UNKNOWN_SPEAKER
                lastDialogueSpeaker = speaker
                src = "machine" if (voice and voice.src == "machine") else "author"
                toneRef = uttSpan.tone if uttSpan and uttSpan.tone else paraTone(unitVoice.tone)
                skip = None
                attribution = False
            elif kind == "attribution":
                speaker = spk if spk else narrSpeaker
                src = "author"
                toneRef = unitVoice.ntone if unitVoice.ntone else toneNeutral()
                attrSpan = AttrSpan(start, end, seg, ATTR_INHERIT)
                skip = "attribution" if effectiveDrop(attrSpan, None) else None
                attribution = True
            else:
                speaker = narrSpeaker
                src = "author"
                toneRef = unitVoice.ntone if unitVoice.ntone else toneNeutral()
                skip = None
                attribution = bool(
                    re.match(
                        r"\s*(?:said|asked|replied|whispered|shouted)\s+.+?[.,!?]\s*$",
                        seg,
                        re.IGNORECASE,
                    )
                )

            voiceCode = _voiceForSpeaker(speaker, index, store)
            toneStr = _toneString(toneRef)
            toneI = toneRef.intensity if toneRef else 2
            lang = voice.lang if voice and voice.lang else ""

            utt = Utterance(
                id=f"u-{handle}-{paraIndex:04d}-{k}",
                handle=handle,
                para=paraIndex,
                kind=kind,
                speaker=speaker,
                text=seg,
                joinAfter=joinAfter,
                tone=toneStr,
                toneI=toneI,
                lang=lang,
                src=src,
                skip=skip,
                attribution=attribution,
                voice=voiceCode,
                pron=[],
            )
            utt.hash = _utteranceHash(kind, speaker, seg, toneStr, toneI, lang, voiceCode, [])
            utterances.append(utt)
            k += 1

        paraIndex += 1

    return utterances


def paraTone(tr: ToneRef | None) -> ToneRef:
    """Return the tone or neutral default."""
    return tr if tr is not None else toneNeutral()


def _speakerFromFollowingText(cleanBody: str, dialEnd: int, index: Any) -> str | None:
    """Try to resolve a dialogue speaker from text immediately following
    the dialogue span, looking for patterns like "said Uncle Bob.".
    """
    if index is None:
        return None

    following = cleanBody[dialEnd:]
    m = re.match(
        r"\s*(?:said|asked|replied|whispered|shouted)\s+(.+?)\s*[.,!?]\s*",
        following,
        re.IGNORECASE,
    )
    if not m:
        return None
    name = m.group(1).strip()
    if not name:
        return None
    norm = aliasNorm(name)
    for row in index.iterEntities():
        if aliasNorm(row.tag) == norm:
            return row.tag
        if any(aliasNorm(a) == norm for a in row.aliases):
            return row.tag
        attrs = getattr(row, "attrs", {}) or {}
        for key in ("fn", "mn", "ln", "nick", "title"):
            if attrs.get(key) and aliasNorm(attrs[key]) == norm:
                return row.tag
    return None
