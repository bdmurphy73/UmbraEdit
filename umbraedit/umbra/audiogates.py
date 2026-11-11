"""
UmbraEdit - Audio Gate Rules
=============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for audio package (P31): speaker unassigned, voice matrix missing,
voice matrix unknown, voice matrix corrupt, voice matrix language mismatch,
attribution drop same voice, tone not in set, token unresolved, pronunciation
missing, pronunciation language missing, pronunciation invalid IPA,
asset corrupt, sync conflict open, voice line orphan, file unrecoverable,
book audio incomplete, cover missing, cover invalid, audiobook narrator missing.
"""  # noqa

from __future__ import annotations

import json
import logging

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_AUDIO_BOOK,
    OP_AUDIO_CHAPTER,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.sheet import SheetManager
from umbraedit.umbra.utterances import deriveUtterances
from umbraedit.umbra.voicestore import VoiceStore

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


# Rule IDs
RULE_AUDIOBOOK_SPEAKER_UNASSIGNED = "audiobookSpeakerUnassigned"
RULE_AUDIOBOOK_VOICE_MATRIX_MISSING = "audiobookVoiceMatrixMissing"
RULE_AUDIOBOOK_VOICE_MATRIX_UNKNOWN = "audiobookVoiceMatrixUnknown"
RULE_AUDIOBOOK_VOICE_MATRIX_CORRUPT = "audiobookVoiceMatrixCorrupt"
RULE_AUDIOBOOK_VOICE_MATRIX_LANGUAGE = "audiobookVoiceMatrixLanguage"
RULE_AUDIOBOOK_ATTRIB_DROP_SAME_VOICE = "audiobookAttribDropSameVoice"
RULE_AUDIOBOOK_TONE_NOT_IN_SET = "audiobookToneNotInSet"
RULE_AUDIOBOOK_TOKEN_UNRESOLVED = "audiobookTokenUnresolved"
RULE_AUDIOBOOK_PRONUNCIATION_MISSING = "audiobookPronunciationMissing"
RULE_AUDIOBOOK_PRONUNCIATION_LANGUAGE_MISSING = "audiobookPronunciationLanguageMissing"
RULE_AUDIOBOOK_PRONUNCIATION_INVALID_IPA = "audiobookPronunciationInvalidIpa"
RULE_AUDIOBOOK_ASSET_CORRUPT = "audiobookAssetCorrupt"
RULE_AUDIOBOOK_SYNC_CONFLICT_OPEN = "audiobookSyncConflictOpen"
RULE_AUDIOBOOK_VOICE_LINE_ORPHAN = "audiobookVoiceLineOrphan"
RULE_AUDIOBOOK_FILE_UNRECOVERABLE = "audiobookFileUnrecoverable"
RULE_BOOK_AUDIO_INCOMPLETE = "bookAudioIncomplete"
RULE_AUDIOBOOK_COVER_MISSING = "audiobookCoverMissing"
RULE_AUDIOBOOK_COVER_INVALID = "audiobookCoverInvalid"
RULE_AUDIOBOOK_NARRATOR_MISSING = "audiobookNarratorMissingAudio"


def _audiobookSpeakerUnassignedFindings(scope: Any) -> Iterable[Finding]:
    """Block audio.chapter: a speaker tag used in the chapter has no entity note."""
    project = scope.project
    if not project:
        return iter([])
    storage_path = project.storage.storagePath
    if not storage_path:
        return iter([])

    # Get edition info from options
    edition_id = scope.options.get("edition", "") if scope.options else ""
    if not edition_id:
        return iter([])

    project_path = Path(project.storage.storagePath)
    edition_path = project_path.parent / f"{project_path.name}-ed-{edition_id}"
    if not edition_path.exists():
        return iter([])

    sheet = SheetManager(edition_path / "umbra")
    sheet.buildFromProject(str(edition_path))

    # Get chapter handle from options
    chapter_handle = scope.options.get("chapter", "") if scope.options else ""
    if not chapter_handle:
        return iter([])

    # Get utterances for chapter and check speakers
    store = VoiceStore(edition_path)

    try:
        utterances = deriveUtterances(
            handle=chapter_handle,
            text="",  # Would need to read chapter text
            project=scope.project,
            index=sheet,
            store=store,
        )
    except Exception:
        return iter([])

    for u in utterances:
        speaker = u.speaker
        if speaker:
            entity = sheet.getEntity(speaker)
            if not entity:
                yield Finding(
                    ruleId=RULE_AUDIOBOOK_SPEAKER_UNASSIGNED,
                    severity="block",
                    message=f"Speaker '{speaker}' has no entity note in edition",
                    fix=f"Create an entity note for '{speaker}' in the edition",
                    handle=chapter_handle,
                    detail={"speaker": speaker},
                )


def _audiobookVoiceMatrixMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block: a speaker's voice matrix is missing."""
    # TODO: Implement
    return iter([])


def _audiobookVoiceMatrixUnknownFindings(scope: Any) -> Iterable[Finding]:
    """Block: a speaker's voice matrix code is unknown."""
    # TODO: Implement
    return iter([])


def _audiobookVoiceMatrixCorruptFindings(scope: Any) -> Iterable[Finding]:
    """Block: a voice matrix file is corrupt (trailer hash mismatch)."""
    # TODO: Implement
    return iter([])


def _audiobookVoiceMatrixLanguageFindings(scope: Any) -> Iterable[Finding]:
    """Block: voice matrix language doesn't match edition language."""
    # TODO: Implement
    return iter([])


def _audiobookAttribDropSameVoiceFindings(scope: Any) -> Iterable[Finding]:
    """Block: attribution dropped but voice code is same as narrator."""
    # TODO: Implement
    return iter([])


def _audiobookToneNotInSetFindings(scope: Any) -> Iterable[Finding]:
    """Advisory: tone not in tone set."""
    # TODO: Implement
    return iter([])


def _audiobookTokenUnresolvedFindings(scope: Any) -> Iterable[Finding]:
    """Block: unresolved token in chapter."""
    # TODO: Implement
    return iter([])


def _audiobookPronunciationMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block: pronunciation missing for entity in chapter."""
    # TODO: Implement
    return iter([])


def _audiobookPronunciationLanguageMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block: pronunciation missing for edition language."""
    # TODO: Implement
    return iter([])


def _audiobookPronunciationInvalidIpaFindings(scope: Any) -> Iterable[Finding]:
    """Block: pronunciation has invalid IPA."""
    # TODO: Implement
    return iter([])


def _audiobookAssetCorruptFindings(scope: Any) -> Iterable[Finding]:
    """Block: asset (voice matrix, cover, etc.) is corrupt."""
    # TODO: Implement
    return iter([])


def _audiobookSyncConflictOpenFindings(scope: Any) -> Iterable[Finding]:
    """Block: open sync conflicts exist."""
    from umbraedit.umbra.sync.conflicts import ConflictsStore

    project = scope.project
    if not project:
        return iter([])
    storage_path = project.storage.storagePath
    if not storage_path:
        return iter([])

    store = ConflictsStore(storage_path)
    count = store.open_count()
    if count > 0:
        yield Finding(
            ruleId=RULE_AUDIOBOOK_SYNC_CONFLICT_OPEN,
            severity="block",
            message=f"{count} open sync conflict(s) - resolve before building audio",
            fix="Open the Conflicts panel and resolve all open conflicts.",
            handle=None,
            detail={"openConflicts": count},
        )


def _audiobookVoiceLineOrphanFindings(scope: Any) -> Iterable[Finding]:
    """Advisory: %Voice: line has no following paragraph."""
    # TODO: Implement
    return iter([])


def _audiobookFileUnrecoverableFindings(scope: Any) -> Iterable[Finding]:
    """Block: file cannot be recovered."""
    # TODO: Implement
    return iter([])


