"""
UmbraEdit - Entity Sheet Logic
===============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Manages entity sheets: characters, places, things, organisations.
Handles aliases, attributes, speaker resolution, slots, and the tone
set. Qt-free.
"""  # noqa

from __future__ import annotations

import logging
import re
import unicodedata

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.paths import sheetFile, tonesFile

if TYPE_CHECKING:  # pragma: no cover
    from pathlib import Path

logger = logging.getLogger(__name__)

# Built-in columns for characters, in canonical order
CHARACTER_COLUMNS = [
    "kind",
    "slot",
    "fn",
    "mn",
    "ln",
    "nick",
    "title",
    "suffix",
    "full_name",
    "race",
    "race_detail",
    "age",
    "height",
    "hair",
    "eyes",
    "lang_native",
    "lang_alt",
    "personality",
    "quirks",
    "mannerisms",
    "biggest_fear",
    "biggest_confidence",
    "voice",
    "voice_matrix",
    "drop_attrib",
]
# Built-in columns for places, things, and organisations
PLACE_COLUMNS = ["kind", "description", "lang_native"]
THING_COLUMNS = ["kind", "description", "lang_native"]
ORG_COLUMNS = ["kind", "description", "lang_native"]

# Pattern for custom column keys
CUSTOM_KEY_RE = re.compile(r"^x_[a-z0-9_]{1,30}$")

# All entity kinds
ENTITY_KINDS = ("character", "place", "thing", "organisation", "narrator", "oneoff")


def aliasNorm(text: str) -> str:
    """Normalise an alias for comparison.

    NFKC normalisation, case folding, punctuation removal, and
    whitespace collapsing, so 'Uncle Bob!' and 'uncle  bob' match.
    """
    norm = unicodedata.normalize("NFKC", text).casefold()
    norm = re.sub(r"[^\w\s]", "", norm, flags=re.UNICODE)
    return " ".join(norm.split())


def full_name(attrs: dict[str, str]) -> str:
    """Compute the full name from the name component attributes.

    The value is `{title} {fn} {mn} {ln} {suffix}` with empty parts
    omitted. It is never stored in the note.
    """
    parts = []
    for key in ("title", "fn", "mn", "ln", "suffix"):
        val = attrs.get(key, "")
        if val:
            parts.append(val)
    return " ".join(parts)


@dataclass
class EntityRow:
    """A single entity from the index with its sheet data."""

    tag: str
    handle: str
    kind: str
    displayName: str = ""
    aliases: list[str] = field(default_factory=list)
    attrs: dict[str, str] = field(default_factory=dict)
    # P07: pronunciation entries as (lang, respelling, ipa), and alias
    # respellings keyed by alias text
    prons: list[tuple[str, str, str]] = field(default_factory=list)
    aliasPron: dict[str, str] = field(default_factory=dict)
    # P26: origin of entity ("book" or "bible")
    origin: str = "book"


@dataclass
class ToneEntry:
    """A single tone in the tone set."""

    key: str
    label: str
    appliesTo: str  # "dialogue" | "narration" | "both"
    audioHint: str = ""
    order: int = 0


# The 16 default tones, seeded into umbra/tones.json on first use
DEFAULT_TONES: list[ToneEntry] = [
    ToneEntry("neutral", "Neutral", "both", "", 1),
    ToneEntry("happy", "Happy", "dialogue", "style=cheerful", 2),
    ToneEntry("sad", "Sad", "both", "style=sad", 3),
    ToneEntry("angry", "Angry", "dialogue", "style=angry", 4),
    ToneEntry("excited", "Excited", "both", "style=excited", 5),
    ToneEntry("afraid", "Afraid", "dialogue", "style=afraid", 6),
    ToneEntry("crying", "Crying", "dialogue", "style=crying", 7),
    ToneEntry("laughing", "Laughing", "dialogue", "style=laughing", 8),
    ToneEntry("whisper", "Whisper", "dialogue", "style=whisper", 9),
    ToneEntry("shout", "Shout", "dialogue", "style=shout", 10),
    ToneEntry("tender", "Tender", "dialogue", "style=tender", 11),
    ToneEntry("tired", "Tired", "both", "style=tired", 12),
    ToneEntry("sarcastic", "Sarcastic", "dialogue", "style=sarcastic", 13),
    ToneEntry("calm", "Calm", "narration", "style=calm", 14),
    ToneEntry("measured", "Measured", "narration", "style=measured", 15),
    ToneEntry("tense", "Tense", "narration", "style=tense", 16),
]


