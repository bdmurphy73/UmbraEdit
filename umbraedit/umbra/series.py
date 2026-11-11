"""
UmbraEdit - Series Bible
========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import logging

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.paths import bibleSeenFile, seriesFile
from umbraedit.umbra.sheet import EntityRow, SheetManager, ToneEntry

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

    from umbraedit.umbra.voicestore import VoiceStore

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DEFAULT_SERIES = {
    "v": SCHEMA_VERSION,
    "series": "",
    "bible": "",
    "bookNumber": 0,
}


@dataclass(frozen=True)
class SeriesInfo:
    """Series configuration for a book project."""

    v: int = 1
    series: str = ""
    bible: str = ""
    bookNumber: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "v": self.v,
            "series": self.series,
            "bible": self.bible,
            "bookNumber": self.bookNumber,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeriesInfo:
        """Create SeriesInfo from dictionary."""
        return cls(
            v=data.get("v", 1),
            series=data.get("series", ""),
            bible=data.get("bible", ""),
            bookNumber=data.get("bookNumber", 0),
        )

    def is_valid(self) -> bool:
        """Check if series configuration is valid."""
        return bool(self.series and self.bible and self.bookNumber > 0)


def loadSeries(projectPath: Path) -> SeriesInfo:
    """Load series info from project's umbra/series.json."""
    path = seriesFile(projectPath)
    if not path.is_file():
        return SeriesInfo()
    try:
        data = readJson(path)
        if isinstance(data, dict):
            return SeriesInfo.from_dict(data)
        logger.warning("series.json does not contain an object, returning defaults")
        return SeriesInfo()
    except Exception:
        logger.exception("Failed to load series from %s", path)
        return SeriesInfo()


def saveSeries(projectPath: Path, series: SeriesInfo) -> None:
    """Save series info to project's umbra/series.json atomically."""
    path = seriesFile(projectPath)
    path.parent.mkdir(parents=True, exist_ok=True)
    writeJson(path, series.to_dict())


def getBiblePath(projectPath: Path, series: SeriesInfo) -> Path | None:
    """Get the absolute path to the bible project."""
    if not series.bible:
        return None
    # bible path is relative to the project directory
    return (projectPath / series.bible).resolve()


def loadBibleEntities(biblePath: Path) -> list[EntityRow]:
    """Load all entities from the bible project."""
    if not biblePath.exists():
        return []

    sheet_file = biblePath / "umbra" / "sheet.json"
    if not sheet_file.is_file():
        return []

    try:
        data = readJson(sheet_file)
        if not isinstance(data, dict):
            return []
    except Exception:
        return []

    entities = []
    for entity_data in data.get("entities", []):
        try:
            entity = EntityRow(**entity_data)
            # Mark as bible origin
            entity.origin = "bible"
            entity.attrs["_origin"] = "bible"
            entities.append(entity)
        except Exception:
            continue

    return entities


def loadBibleVoiceStore(biblePath: Path) -> VoiceStore:
    """Load the voice store from the bible project."""
    from umbraedit.umbra.voicestore import VoiceStore
    return VoiceStore(biblePath)


def loadBibleTones(biblePath: Path) -> list:
    """Load the tone set from the bible project."""
    tones_file = biblePath / "umbra" / "tones.json"
    if not tones_file.is_file():
        from umbraedit.umbra.sheet import DEFAULT_TONES
        return list(DEFAULT_TONES)

    try:
        data = readJson(tones_file)
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
        pass
    from umbraedit.umbra.sheet import DEFAULT_TONES
    return list(DEFAULT_TONES)


def loadBibleSlots(biblePath: Path) -> set[int]:
    """Load all used slot numbers from the bible project."""
    if not biblePath.exists():
        return set()

    sheet_file = biblePath / "umbra" / "sheet.json"
    if not sheet_file.is_file():
        return set()

    try:
        data = readJson(sheet_file)
        if not isinstance(data, dict):
            return set()
    except Exception:
        return set()

    slots = set()
    for entity_data in data.get("entities", []):
        try:
            entity = EntityRow(**entity_data)
            slot_val = entity.attrs.get("slot", "")
            if slot_val and slot_val.isdigit():
                slots.add(int(slot_val))
        except Exception:
            continue
    return slots