def _bookAudioIncompleteFindings(scope: Any) -> Iterable[Finding]:
    """Block: not all chapters are ready for audio book."""
    project = scope.project
    if not project:
        return iter([])
    storage_path = project.storage.storagePath
    if not storage_path:
        return iter([])

    # Check edition
    edition_id = scope.options.get("edition", "") if scope.options else ""
    if not edition_id:
        return iter([])

    project_path = Path(project.storage.storagePath)
    edition_path = project_path.parent / f"{project_path.name}-ed-{edition_id}"
    if not edition_path.exists():
        return iter([])

    # Check audio directory
    audio_dir = edition_path / "audio" / edition_id
    if not audio_dir.exists():
        yield Finding(
            ruleId=RULE_BOOK_AUDIO_INCOMPLETE,
            severity="block",
            message="Audio package not built for this edition",
            fix="Build audio chapters first",
            handle="audio",
            detail={},
        )
        return iter([])

    # Check manifest
    manifest_path = edition_path / "audio" / edition_id / "manifest.json"
    if not manifest_path.exists():
        yield Finding(
            ruleId=RULE_BOOK_AUDIO_INCOMPLETE,
            severity="block",
            message="Audio package manifest not found",
            fix="Build audio chapters first",
            handle="audio",
            detail={},
        )
        return iter([])

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        yield Finding(
            ruleId=RULE_BOOK_AUDIO_INCOMPLETE,
            severity="block",
            message="Audio package manifest is corrupt",
            fix="Rebuild audio package",
            handle="audio",
            detail={},
        )
        return iter([])

    # Check all chapters are ready
    incomplete = [
        chapter.get("handle", "")
        for chapter in manifest.get("chapters", [])
        if chapter.get("status") != "ready"
    ]

    if incomplete:
        yield Finding(
            ruleId=RULE_BOOK_AUDIO_INCOMPLETE,
            severity="block",
            message=f"Chapters not ready: {', '.join(incomplete)}",
            fix="Build remaining chapters with 'audio.chapter'",
            handle="audio",
            detail={"incomplete_chapters": incomplete},
        )


def _audiobookCoverMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block: audiobook cover is missing."""
    # TODO: Implement
    return iter([])


def _audiobookCoverInvalidFindings(scope: Any) -> Iterable[Finding]:
    """Block: audiobook cover is invalid."""
    # TODO: Implement
    return iter([])


def _audiobookNarratorMissingAudioFindings(scope: Any) -> Iterable[Finding]:
    """Block: audiobook narrator not configured."""
    # TODO: Implement
    return iter([])


registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_SPEAKER_UNASSIGNED,
        title="Audiobook Speaker Unassigned",
        operations=frozenset({OP_AUDIO_CHAPTER}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookSpeakerUnassignedFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_VOICE_MATRIX_MISSING,
        title="Audiobook Voice Matrix Missing",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookVoiceMatrixMissingFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_VOICE_MATRIX_UNKNOWN,
        title="Audiobook Voice Matrix Unknown",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookVoiceMatrixUnknownFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_VOICE_MATRIX_CORRUPT,
        title="Audiobook Voice Matrix Corrupt",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookVoiceMatrixCorruptFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_VOICE_MATRIX_LANGUAGE,
        title="Audiobook Voice Matrix Language Mismatch",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookVoiceMatrixLanguageFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_ATTRIB_DROP_SAME_VOICE,
        title="Audiobook Attribution Drop Same Voice",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookAttribDropSameVoiceFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_TONE_NOT_IN_SET,
        title="Audiobook Tone Not In Set",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_audiobookToneNotInSetFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_TOKEN_UNRESOLVED,
        title="Audiobook Token Unresolved",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookTokenUnresolvedFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_PRONUNCIATION_MISSING,
        title="Audiobook Pronunciation Missing",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookPronunciationMissingFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_PRONUNCIATION_LANGUAGE_MISSING,
        title="Audiobook Pronunciation Language Missing",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookPronunciationLanguageMissingFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_PRONUNCIATION_INVALID_IPA,
        title="Audiobook Pronunciation Invalid IPA",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookPronunciationInvalidIpaFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_ASSET_CORRUPT,
        title="Audiobook Asset Corrupt",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookAssetCorruptFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_SYNC_CONFLICT_OPEN,
        title="Audiobook Sync Conflict Open",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookSyncConflictOpenFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_VOICE_LINE_ORPHAN,
        title="Audiobook Voice Line Orphan",
        operations=frozenset({OP_AUDIO_CHAPTER}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_audiobookVoiceLineOrphanFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_FILE_UNRECOVERABLE,
        title="Audiobook File Unrecoverable",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookFileUnrecoverableFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_BOOK_AUDIO_INCOMPLETE,
        title="Book Audio Incomplete",
        operations=frozenset({OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_bookAudioIncompleteFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_COVER_MISSING,
        title="Audiobook Cover Missing",
        operations=frozenset({OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookCoverMissingFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_COVER_INVALID,
        title="Audiobook Cover Invalid",
        operations=frozenset({OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookCoverInvalidFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_AUDIOBOOK_NARRATOR_MISSING,
        title="Audiobook Narrator Missing",
        operations=frozenset({OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_audiobookNarratorMissingAudioFindings,
    )
)

