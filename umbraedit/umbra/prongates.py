"""
UmbraEdit - Pronunciation Gate Rules
=====================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for name pronunciation (P07): missing pronunciations,
missing edition languages, invalid IPA, untracked names, and stale
pronunciations. Imported at the end of `umbra.gates` so the rules are
always registered.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_AUDIO_BOOK,
    OP_AUDIO_CHAPTER,
    OP_BUILD_RUN,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.mentions import findMentions, findUntrackedNames
from umbraedit.umbra.pronunciation import (
    STATUS_CONFIRMED,
    EntityPron,
    Pronunciations,
    parsePronNote,
    validateIpa,
)
from umbraedit.umbra.sheet import EntityRow
from umbraedit.umbra.sheetgates import _iterAllDocs, _iterEntityDocs

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Item classes that hold names (P07 R2)
_NAME_CLASS_KIND = {
    "CHARACTER": "character",
    "WORLD": "place",
    "OBJECT": "thing",
    "ENTITY": "organisation",
}


def _editionLang(scope: Any) -> str:
    """Return the edition language for a scope."""
    lang = scope.options.get("lang", "") if scope.options else ""
    if not lang and getattr(scope, "edition", None):
        lang = str(scope.edition)
    return lang or "en"


def _collectEntities(scope: Any) -> list[EntityRow]:
    """Build entity rows from the name-root notes on disk.

    Gates read the note files directly so they always see the current
    state, independent of index freshness. The scope's handle filter is
    not applied: entity notes are needed regardless of which chapters
    are being built.
    """
    rows: list[EntityRow] = []
    for item, kind, body in _iterEntityDocs(scope, respectHandles=False):
        data: EntityPron = parsePronNote(body)
        if not data.tag:
            continue
        rows.append(
            EntityRow(
                tag=data.tag,
                handle=item.itemHandle,
                kind=kind,
                displayName=data.displayName,
                aliases=list(data.aliasProns),
                attrs={"pron_status": data.status},
                prons=[(lang, resp, ipa) for lang, (resp, ipa) in data.prons.items()],
                aliasPron=dict(data.aliasProns),
            )
        )
    return rows


def _mentionedEntities(scope: Any, entities: list[EntityRow]) -> list[tuple[Any, list[EntityRow]]]:
    """Return (docItem, mentionedEntities) per document in the scope."""
    if not entities:
        return []
    matcherEntities = entities
    result: list[tuple[Any, list[EntityRow]]] = []
    for item, body in _iterAllDocs(scope):
        mentions = findMentions(body, matcherEntities)
        mentionedTags = {m.tag for m in mentions}
        if not mentionedTags:
            continue
        mentioned = [row for row in entities if row.tag in mentionedTags]
        result.append((item, mentioned))
    return result


def _checkPronunciationMissing(scope: Any) -> Iterable[Finding]:
    """Block: an entity mentioned in the chapter has status todo."""
    entities = _collectEntities(scope)
    for item, mentioned in _mentionedEntities(scope, entities):
        for row in mentioned:
            if row.attrs.get("pron_status", "todo") == "todo":
                yield Finding(
                    ruleId="pronunciationMissing",
                    severity="block",
                    message=f"'{row.tag}' is mentioned in '{item.itemName}' but has no pronunciation.",
                    fix="Add an @pron entry to the note, or mark the name as read as written.",
                    handle=item.itemHandle,
                    line=None,
                    detail={"tag": row.tag, "itemName": item.itemName},
                )


def _checkPronunciationLanguageMissing(scope: Any) -> Iterable[Finding]:
    """Block: entities have a pronunciation in another language but
    none for this edition's language.
    """
    lang = _editionLang(scope)
    entities = _collectEntities(scope)
    for item, mentioned in _mentionedEntities(scope, entities):
        for row in mentioned:
            hasAny = bool(row.prons)
            hasLang = any(pronLang == lang for pronLang, _, _ in row.prons)
            if hasAny and not hasLang and row.attrs.get("pron_status") == STATUS_CONFIRMED:
                known = ", ".join(sorted(pronLang for pronLang, _, _ in row.prons))
                yield Finding(
                    ruleId="pronunciationLanguageMissing",
                    severity="block",
                    message=(
                        f"'{row.tag}' has a pronunciation for {known} but none for '{lang}' (needed by this edition)."
                    ),
                    fix=f"Add '@pron: {lang} | <respelling>' to the note for '{row.tag}'.",
                    handle=item.itemHandle,
                    line=None,
                    detail={"tag": row.tag, "lang": lang, "knownLanguages": known},
                )


def _checkPronunciationInvalidIpa(scope: Any) -> Iterable[Finding]:
    """Block: an @pron entry contains invalid IPA.

    Runs on audio operations always, and on build.run only for audio
    targets (scope option `audio`).
    """
    if scope.project is None:
        return
    if scope.operation == OP_BUILD_RUN and not (scope.options or {}).get("audio", False):
        return
    for _item, _kind, body in _iterEntityDocs(scope, respectHandles=False):
        data = parsePronNote(body)
        if not data.tag:
            continue
        for lang, (_resp, ipa) in sorted(data.prons.items()):
            for error in validateIpa(ipa):
                yield Finding(
                    ruleId="pronunciationInvalidIpa",
                    severity="block",
                    message=f"Invalid IPA for '{data.tag}' ({lang}): {error}",
                    fix="Correct the IPA transcription in the @pron entry.",
                    handle=None,
                    line=None,
                    detail={"tag": data.tag, "lang": lang, "error": error},
                )


def _checkNameUntracked(scope: Any) -> Iterable[Finding]:
    """Advisory: capitalised words that match no entity."""
    if scope.project is None:
        return
    entities = _collectEntities(scope)
    texts = [body for _item, body in _iterAllDocs(scope, respectHandles=False)]
    if not texts:
        return
    stoplist = (scope.options or {}).get("stoplist", [])
    for name in findUntrackedNames(texts, entities, stoplist=stoplist):
        yield Finding(
            ruleId="nameUntracked",
            severity="advisory",
            message=f"'{name.word}' occurs {name.count} times but matches no entity.",
            fix="Create an entity sheet for it, add it to an existing sheet, or stoplist it.",
            handle=None,
            line=None,
            detail={"word": name.word, "count": name.count},
        )


def _checkPronunciationStale(scope: Any) -> Iterable[Finding]:
    """Advisory: the display name changed after the pronunciation was
    last confirmed (tracked in umbra/cache/pron-seen.json).
    """
    if scope.project is None:
        return
    try:
        stale = Pronunciations(scope.project).staleEntities()
    except Exception:
        logger.exception("Could not read the pronunciation seen-cache")
        return
    for tag in stale:
        yield Finding(
            ruleId="pronunciationStale",
            severity="advisory",
            message=f"The display name of '{tag}' changed after its pronunciation was last confirmed.",
            fix="Check the pronunciation in the note, then refresh the seen state.",
            handle=None,
            line=None,
            detail={"tag": tag},
        )


registerGate(
    GateRule(
        ruleId="pronunciationMissing",
        title="Pronunciation Missing",
        operations=frozenset({OP_AUDIO_CHAPTER}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkPronunciationMissing,
    )
)

registerGate(
    GateRule(
        ruleId="pronunciationLanguageMissing",
        title="Pronunciation Language Missing",
        operations=frozenset({OP_AUDIO_CHAPTER}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkPronunciationLanguageMissing,
    )
)

registerGate(
    GateRule(
        ruleId="pronunciationInvalidIpa",
        title="Invalid IPA",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK, OP_BUILD_RUN}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkPronunciationInvalidIpa,
    )
)

registerGate(
    GateRule(
        ruleId="nameUntracked",
        title="Name Without A Sheet",
        operations=frozenset({OP_BUILD_RUN, OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_checkNameUntracked,
    )
)

registerGate(
    GateRule(
        ruleId="pronunciationStale",
        title="Pronunciation Stale",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_checkPronunciationStale,
    )
)