class SheetManager:
    """Manages entity sheets for one project.

    Works on an in-memory entity map, which is either built from the
    project tree (`buildFromProject`) or filled by the caller. The
    project path is only needed for the tone set file.
    """

    def __init__(self, projectPath: Path) -> None:
        self._projectPath = projectPath
        self._entityMap: dict[str, EntityRow] = {}
        # Bible entities (read-only, merged for queries)
        self._bibleEntityMap: dict[str, EntityRow] = {}
        # Bible slots (from bible project)
        self._bibleSlots: set[int] = set()

    ##
    #  Speaker Resolution
    ##

    def resolveSpeaker(self, text: str) -> list[EntityRow]:
        """Resolve a speaker name to matching entities.

        Matches tag, display name parts (fn, mn, ln, nick, title), the
        computed full name, and aliases, all through aliasNorm. Returns
        all matches so a shared alias is visible.
        """
        norm = aliasNorm(text)
        if not norm:
            return []
        results = []
        for row in self._entityMap.values():
            if aliasNorm(row.tag) == norm:
                results.append(row)
                continue
            matched = False
            for attrKey in ("fn", "mn", "ln", "nick", "title"):
                attrVal = row.attrs.get(attrKey, "")
                if attrVal and aliasNorm(attrVal) == norm:
                    results.append(row)
                    matched = True
                    break
            if matched:
                continue
            if aliasNorm(full_name(row.attrs)) == norm:
                results.append(row)
                continue
            if any(aliasNorm(alias) == norm for alias in row.aliases):
                results.append(row)
        return results

    ##
    #  Bible Integration
    ##

    def setBibleEntities(self, entities: list[EntityRow], slots: set[int]) -> None:
        """Set bible entities (read-only) and their slots.

        Bible entities are merged into the entity map for queries but
        marked with origin='bible' and cannot be modified.
        """
        self._bibleEntityMap = {e.tag: e for e in entities}
        self._bibleSlots = slots
        # Merge into entity map for resolution, but mark as bible
        for entity in entities:
            if entity.tag not in self._entityMap:
                self._entityMap[entity.tag] = entity

    def getBibleSlots(self) -> set[int]:
        """Return the set of slot numbers used in the bible."""
        return self._bibleSlots.copy()

    def isBibleEntity(self, tag: str) -> bool:
        """Check if an entity originates from the bible."""
        entity = self._entityMap.get(tag)
        if entity is None:
            return False
        return entity.origin == "bible" or entity.attrs.get("_origin") == "bible"

    def canEditEntity(self, tag: str) -> bool:
        """Check if an entity can be edited (not a bible entity)."""
        return not self.isBibleEntity(tag)

    def nextSlot(self) -> int:
        """Return the next free slot number across all characters.

        Bible slots use 1-1000. Book-only slots start above 1000.
        """
        slots = set(self._bibleSlots)
        for row in self._entityMap.values():
            slotVal = row.attrs.get("slot", "")
            if slotVal and slotVal.isdigit():
                slots.add(int(slotVal))

        # First try bible slots (1-1000)
        for slot in range(1, 1001):
            if slot not in slots:
                return slot

        # All bible slots used, use book-only slot above 1000
        slot = max(1001, max(slots, default=1000) + 1)
        return slot

    def promoteOneOff(self, label: str) -> str | None:
        """Promote a one-off speaker (`~the_guard`) to a full entity.

        Creates the tag, assigns the next free slot, and records the
        label as an alias. Returns the new tag, or None when the tag
        already exists. Rewriting the `%Voice:` lines of the project is
        the caller's job (the GUI does it as one undoable batch).
        """
        cleanLabel = label.lstrip("~").replace("_", " ").title()
        tag = cleanLabel.replace(" ", "")
        if not tag or tag in self._entityMap:
            return None
        slot = self.nextSlot()
        row = EntityRow(
            tag=tag,
            handle=f"promoted_{slot:04d}",
            kind="character",
            aliases=[label],
            attrs={"slot": str(slot), "kind": "character"},
        )
        self._entityMap[tag] = row
        return tag

    ##
    #  Alias and Attribute Management
    ##

    def addAlias(self, tag: str, alias: str, originHandle: str = "") -> bool:
        """Add an alias to an entity. Idempotent on aliasNorm.

        Returns True when the alias was added, False when it was
        already present or the tag is unknown or a bible entity.
        """
        if not self.canEditEntity(tag):
            return False
        norm = aliasNorm(alias)
        if not norm:
            return False
        row = self._entityMap.get(tag)
        if row is None:
            return False
        if any(aliasNorm(existing) == norm for existing in row.aliases):
            return False
        row.aliases.append(alias)
        return True

    def setAttr(self, tag: str, key: str, value: str) -> bool:
        """Set an attribute on an entity. Returns False on unknown tag or bible entity."""
        if not self.canEditEntity(tag):
            return False
        row = self._entityMap.get(tag)
        if row is None:
            return False
        row.attrs[key] = value
        return True

    ##
    #  Voice Reference
    ##

    def getVoiceCode(self, tag: str, editionLang: str | None = None) -> str | None:
        """Return the voice_matrix code for a tag, or None.

        The voice matrix itself is a P08 concept; here only the code is
        resolved. `editionLang` is accepted for interface compatibility
        with later features.
        """
        row = self._entityMap.get(tag)
        if row is None:
            return None
        return row.attrs.get("voice_matrix", None)

    def addEntity(self, entity: EntityRow) -> None:
        """Add an entity to the sheet. Used for copying bible entities to book."""
        self._entityMap[entity.tag] = entity

    ##
    #  Slots
    ##

    def buildFromProject(self, project: Any) -> None:
        """Build the entity map from the project tree and note files."""
        self._entityMap.clear()
        for item in project.tree:
            if not item.isFileType():
                continue
            handle = item.itemHandle
            tag = item.itemName
            kind = "character"
            if item.itemClass.name == "WORLD":
                kind = "place"
            elif item.itemClass.name == "OBJECT":
                kind = "thing"
            elif item.itemClass.name == "ENTITY":
                kind = "organisation"
            row = EntityRow(tag=tag, handle=handle, kind=kind)
            docPath = project.storage.contentPath
            if docPath:
                docFile = docPath / f"{handle}.md"
                if docFile.is_file():
                    content = docFile.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        if line.startswith("@alias:"):
                            alias = line[7:].strip().partition("|")[0].strip()
                            if alias:
                                row.aliases.append(alias)
                        elif line.startswith("@attr:"):
                            attrText = line[6:].strip()
                            key, _, value = attrText.partition("|")
                            if key.strip():
                                row.attrs[key.strip()] = value.strip()
            self._entityMap[tag] = row

    ##
    #  Queries
    ##

    def iterEntities(self, kind: str | None = None) -> list[EntityRow]:
        """Return all entities sorted by tag, optionally by kind."""
        return [
            row for row in sorted(self._entityMap.values(), key=lambda r: r.tag) if kind is None or row.kind == kind
        ]

    def getEntity(self, tag: str) -> EntityRow | None:
        """Return an entity by tag, or None."""
        return self._entityMap.get(tag)

    ##
    #  Tone Set
    ##

    def loadTones(self) -> list[ToneEntry]:
        """Load the tone set from umbra/tones.json.

        Seeds the 16 default tones when the file is missing or corrupt.
        Hand-edited unknown tones are returned as they are; flagging
        them is the toneNotInSet gate's job.
        """
        filePath = tonesFile(self._projectPath)
        if filePath.is_file():
            try:
                data = readJson(filePath)
                if isinstance(data, dict):
                    tones = [
                        ToneEntry(
                            key=t.get("key", ""),
                            label=t.get("label", ""),
                            appliesTo=t.get("appliesTo", "both"),
                            audioHint=t.get("audioHint", ""),
                            order=t.get("order", 0),
                        )
                        for t in data.get("tones", [])
                    ]
                    if tones:
                        return tones
            except Exception:
                logger.exception("Could not read the tone set, re-seeding")
        self.saveTones(DEFAULT_TONES)
        return list(DEFAULT_TONES)

    def saveTones(self, tones: list[ToneEntry]) -> None:
        """Save the tone set to umbra/tones.json."""
        data = {
            "v": 1,
            "tones": [
                {"key": t.key, "label": t.label, "appliesTo": t.appliesTo, "audioHint": t.audioHint, "order": t.order}
                for t in tones
            ],
        }
        writeJson(tonesFile(self._projectPath), data)
        from umbraedit.umbra import hooks as _umbraHooks
        _umbraHooks.call(_umbraHooks.SIDECAR_WRITTEN, tonesFile(self._projectPath))

    def save(self) -> None:
        """Save the entity sheet to umbra/sheet.json."""
        data = {
            "v": 1,
            "entities": [
                {
                    "tag": row.tag,
                    "handle": row.handle,
                    "kind": row.kind,
                    "displayName": row.displayName,
                    "aliases": row.aliases,
                    "attrs": row.attrs,
                    "prons": row.prons,
                    "aliasPron": row.aliasPron,
                }
                for row in self._entityMap.values()
            ],
        }
        writeJson(sheetFile(self._projectPath), data)
        from umbraedit.umbra import hooks as _umbraHooks
        _umbraHooks.call(_umbraHooks.SIDECAR_WRITTEN, sheetFile(self._projectPath))
