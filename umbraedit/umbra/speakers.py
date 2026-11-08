"""
UmbraEdit - Speaker Authoring
=============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Qt-free logic for speaker authoring (P09): annotate-mode chips, the
speaker picker application, Enter alternation/unclosed-quote proposals,
split and merge, review flags, and attribution-name checking. The GUI
layer (gutter chips, picker popup, Speakers dock, underlines) is
deferred to GAPS.md.
"""  # noqa

from __future__ import annotations

import hashlib
import json
import re

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.sheet import EntityRow, aliasNorm
from umbraedit.umbra.voiceline import (
    VoiceData,
    formatVoiceLine,
    isVoiceLine,
    parseVoiceLine,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable, Iterable
    from pathlib import Path

# Chip kinds
CHIP_ASSIGNED = "assigned"
CHIP_PROPOSED = "proposed"
CHIP_UNASSIGNED = "unassigned"
CHIP_NEEDS_REVIEW = "needs_review"
CHIP_NONE = "none"

# Amber for unassigned / needs review
CHIP_AMBER = "#c58a00"


@dataclass(frozen=True)
class SpeakerChip:
    """The annotate-mode chip for one paragraph.

    Attributes:
        kind: ``assigned``, ``proposed``, ``unassigned``,
            ``needs_review`` or ``none``.
        tag: The resolved speaker tag, when assigned or proposed.
        label: The chip text: initials for ``assigned``, ``?`` for
            ``unassigned``.
        color: A stable hex color for the tag (``assigned`` only).
        dashed: Whether the chip border is dashed (``proposed`` only).

    """

    kind: str
    tag: str | None = None
    label: str = ""
    color: str = ""
    dashed: bool = False


@dataclass(frozen=True)
class SpeakerProposal:
    """A proposed speaker for a new paragraph (Enter behavior, R4)."""

    tag: str
    reason: str  # "alternation" or "unclosed_quote"


@dataclass
class SplitResult:
    """Result of splitting a paragraph (R5)."""

    firstPart: str
    secondPart: str


@dataclass
class MergeResult:
    """Result of merging two paragraphs (R5)."""

    merged: str
    dropped: str | None  # Human-readable notice of what was dropped.


def tagColor(tag: str) -> str:
    """Return a stable hex color for a tag."""
    digest = hashlib.sha256(tag.encode("utf-8")).digest()
    return f"#{digest[0]:02x}{digest[1]:02x}{digest[2]:02x}"


def tagInitials(tag: str, entities: Iterable[EntityRow]) -> str:
    """Return the initials for a tag from its display name or tag."""
    for entity in entities:
        if entity.tag == tag:
            name = entity.displayName or entity.tag
            break
    else:
        name = tag
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _voiceOfParagraph(paragraphText: str) -> VoiceData | None:
    """Return the VoiceData attached to a paragraph, if any.

    The paragraph text may include a leading ``%Voice:`` line.
    """
    for line in paragraphText.split("\n"):
        if isVoiceLine(line):
            return parseVoiceLine(line)
    return None


def _hasDialogue(paragraphText: str, dialogueSpans: Callable[[str], list]) -> bool:
    """Return True when the paragraph contains a dialogue span."""
    spans = dialogueSpans(paragraphText)
    return any(s.kind == "dialogue" for s in spans)


def chipForParagraph(
    paragraphText: str,
    entities: list[EntityRow],
    dialogueSpans: Callable[[str], list],
    reviewFlags: set[tuple[str, int]],
    handle: str = "",
    lineNo: int = 0,
) -> SpeakerChip:
    """Compute the annotate-mode chip for one paragraph (R1).

    ``dialogueSpans`` is a callable ``findDialogueSpans(text, config)``
    bound to the project's dialogue settings. ``reviewFlags`` holds
    (handle, lineNo) pairs flagged for review (R7).
    """
    voice = _voiceOfParagraph(paragraphText)

    if reviewFlags and handle and (handle, lineNo) in reviewFlags:
        return SpeakerChip(
            kind=CHIP_NEEDS_REVIEW,
            tag=voice.spk if voice else None,
            label=tagInitials(voice.spk or "", entities) if voice else "?",
            color=tagColor(voice.spk or "") if voice else "",
        )

    if voice is None:
        if _hasDialogue(paragraphText, dialogueSpans):
            return SpeakerChip(kind=CHIP_UNASSIGNED, label="?", color=CHIP_AMBER)
        return SpeakerChip(kind=CHIP_NONE)

    if voice.src == "machine":
        return SpeakerChip(
            kind=CHIP_PROPOSED,
            tag=voice.spk,
            label=tagInitials(voice.spk or "", entities),
            color=tagColor(voice.spk or ""),
            dashed=True,
        )
    return SpeakerChip(
        kind=CHIP_ASSIGNED,
        tag=voice.spk,
        label=tagInitials(voice.spk or "", entities),
        color=tagColor(voice.spk or ""),
    )


def enterProposal(
    previousVoices: list[VoiceData | None],
    lastParagraphEndsWithUnclosedQuote: bool,
) -> SpeakerProposal | None:
    """Proposal for a new paragraph after Enter (R4).

    Alternation: the previous two paragraphs alternate speakers A, B ->
    propose A. Unclosed quote: propose the same speaker as the previous
    paragraph. Returns None when there is no basis for a proposal.
    """
    if lastParagraphEndsWithUnclosedQuote and previousVoices:
        last = previousVoices[-1]
        if last and last.spk:
            return SpeakerProposal(tag=last.spk, reason="unclosed_quote")
    if len(previousVoices) >= 2:
        a, b = previousVoices[-2], previousVoices[-1]
        if a and b and a.spk and b.spk and a.spk != b.spk and a.src != "machine" and b.src != "machine":
            return SpeakerProposal(tag=a.spk, reason="alternation")
    return None


def applySpeaker(paragraphText: str, tag: str | None, entities: list[EntityRow]) -> str:
    """Write or update the ``%Voice:`` line for a paragraph (R2).

    ``tag=None`` removes the voice line entirely. When the paragraph
    already has a ``%Voice:`` line above it, only ``spk`` is changed;
    otherwise a new line is inserted directly before the paragraph.
    """
    lines = paragraphText.split("\n")
    voiceLineIndex = -1
    for i, line in enumerate(lines):
        if isVoiceLine(line):
            voiceLineIndex = i
            break

    data: VoiceData | None = None
    if voiceLineIndex >= 0:
        data = parseVoiceLine(lines[voiceLineIndex])

    if tag is None:
        # Remove the voice line if every field would become default.
        if voiceLineIndex >= 0:
            del lines[voiceLineIndex]
        return "\n".join(lines)

    if data is None:
        voiceLine = formatVoiceLine(VoiceData(spk=tag))
        return "\n".join([voiceLine, *lines])

    data.spk = tag
    lines[voiceLineIndex] = formatVoiceLine(data)
    return "\n".join(lines)


def resolvePick(text: str, entities: list[EntityRow]) -> tuple[list[EntityRow], bool]:
    """Resolve typed text to matching entities (R3).

    Returns (matches, exactSingleMatch). Matching uses aliasNorm over
    tag, name parts, aliases, and full name.
    """
    norm = aliasNorm(text)
    if not norm:
        return [], False
    matches: list[EntityRow] = []
    for entity in entities:
        if aliasNorm(entity.tag) == norm:
            matches.append(entity)
            continue
        if any(aliasNorm(alias) == norm for alias in entity.aliases):
            matches.append(entity)
            continue
        attrs = entity.attrs
        for key in ("fn", "mn", "ln", "nick", "title"):
            if attrs.get(key) and aliasNorm(attrs[key]) == norm:
                matches.append(entity)
                break
        else:
            if aliasNorm(full_name(attrs)) == norm:
                matches.append(entity)
    return matches, len(matches) == 1


def splitParagraph(paragraphText: str, splitIndex: int) -> SplitResult:
    """Split a paragraph at ``splitIndex`` (R5).

    The first part keeps its ``%Voice:`` line; the second gets none.
    """
    lines = paragraphText.split("\n")
    voice = _voiceOfParagraph(paragraphText)
    firstLines = lines[:splitIndex]
    secondLines = lines[splitIndex:]
    if voice is not None and firstLines:
        # Ensure the first part keeps the voice line; it already does if
        # the split point is after the voice line.
        pass
    return SplitResult(firstPart="\n".join(firstLines), secondPart="\n".join(secondLines))


def mergeParagraphs(firstText: str, secondText: str) -> MergeResult:
    """Merge two paragraphs (R5).

    Keeps the first part's ``%Voice:`` line. When the second paragraph
    had a different ``spk`` or ``tone``, returns a dropped notice.
    """
    firstVoice = _voiceOfParagraph(firstText)
    secondVoice = _voiceOfParagraph(secondText)
    dropped: str | None = None

    firstLines = firstText.split("\n")
    # Strip any leading voice line from the first text body; it will be
    # re-added on top of the merge.
    firstBodyLines = [line for line in firstLines if not isVoiceLine(line)]
    secondBodyLines = [line for line in secondText.split("\n") if not isVoiceLine(line)]

    if firstVoice and secondVoice and (firstVoice.spk != secondVoice.spk or firstVoice.tone != secondVoice.tone):
        dropped = (
            f"Dropped voice '{secondVoice.spk or 'none'}'"
            + (f" (tone {secondVoice.tone})" if secondVoice.tone else "")
            + " from the merged paragraph."
        )

    voiceLine = formatVoiceLine(firstVoice) if firstVoice else ""
    mergedLines = ([voiceLine] if voiceLine else []) + firstBodyLines + [""] + secondBodyLines
    return MergeResult(merged="\n".join(mergedLines), dropped=dropped)


##
#  Review flags (R7)
##


def reviewFlagsPath(projectPath: Path) -> Path:
    """Return ``<project>/umbra/cache/review.json``."""
    return projectPath / "umbra" / "cache" / "review.json"


def loadReviewFlags(projectPath: Path) -> set[tuple[str, int]]:
    """Load the review-flag set from ``review.json``."""
    path = reviewFlagsPath(projectPath)
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    flags: set[tuple[str, int]] = set()
    for handle, lines in (data.get("flags") or {}).items():
        if not isinstance(lines, dict):
            continue
        for lineNo in lines:
            try:
                flags.add((handle, int(lineNo)))
            except (TypeError, ValueError):
                continue
    return flags


def saveReviewFlags(projectPath: Path, flags: set[tuple[str, int]]) -> None:
    """Atomically save the review-flag set to ``review.json``."""
    path = reviewFlagsPath(projectPath)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "v": 1,
        "flags": {
            handle: {str(lineNo): True for lineNo in sorted(lineNos)} for handle, lineNos in _groupFlags(flags).items()
        },
    }
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def _groupFlags(
    flags: set[tuple[str, int]],
) -> dict[str, list[int]]:
    """Group (handle, lineNo) flags into a handle -> line numbers dict."""
    grouped: dict[str, list[int]] = {}
    for handle in sorted({handle for handle, _ in flags}):
        grouped[handle] = sorted(lineNo for h, lineNo in flags if h == handle)
    return grouped


