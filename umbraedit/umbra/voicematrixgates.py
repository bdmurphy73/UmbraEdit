"""
UmbraEdit - Voice Matrix Gate Rules
====================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for voice matrices (P07/P08): missing, unknown, corrupt,
wrong-language, and retired voice matrices. Registered via ``umbra.gates``.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_AUDIO_BOOK,
    OP_AUDIO_CHAPTER,
    OP_SYNC_PUSH,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.sheetgates import _iterAllDocs
from umbraedit.umbra.voiceline import isVoiceLine, parseVoiceLine
from umbraedit.umbra.voicematrix import VoiceMatrixError, parseVoiceMatrix
from umbraedit.umbra.voicestore import VoiceStore

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# The narrator is the entity with kind = narrator, tag "Narrator".
NARRATOR_TAG = "Narrator"


def _voiceStore(scope: Any) -> VoiceStore | None:
    project = scope.project
    if project is None:
        return None
    storagePath = project.storage.storagePath
    if not storagePath:
        return None
    from pathlib import Path

    return VoiceStore(Path(storagePath))


def _speakerTagsInChapter(scope: Any) -> set[str]:
    """Collect the speaker tags referenced by %Voice: lines in chapter
    documents, plus the narrator tag when narration is present.
    """
    tags: set[str] = set()
    for _item, body in _iterAllDocs(scope):
        for line in body.split("\n"):
            if not isVoiceLine(line):
                continue
            data = parseVoiceLine(line)
            if data is None:
                continue
            spk = data.spk
            if spk and spk != "narrator" and not spk.startswith("~"):
                tags.add(spk)
            if data.scope == "scene" and data.ntone:
                tags.add(NARRATOR_TAG)
    return tags


def _entityVoiceCodes(scope: Any) -> dict[str, str]:
    """Map entity tag -> voice_matrix code for all indexed entities."""
    project = scope.project
    if project is None:
        return {}
    result: dict[str, str] = {}
    for row in project.index.iterEntities():
        code = row.attrs.get("voice_matrix", "")
        if code:
            result[row.tag] = code
    return result


def _checkVoiceMatrixMissing(scope: Any) -> Iterable[Finding]:
    """Block: a speaker with dialogue in the chapter, or the narration
    voice, has no voice_matrix code.
    """
    store = _voiceStore(scope)
    if store is None:
        return
    project = scope.project
    tags = _speakerTagsInChapter(scope)
    for tag in tags:
        row = project.index.getEntity(tag) if project else None
        if row is None:
            continue
        if not row.attrs.get("voice_matrix", ""):
            yield Finding(
                ruleId="voiceMatrixMissing",
                severity="block",
                message=f"'{tag}' speaks in this chapter but has no voice matrix assigned.",
                fix=f"Assign a voice matrix to '{tag}' in the Voices picker or sheet.",
                handle=None,
                line=None,
                detail={"tag": tag},
            )


def _checkVoiceMatrixUnknown(scope: Any) -> Iterable[Finding]:
    """Block: a voice_matrix code is not in the registry or its asset
    is missing.
    """
    store = _voiceStore(scope)
    if store is None:
        return
    codes = _entityVoiceCodes(scope).values()
    for code in codes:
        entry = store.getVoiceEntry(code)
        if entry is None:
            yield Finding(
                ruleId="voiceMatrixUnknown",
                severity="block",
                message=f"Voice matrix '{code}' is not registered.",
                fix="Import the voice matrix or correct the voice_matrix attribute.",
                handle=None,
                line=None,
                detail={"code": code},
            )
            continue
        if store.getVoiceMatrix(code) is None:
            yield Finding(
                ruleId="voiceMatrixUnknown",
                severity="block",
                message=f"Voice matrix '{code}' is registered but its asset file is missing.",
                fix="Re-import the voice matrix asset.",
                handle=None,
                line=None,
                detail={"code": code},
            )


def _checkVoiceMatrixCorrupt(scope: Any) -> Iterable[Finding]:
    """Block: a registered matrix's trailer hash no longer matches its
    content (audio.chapter and sync.push).
    """
    store = _voiceStore(scope)
    if store is None:
        return
    for entry in store.listVoices(includeRetired=True):
        data = store.getVoiceMatrix(entry.code)
        if data is None:
            continue
        try:
            parseVoiceMatrix(data)
        except VoiceMatrixError as exc:
            yield Finding(
                ruleId="voiceMatrixCorrupt",
                severity="block",
                message=f"Voice matrix '{entry.code}' is corrupt: {exc}",
                fix="Re-import the voice matrix; matrices are immutable.",
                handle=None,
                line=None,
                detail={"code": entry.code, "error": str(exc)},
            )


def _checkVoiceMatrixLanguage(scope: Any) -> Iterable[Finding]:
    """Block: the matrix's languages do not include the utterance
    (edition) language.
    """
    store = _voiceStore(scope)
    if store is None:
        return
    lang = scope.options.get("lang", "") if scope.options else ""
    if not lang:
        return
    project = scope.project
    tags = _speakerTagsInChapter(scope)
    for tag in tags:
        row = project.index.getEntity(tag) if project else None
        if row is None:
            continue
        code = row.attrs.get("voice_matrix", "")
        if not code:
            continue
        entry = store.getVoiceEntry(code)
        if entry is None:
            continue
        if lang not in entry.languages:
            yield Finding(
                ruleId="voiceMatrixLanguage",
                severity="block",
                message=(f"Voice matrix '{entry.code}' for '{tag}' does not support language '{lang}'."),
                fix=(f"Import a matrix for '{tag}' that speaks '{lang}', or change the edition language."),
                handle=None,
                line=None,
                detail={"code": entry.code, "tag": tag, "lang": lang},
            )


def _checkVoiceMatrixRetired(scope: Any) -> Iterable[Finding]:
    """Advisory: a retired voice matrix code is still in use."""
    store = _voiceStore(scope)
    if store is None:
        return
    codes = _entityVoiceCodes(scope).values()
    for code in codes:
        entry = store.getVoiceEntry(code)
        if entry is not None and entry.retired:
            yield Finding(
                ruleId="voiceMatrixRetired",
                severity="advisory",
                message=f"Voice matrix '{code}' is retired but still in use.",
                fix="Re-assign a current voice matrix, or un-retire it.",
                handle=None,
                line=None,
                detail={"code": code},
            )


registerGate(
    GateRule(
        ruleId="voiceMatrixMissing",
        title="Voice Matrix Missing",
        operations=frozenset({OP_AUDIO_CHAPTER}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkVoiceMatrixMissing,
    )
)

registerGate(
    GateRule(
        ruleId="voiceMatrixUnknown",
        title="Voice Matrix Unknown",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_SYNC_PUSH}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkVoiceMatrixUnknown,
    )
)

registerGate(
    GateRule(
        ruleId="voiceMatrixCorrupt",
        title="Voice Matrix Corrupt",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_SYNC_PUSH}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkVoiceMatrixCorrupt,
    )
)

registerGate(
    GateRule(
        ruleId="voiceMatrixLanguage",
        title="Voice Matrix Language",
        operations=frozenset({OP_AUDIO_CHAPTER}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkVoiceMatrixLanguage,
    )
)

registerGate(
    GateRule(
        ruleId="voiceMatrixRetired",
        title="Voice Matrix Retired",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_checkVoiceMatrixRetired,
    )
)
