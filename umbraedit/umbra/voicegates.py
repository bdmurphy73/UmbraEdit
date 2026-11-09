"""
UmbraEdit - Attribution Gate Rules
===================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for attribution spans (P10): drop-same-voice and open
proposal. Registered via ``umbra.gates``.
"""  # noqa

from __future__ import annotations

import logging
import re

from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_AUDIO_CHAPTER,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.sheet import aliasNorm
from umbraedit.umbra.voice import ATTR_PROPOSAL, effectiveDrop, parseAttrSpans

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

_ATTRIB_NAME_RE = re.compile(
    r"\s*(?:said|asked|replied|whispered|shouted)\s+(.+?)\s*[.,!?]\s*$",
    re.IGNORECASE,
)


def _voiceStore(scope: Any) -> Any | None:
    project = scope.project
    if project is None:
        return None
    storagePath = project.storage.storagePath
    if not storagePath:
        return None
    from umbraedit.umbra.voicestore import VoiceStore

    return VoiceStore(Path(storagePath))


def _iterAttributionParagraphs(scope: Any) -> Iterable[tuple[str, str]]:
    """Yield (handle, body text) for documents containing attribution spans."""
    project = scope.project
    if project is None:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return
    contentPath = project.storage.contentPath
    if not contentPath:
        return
    for item in project.tree:
        if not item.isFileType():
            continue
        if scope.handles and item.itemHandle not in scope.handles:
            continue
        docFile = contentPath / f"{item.itemHandle}.md"
        if not docFile.is_file():
            continue
        text = docFile.read_text(encoding="utf-8")
        if parseAttrSpans(text):
            yield item.itemHandle, text


def _speakerForName(name: str, index: Any) -> Any | None:
    """Resolve a name to an entity row by tag, alias, or name part."""
    if index is None or not name:
        return None
    norm = aliasNorm(name)
    for row in index.iterEntities():
        if aliasNorm(row.tag) == norm:
            return row
        if any(aliasNorm(alias) == norm for alias in row.aliases):
            return row
        attrs = getattr(row, "attrs", {}) or {}
        for key in ("fn", "mn", "ln", "nick", "title"):
            if attrs.get(key) and aliasNorm(attrs[key]) == norm:
                return row
    return None


def _attributionName(inner: str) -> str:
    m = _ATTRIB_NAME_RE.match(inner.strip())
    if m:
        return m.group(1).strip()
    return inner.strip()


def _codeForRow(row: Any) -> str:
    attrs = getattr(row, "attrs", {}) or {}
    return attrs.get("voice_matrix", "")


def _narrationVoiceCode(handle: str, project: Any) -> str:
    """Return the voice_matrix code of the scene narration speaker.

    Looks up the scene document entity by handle, reads its @pov tag
    (falling back to "narrator"), then returns that speaker's
    voice_matrix code.
    """
    index = project.index
    sceneRow = None
    if hasattr(index, "iterEntities"):
        for row in index.iterEntities():
            if getattr(row, "handle", "") == handle:
                sceneRow = row
                break
    if sceneRow is None:
        return ""
    attrs = getattr(sceneRow, "attrs", {}) or {}
    pov = attrs.get("pov", "")
    povTag = pov.partition("|")[0].strip() or "narrator"
    narratorRow = index.getEntity(povTag) if hasattr(index, "getEntity") else None
    if narratorRow is None:
        return ""
    return _codeForRow(narratorRow)


def _checkAttribDropSameVoice(scope: Any) -> Iterable[Finding]:
    """Block: effective drop is true for a speaker whose voice_matrix
    equals the scene narration voice's voice_matrix.
    """
    store = _voiceStore(scope)
    if store is None:
        return
    project = scope.project
    index = project.index
    for handle, text in _iterAttributionParagraphs(scope):
        narrationCode = _narrationVoiceCode(handle, project)
        for span in parseAttrSpans(text):
            name = _attributionName(span.inner)
            speaker = _speakerForName(name, index)
            if speaker is None:
                continue
            if effectiveDrop(span, speaker) is not True:
                continue
            speakerCode = _codeForRow(speaker)
            if speakerCode and speakerCode == narrationCode:
                yield Finding(
                    ruleId="attribDropSameVoice",
                    severity="block",
                    message=f"Attribution drop for '{speaker.tag}' would silence the scene narration voice.",
                    fix="Remove the attribution drop or assign a different voice matrix.",
                    handle=handle,
                    line=None,
                    detail={"tag": speaker.tag, "code": speakerCode},
                )


def _checkAttribProposalOpen(scope: Any) -> Iterable[Finding]:
    """Advisory: [attr:proposal] spans exist awaiting acceptance."""
    for handle, text in _iterAttributionParagraphs(scope):
        for span in parseAttrSpans(text):
            if span.mode == ATTR_PROPOSAL:
                yield Finding(
                    ruleId="attribProposalOpen",
                    severity="advisory",
                    message=f"Unaccepted attribution proposal in '{handle}'.",
                    fix="Accept or reject the proposal in annotate mode.",
                    handle=handle,
                    line=None,
                    detail={"handle": handle},
                )


registerGate(
    GateRule(
        ruleId="attribDropSameVoice",
        title="Attribution Drop Same Voice",
        operations=frozenset({OP_AUDIO_CHAPTER}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkAttribDropSameVoice,
    )
)

registerGate(
    GateRule(
        ruleId="attribProposalOpen",
        title="Attribution Proposal Open",
        operations=frozenset({OP_AUDIO_CHAPTER}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_checkAttribProposalOpen,
    )
)