def toggleReviewFlag(projectPath: Path, handle: str, lineNo: int) -> set[tuple[str, int]]:
    """Toggle one review flag and persist (R7)."""
    flags = loadReviewFlags(projectPath)
    key = (handle, lineNo)
    if key in flags:
        flags.discard(key)
    else:
        flags.add(key)
    saveReviewFlags(projectPath, flags)
    return flags


##
#  Attribution name checking (R8)
##


@dataclass(frozen=True)
class UnattributedName:
    """An attribution name that matches no character or alias."""

    start: int
    end: int
    name: str


def attributionSpanText(paragraph: str) -> list[tuple[int, int, str]]:
    """Return (start, end, innerText) of each ``[attr]``/``[utt]`` span."""
    return [
        (m.start(1), m.end(1), m.group(1))
        for m in re.finditer(
            r"\[(?:attr(?::\w+)?|utt:[^\]]*)\](.*?)\[/\w+\]",
            paragraph,
            re.DOTALL,
        )
    ]


def unattributedNames(paragraph: str, entities: list[EntityRow]) -> list[UnattributedName]:
    """Attribution names in ``[attr]`` spans matching no entity (R8)."""
    result: list[UnattributedName] = []
    for start, end, inner in attributionSpanText(paragraph):
        name = _attributionName(inner)
        if not name:
            continue
        matches, _ = resolvePick(name, entities)
        if not matches:
            result.append(UnattributedName(start=start, end=end, name=name))
    return result


