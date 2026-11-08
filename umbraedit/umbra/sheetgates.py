"""
UmbraEdit - Sheet Gate Rules
=============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for entity sheets (P06): alias collisions, duplicate slots,
tones missing from the tone set, and entity notes without a kind.
Imported at the end of `umbra.gates` so the rules are always
registered.
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
from umbraedit.umbra.sheet import SheetManager, aliasNorm
from umbraedit.umbra.voiceline import isVoiceLine, parseVoiceLine

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Map from item class name to entity kind
_CLASS_KIND = {
    "CHARACTER": "character",
    "WORLD": "place",
    "OBJECT": "thing",
    "ENTITY": "organisation",
}


def _iterEntityDocs(scope: Any, respectHandles: bool = True) -> Iterable[tuple[Any, str, str]]:
    """Yield (item, kind, noteText) for documents in the name roots.

    The note text is the body after the `+++` header separator when one
    exists. With `respectHandles` the scope's handle filter limits the
    yield; entity collection passes False because entity notes are
    needed regardless of which chapters are being built.
    """
    proj = scope.project
    if not proj:
        return
    contentPath = proj.storage.contentPath
    if not contentPath:
        return
    for item in proj.tree:
        if not item.isFileType():
            continue
        kind = _CLASS_KIND.get(item.itemClass.name, "")
        if not kind:
            continue
        if respectHandles and scope.handles and item.itemHandle not in scope.handles:
            continue
        docFile = contentPath / f"{item.itemHandle}.md"
        if not docFile.is_file():
            continue
        text = docFile.read_text(encoding="utf-8")
        parts = text.split("+++", 2)
        body = parts[2] if len(parts) >= 3 else text
        yield item, kind, body


def _iterAllDocs(scope: Any, respectHandles: bool = True) -> Iterable[tuple[Any, str]]:
    """Yield (item, body) for every file-type document in the scope.

    Used by the tone check and the mention scan, because `%Voice:`
    lines and name mentions live in novel chapters as well as in notes.
    """
    proj = scope.project
    if not proj:
        return
    contentPath = proj.storage.contentPath
    if not contentPath:
        return
    for item in proj.tree:
        if not item.isFileType():
            continue
        if respectHandles and scope.handles and item.itemHandle not in scope.handles:
            continue
        docFile = contentPath / f"{item.itemHandle}.md"
        if not docFile.is_file():
            continue
        text = docFile.read_text(encoding="utf-8")
        parts = text.split("+++", 2)
        body = parts[2] if len(parts) >= 3 else text
        yield item, body


def _parseSheetLines(body: str) -> tuple[str, list[str], dict[str, str]]:
    """Extract (tag, aliases, attrs) from a note body."""
    tag = ""
    aliases: list[str] = []
    attrs: dict[str, str] = {}
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("@"):
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "@tag" and not tag:
            tag = value.partition("|")[0].strip()
        elif key == "@alias":
            alias = value.partition("|")[0].strip()
            if alias:
                aliases.append(alias)
        elif key == "@attr":
            attrKey, _, attrValue = value.partition("|")
            attrKey = attrKey.strip()
            if attrKey:
                attrs[attrKey.strip()] = attrValue.strip()
    return tag, aliases, attrs


def _checkAliasCollision(scope: Any) -> Iterable[Finding]:
    """Advisory: two or more entities share an alias (or a tag and an
    alias normalise to the same name).
    """
    owners: dict[str, list[str]] = {}
    for _item, _kind, body in _iterEntityDocs(scope):
        tag, aliases, _attrs = _parseSheetLines(body)
        if not tag:
            continue
        for name in [tag, *aliases]:
            norm = aliasNorm(name)
            if not norm:
                continue
            owners.setdefault(norm, []).append(tag)
    for norm, tags in sorted(owners.items()):
        uniqueTags = sorted(set(tags))
        if len(uniqueTags) > 1:
            yield Finding(
                ruleId="aliasCollision",
                severity="advisory",
                message=f"The alias '{norm}' is shared by: {', '.join(uniqueTags)}.",
                fix="Give each entity a distinct alias, or pick the right one when resolving the speaker.",
                handle=None,
                line=None,
                detail={"alias": norm, "tags": uniqueTags},
            )


def _checkSlotDuplicate(scope: Any) -> Iterable[Finding]:
    """Block: two characters have the same slot number."""
    slotOwners: dict[int, list[str]] = {}
    for _item, _kind, body in _iterEntityDocs(scope):
        tag, _aliases, attrs = _parseSheetLines(body)
        if not tag:
            continue
        slotValue = attrs.get("slot", "")
        if slotValue.isdigit():
            slotOwners.setdefault(int(slotValue), []).append(tag)
    for slot, tags in sorted(slotOwners.items()):
        uniqueTags = sorted(set(tags))
        if len(uniqueTags) > 1:
            yield Finding(
                ruleId="slotDuplicate",
                severity="block",
                message=f"Slot {slot} is assigned to multiple characters: {', '.join(uniqueTags)}.",
                fix="Give each character a unique slot number in the Sheets view.",
                handle=None,
                line=None,
                detail={"slot": slot, "tags": uniqueTags},
            )


def _checkToneNotInSet(scope: Any) -> Iterable[Finding]:
    """Block: a tone key in a %Voice: line is missing from tones.json.

    The value stays in the file; the operation is blocked until the
    tone is added to the set or the annotation is corrected.
    """
    proj = scope.project
    if not proj:
        return
    storagePath = proj.storage.storagePath
    if not storagePath:
        return
    known: set[str] = set()
    try:
        manager = SheetManager(storagePath)
        known = {t.key for t in manager.loadTones()}
    except Exception:
        logger.exception("Could not load the tone set for the toneNotInSet gate")
        return
    if not known:
        return

    for item, body in _iterAllDocs(scope):
        for lineNo, line in enumerate(body.split("\n"), start=1):
            if not isVoiceLine(line):
                continue
            data = parseVoiceLine(line)
            if data is None:
                continue
            for field in ("tone", "ntone"):
                value = getattr(data, field, None)
                if not value:
                    continue
                toneKey = value.partition(":")[0].strip()
                if toneKey and toneKey not in known:
                    yield Finding(
                        ruleId="toneNotInSet",
                        severity="block",
                        message=f"Tone '{toneKey}' is not in the tone set.",
                        fix="Add the tone to the tone set, or use an existing tone.",
                        handle=item.itemHandle,
                        line=lineNo,
                        detail={"tone": toneKey, "field": field, "known": sorted(known)},
                    )


def _checkEntityKindMissing(scope: Any) -> Iterable[Finding]:
    """Advisory: a note in a name root has no `@attr: kind`."""
    for item, kind, body in _iterEntityDocs(scope):
        _tag, _aliases, attrs = _parseSheetLines(body)
        if attrs.get("kind", ""):
            continue
        yield Finding(
            ruleId="entityKindMissing",
            severity="advisory",
            message=f"The note '{item.itemName}' has no '@attr: kind' line.",
            fix=f"Add '@attr: kind | {kind}' to the note.",
            handle=item.itemHandle,
            line=None,
            detail={"itemName": item.itemName, "impliedKind": kind},
        )


registerGate(
    GateRule(
        ruleId="aliasCollision",
        title="Alias Collision",
        operations=frozenset({OP_BUILD_RUN, OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_checkAliasCollision,
    )
)

registerGate(
    GateRule(
        ruleId="slotDuplicate",
        title="Duplicate Slot",
        operations=frozenset({OP_BUILD_RUN}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkSlotDuplicate,
    )
)

registerGate(
    GateRule(
        ruleId="toneNotInSet",
        title="Tone Not In Set",
        operations=frozenset({OP_AUDIO_CHAPTER, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkToneNotInSet,
    )
)

registerGate(
    GateRule(
        ruleId="entityKindMissing",
        title="Entity Kind Missing",
        operations=frozenset({OP_BUILD_RUN}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_checkEntityKindMissing,
    )
)