def getNextBibleSlot(bookSheet: SheetManager, bibleSlots: set[int]) -> int:
    """Get the next slot number, preferring bible's counter.

    Bible slots use 1-1000, book-only slots start above 1000.
    """
    # First try to use next bible slot
    for slot in range(1, 1001):
        if slot not in bibleSlots:
            # Check if book already uses this slot
            book_slots = {
                int(e.attrs["slot"])
                for e in bookSheet.iterEntities(kind="character")
                if e.attrs.get("slot", "").isdigit()
            }
            if slot not in book_slots:
                return slot

    # All bible slots used, use book-only slot above 1000
    return max(1001, bookSheet.nextSlot())


def _loadBibleSeen(projectPath: Path) -> dict[str, Any]:
    """Load bible seen state from cache."""
    path = bibleSeenFile(projectPath)
    if not path.is_file():
        return {"bibleChangeCounter": 0}
    try:
        data = readJson(path)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"bibleChangeCounter": 0}


def _saveBibleSeen(projectPath: Path, changeCounter: int) -> None:
    """Save bible seen state to cache atomically."""
    path = bibleSeenFile(projectPath)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"bibleChangeCounter": changeCounter}
    writeJson(path, data)


def getBibleChangeCounter(biblePath: Path) -> int:
    """Get the bible's change counter from its journal."""
    journal_path = biblePath / "umbra" / "journal.jsonl"
    if not journal_path.is_file():
        return 0

    # Count entries as a simple change counter
    # In production, this could be a more sophisticated counter
    try:
        with open(journal_path, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def checkBibleChanged(projectPath: Path, biblePath: Path) -> tuple[bool, int]:
    """Check if bible has changed since last build.

    Returns (has_changed, current_counter).
    """
    current = getBibleChangeCounter(biblePath)
    seen = _loadBibleSeen(projectPath)
    last_seen = seen.get("bibleChangeCounter", 0)
    return current > last_seen, current


def markBibleSeen(projectPath: Path, biblePath: Path) -> None:
    """Mark current bible change counter as seen."""
    counter = getBibleChangeCounter(biblePath)
    _saveBibleSeen(projectPath, counter)


def iterBibleEntities(
    bookProjectPath: Path,
    kind: str | None = None,
) -> Iterable[EntityRow]:
    """Iterate all entities from the bible, marked with origin='bible'."""
    series_info = loadSeries(bookProjectPath)
    if not series_info.is_valid():
        return

    bible_path = getBiblePath(bookProjectPath, series_info)
    if not bible_path or not bible_path.exists():
        return

    for entity in loadBibleEntities(bible_path):
        if kind is None or entity.kind == kind:
            yield entity


def checkTagShadow(bookProject: Any, tag: str) -> bool:
    """Check if a tag exists in both book and bible (shadowing).

    Returns True if the tag is shadowed (book wins).
    """
    series_info = loadSeries(bookProject.storage.storagePath)
    if not series_info.is_valid():
        return False

    bible_path = getBiblePath(bookProject.storage.storagePath, series_info)
    if not bible_path or not bible_path.exists():
        return False

    # Check if bible has this tag
    bible_entities = loadBibleEntities(bible_path)
    bible_tags = {e.tag for e in bible_entities}
    if tag not in bible_tags:
        return False

    # Check if book also has this tag
    book_sheet = SheetManager(bookProject.storage.storagePath / "umbra")
    book_sheet.buildFromProject(bookProject)
    return book_sheet.getEntity(tag) is not None


def copyEntityToBook(bibleEntity: EntityRow, bookProjectPath: Path, bookSheet: SheetManager) -> EntityRow:
    """Copy a bible entity to the book project for overriding.

    Returns the new book entity.
    """
    new_entity = EntityRow(
        tag=bibleEntity.tag,
        handle=bibleEntity.handle,
        kind=bibleEntity.kind,
        displayName=bibleEntity.displayName,
        aliases=bibleEntity.aliases.copy(),
        attrs=bibleEntity.attrs.copy(),
    )
    # Remove bible origin marker
    new_entity.attrs.pop("_origin", None)
    # Mark as overridden from bible
    new_entity.attrs["_overridden_from_bible"] = "true"

    bookSheet.addEntity(new_entity)
    return new_entity