def _attributionName(inner: str) -> str:
    """Extract the spoken-of name from attribution inner text.

    ``said Uncle Bob.`` -> ``Uncle Bob``; ``asked Ana.`` -> ``Ana``.
    """
    m = re.match(r"\s*(?:said|asked|replied|whispered|shouted)\s+(.+?)\s*[.,!?]\s*$", inner, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return inner.strip()


##
#  Settings (R10)
##


SETTING_ADD_ALIASES_AUTOMATICALLY = "speakers.addAliasesAutomatically"
SETTING_PROPOSE_ALTERNATION = "speakers.proposeAlternation"

_SPEAKER_SETTING_DEFAULTS: dict[str, Any] = {
    SETTING_ADD_ALIASES_AUTOMATICALLY: False,
    SETTING_PROPOSE_ALTERNATION: True,
}


def speakerSetting(settings: Any, key: str) -> Any:
    """Read a speakers setting, falling back to the default."""
    if settings is None:
        return _SPEAKER_SETTING_DEFAULTS.get(key)
    try:
        return settings.get(key, _SPEAKER_SETTING_DEFAULTS.get(key))
    except AttributeError:  # settings object without a get method
        return _SPEAKER_SETTING_DEFAULTS.get(key)


def addAliasesAutomatically(settings: Any) -> bool:
    """R10: whether the alias prompt is skipped."""
    return bool(speakerSetting(settings, SETTING_ADD_ALIASES_AUTOMATICALLY))


def proposeAlternation(settings: Any) -> bool:
    """R10: whether Enter proposes alternation speakers."""
    return bool(speakerSetting(settings, SETTING_PROPOSE_ALTERNATION))


def full_name(attrs: dict[str, str]) -> str:
    """Compute the full name from name component attributes."""
    parts = []
    for key in ("title", "fn", "mn", "ln", "suffix"):
        val = attrs.get(key, "")
        if val:
            parts.append(val)
    return " ".join(parts)
