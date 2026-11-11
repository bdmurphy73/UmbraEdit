"""
Tests for UmbraEdit Series Bible (P26)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from umbraedit.enum import nwItemClass
from umbraedit.umbra.series import (
    SeriesInfo,
    loadSeries,
    saveSeries,
    getBiblePath,
    loadBibleEntities,
    loadBibleSlots,
    getNextBibleSlot,
    checkTagShadow,
    copyEntityToBook,
    _loadBibleSeen,
    _saveBibleSeen,
    getBibleChangeCounter,
    checkBibleChanged,
    markBibleSeen,
    iterBibleEntities,
)
from umbraedit.umbra.sheet import SheetManager, EntityRow


def _makeManager(tmpPath: Path) -> SheetManager:
    """Create a SheetManager and populate it with test entities."""
    mgr = SheetManager(tmpPath)
    mgr._entityMap["Bob"] = EntityRow(
        tag="Bob",
        handle="h000000001",
        kind="character",
        aliases=["Uncle Bob", "Robert"],
        attrs={"slot": "1", "fn": "Robert", "ln": "Vega", "nick": "Bob", "kind": "character"},
    )
    mgr._entityMap["Ana"] = EntityRow(
        tag="Ana",
        handle="h000000002",
        kind="character",
        aliases=[],
        attrs={"slot": "2", "fn": "Ana", "ln": "Soler", "kind": "character"},
    )
    mgr._entityMap["Ohio"] = EntityRow(
        tag="Ohio",
        handle="h000000003",
        kind="place",
        aliases=["The Buckeye State"],
        attrs={"kind": "place", "description": "A midwestern state"},
    )
    return mgr


def _makeBibleManager(tmpPath: Path) -> SheetManager:
    """Create a SheetManager with bible entities."""
    mgr = SheetManager(tmpPath)
    mgr._entityMap["Katniss"] = EntityRow(
        tag="Katniss",
        handle="char-katniss",
        kind="character",
        aliases=[],
        attrs={"kind": "character", "slot": "1", "voice_matrix": "vm-abc123", "_origin": "bible"},
    )
    mgr._entityMap["Peeta"] = EntityRow(
        tag="Peeta",
        handle="char-peeta",
        kind="character",
        aliases=[],
        attrs={"kind": "character", "slot": "2", "_origin": "bible"},
    )
    mgr._entityMap["Arena"] = EntityRow(
        tag="Arena",
        handle="place-arena",
        kind="place",
        aliases=[],
        attrs={"kind": "place", "_origin": "bible"},
    )
    return mgr


class _FakeItem:
    """Minimal stand-in for a ProjectItem."""

    def __init__(self, handle: str, class_name: str, name: str) -> None:
        self.itemHandle = handle
        self.itemName = name
        self.itemClass = nwItemClass[class_name]
        self.isFileType = lambda: True
        self.isDocumentLayout = lambda: False


class _FakeTree:
    def __init__(self, items: list) -> None:
        self._items = items

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, handle: str):
        return next((item for item in self._items if item.itemHandle == handle), None)

    def checkExists(self, handle: str) -> bool:
        return any(item.itemHandle == handle for item in self._items)


class _FakeStorage:
    def __init__(self, root: Path) -> None:
        self.contentPath = root / "content"
        self.storagePath = root


class _FakeProject:
    def __init__(self, root: Path, items: list) -> None:
        self.tree = _FakeTree(items)
        self.storage = _FakeStorage(root)


def _write_doc(content_path: Path, handle: str, body: str) -> None:
    """Write a content file with the standard header separator."""
    content_path.mkdir(parents=True, exist_ok=True)
    (content_path / f"{handle}.md").write_text(f"+++\ntitle: T\n+++\n{body}", encoding="utf-8")


@pytest.fixture
def series_projects(tmp_path: Path):
    """Create a bible project and a book project with series.json."""
    bible_path = tmp_path / "salt-road-bible"
    book_path = tmp_path / "book1"

    # Create bible project
    bible_content = bible_path / "content"
    bible_content.mkdir(parents=True)
    (bible_path / "umbra").mkdir(parents=True)

    # Create book project
    book_content = book_path / "content"
    book_content.mkdir(parents=True)
    (book_path / "umbra").mkdir(parents=True)

    # Create bible entities
    _write_doc(bible_content, "char-katniss", "# Katniss Everdeen\n\n@tag: Katniss | Katniss Everdeen\n@attr: kind | character\n@attr: slot | 1\n@attr: voice_matrix | vm-abc123")
    _write_doc(bible_content, "char-peeta", "# Peeta Mellark\n\n@tag: Peeta | Peeta Mellark\n@attr: kind | character\n@attr: slot | 2")
    _write_doc(bible_content, "place-arena", "# The Arena\n\n@tag: Arena | The Arena\n@attr: kind | place")

    # Create bible voice store
    (bible_path / "umbra" / "voices.json").write_text(json.dumps({
        "v": 1,
        "voices": [{"code": "vm-abc123", "label": "Katniss Voice", "kind": "character", "engine": "piper", "languages": ["en"], "assetId": "abc123", "createdAt": "2026-01-01T00:00:00Z", "retired": False}]
    }, separators=(",", ":")) + "\n", encoding="utf-8")

    # Create bible tones
    (bible_path / "umbra" / "tones.json").write_text(json.dumps({
        "v": 1,
        "tones": [{"key": "neutral", "label": "Neutral", "appliesTo": "both", "audioHint": "", "order": 1}]
    }, separators=(",", ":")) + "\n", encoding="utf-8")

    # Create bible sheet
    (bible_path / "umbra" / "sheet.json").write_text(json.dumps({
        "v": 1,
        "entities": [
            {"tag": "Katniss", "handle": "char-katniss", "kind": "character", "aliases": [], "attrs": {"kind": "character", "slot": "1", "voice_matrix": "vm-abc123"}},
            {"tag": "Peeta", "handle": "char-peeta", "kind": "character", "aliases": [], "attrs": {"kind": "character", "slot": "2"}},
            {"tag": "Arena", "handle": "place-arena", "kind": "place", "aliases": [], "attrs": {"kind": "place"}},
        ]
    }, separators=(",", ":")) + "\n", encoding="utf-8")

    # Create bible journal for change counter
    (bible_path / "umbra" / "journal.jsonl").write_text(
        '{"v":1,"at":"2026-01-01T00:00:00Z","kind":"create","message":"Created Katniss"}\n'
        '{"v":1,"at":"2026-01-01T00:00:01Z","kind":"create","message":"Created Peeta"}\n'
        '{"v":1,"at":"2026-01-01T00:00:02Z","kind":"create","message":"Created Arena"}\n',
        encoding="utf-8"
    )

    # Create book entities (one shadows bible)
    _write_doc(book_content, "ch1", "# Chapter 1\n\nKatniss drew her bow.")
    _write_doc(book_content, "char-peeta", "# Peeta Mellark\n\n@tag: Peeta | Peeta Mellark\n@attr: kind | character\n@attr: slot | 2\n@attr: note | Book-specific note")

    # Create book sheet
    (book_path / "umbra" / "sheet.json").write_text(json.dumps({
        "v": 1,
        "entities": [
            {"tag": "Peeta", "handle": "char-peeta", "kind": "character", "aliases": [], "attrs": {"kind": "character", "slot": "2"}},
        ]
    }, separators=(",", ":")) + "\n", encoding="utf-8")

    # Create series.json in book
    series_info = SeriesInfo(
        v=1,
        series="Salt Road",
        bible="../salt-road-bible",
        bookNumber=1,
    )
    saveSeries(book_path, series_info)

    yield bible_path, book_path


class TestSeriesInfo:
    """Tests for SeriesInfo dataclass."""

    def test_series_info_creation(self):
        series = SeriesInfo(series="Test", bible="../bible", bookNumber=1)
        assert series.series == "Test"
        assert series.bible == "../bible"
        assert series.bookNumber == 1

    def test_series_info_to_dict(self):
        series = SeriesInfo(series="Test", bible="../bible", bookNumber=1)
        data = series.to_dict()
        assert data["series"] == "Test"
        assert data["bible"] == "../bible"
        assert data["bookNumber"] == 1

    def test_series_info_from_dict(self):
        data = {"v": 1, "series": "Test", "bible": "../bible", "bookNumber": 1}
        series = SeriesInfo.from_dict(data)
        assert series.series == "Test"
        assert series.bible == "../bible"
        assert series.bookNumber == 1

    def test_is_valid(self):
        assert SeriesInfo(series="Test", bible="../bible", bookNumber=1).is_valid()
        assert not SeriesInfo().is_valid()
        assert not SeriesInfo(series="Test").is_valid()
        assert not SeriesInfo(bible="../bible").is_valid()
        assert not SeriesInfo(bookNumber=1).is_valid()


class TestSeriesFile:
    """Tests for series.json file operations."""

    def test_load_series(self, series_projects):
        bible_path, book_path = series_projects
        series = loadSeries(book_path)
        assert series.series == "Salt Road"
        assert series.bible == "../salt-road-bible"
        assert series.bookNumber == 1

    def test_save_series(self, tmp_path: Path):
        book_path = tmp_path / "book"
        book_path.mkdir(parents=True)
        (book_path / "umbra").mkdir(parents=True)

        series = SeriesInfo(series="Test", bible="../bible", bookNumber=1)
        saveSeries(book_path, series)

        loaded = loadSeries(book_path)
        assert loaded.series == "Test"
        assert loaded.bible == "../bible"
        assert loaded.bookNumber == 1


class TestBiblePath:
    """Tests for bible path resolution."""

    def test_get_bible_path(self, series_projects):
        bible_path, book_path = series_projects
        series = loadSeries(book_path)
        resolved = getBiblePath(book_path, series)
        assert resolved == bible_path
        assert resolved.exists()

    def test_get_bible_path_missing(self, tmp_path: Path):
        book_path = tmp_path / "book"
        book_path.mkdir(parents=True)
        (book_path / "umbra").mkdir(parents=True)

        series = SeriesInfo(series="Test", bible="../missing", bookNumber=1)
        saveSeries(book_path, series)

        resolved = getBiblePath(book_path, series)
        assert not resolved.exists()


class TestBibleEntities:
    """Tests for loading bible entities."""

    def test_load_bible_entities(self, series_projects):
        bible_path, book_path = series_projects
        entities = loadBibleEntities(bible_path)
        assert len(entities) == 3
        tags = {e.tag for e in entities}
        assert "Katniss" in tags
        assert "Peeta" in tags
        assert "Arena" in tags

    def test_load_bible_slots(self, series_projects):
        bible_path, book_path = series_projects
        slots = loadBibleSlots(bible_path)
        assert slots == {1, 2}

    def test_load_bible_entities_marked_origin(self, series_projects):
        bible_path, book_path = series_projects
        entities = loadBibleEntities(bible_path)
        for entity in entities:
            assert entity.attrs.get("_origin") == "bible"


class TestNextBibleSlot:
    """Tests for slot allocation."""

    def test_next_bible_slot_first(self, series_projects):
        bible_path, book_path = series_projects
        book_sheet = _makeManager(book_path / "umbra")

        bible_slots = loadBibleSlots(bible_path)
        slot = getNextBibleSlot(book_sheet, bible_slots)
        # Bible has slots 1,2; book has slot 2 (Peeta); next bible slot is 3
        assert slot == 3

    def test_next_bible_slot_above_1000(self, series_projects):
        bible_path, book_path = series_projects
        book_sheet = _makeManager(book_path / "umbra")

        # Mock bible having all slots 1-1000
        bible_slots = set(range(1, 1001))
        slot = getNextBibleSlot(book_sheet, bible_slots)
        assert slot >= 1001


class TestTagShadow:
    """Tests for tag shadowing detection."""

    def test_check_tag_shadow_shadowed(self, series_projects):
        bible_path, book_path = series_projects
        book_project = _FakeProject(book_path, [
            _FakeItem("ch1", "NOVEL", "Chapter 1"),
            _FakeItem("char-peeta", "CHARACTER", "Peeta"),
        ])
        # Peeta is in both bible and book
        assert checkTagShadow(book_project, "Peeta")

    def test_check_tag_shadow_not_shadowed(self, series_projects):
        bible_path, book_path = series_projects
        book_project = _FakeProject(book_path, [
            _FakeItem("ch1", "NOVEL", "Chapter 1"),
            _FakeItem("char-peeta", "CHARACTER", "Peeta"),
        ])
        # Katniss is only in bible
        assert not checkTagShadow(book_project, "Katniss")

    def test_check_tag_shadow_no_series(self, series_projects):
        bible_path, book_path = series_projects
        book_project = _FakeProject(book_path, [
            _FakeItem("ch1", "NOVEL", "Chapter 1"),
        ])
        # Remove series.json
        (book_path / "umbra" / "series.json").unlink()
        assert not checkTagShadow(book_project, "Peeta")


class TestCopyEntityToBook:
    """Tests for copying bible entity to book."""

    def test_copy_entity_to_book(self, series_projects):
        bible_path, book_path = series_projects
        book_sheet = _makeManager(book_path / "umbra")

        bible_entities = loadBibleEntities(bible_path)
        katniss = next(e for e in bible_entities if e.tag == "Katniss")

        copied = copyEntityToBook(katniss, book_path, book_sheet)

        assert copied.tag == "Katniss"
        assert copied.attrs.get("_origin") is None
        assert copied.attrs.get("_overridden_from_bible") == "true"
        assert book_sheet.getEntity("Katniss") is copied


class TestBibleSeen:
    """Tests for bible change counter tracking."""

    def test_load_save_bible_seen(self, tmp_path: Path):
        path = tmp_path / "test"
        path.mkdir(parents=True)
        (path / "umbra").mkdir(parents=True)
        (path / "umbra" / "cache").mkdir(parents=True)

        _saveBibleSeen(path, 42)
        seen = _loadBibleSeen(path)
        assert seen["bibleChangeCounter"] == 42

    def test_get_bible_change_counter(self, series_projects):
        bible_path, book_path = series_projects
        counter = getBibleChangeCounter(bible_path)
        assert counter >= 3

    def test_check_bible_changed(self, series_projects):
        bible_path, book_path = series_projects
        changed, counter = checkBibleChanged(book_path, bible_path)
        assert isinstance(changed, bool)
        assert isinstance(counter, int)

    def test_mark_bible_seen(self, series_projects):
        bible_path, book_path = series_projects
        markBibleSeen(book_path, bible_path)
        seen = _loadBibleSeen(book_path)
        assert seen["bibleChangeCounter"] > 0


class TestIterBibleEntities:
    """Tests for iterating bible entities."""

    def test_iter_bible_entities(self, series_projects):
        bible_path, book_path = series_projects

        entities = list(iterBibleEntities(book_path))
        assert len(entities) == 3
        tags = {e.tag for e in entities}
        assert "Katniss" in tags
        assert "Peeta" in tags
        assert "Arena" in tags

    def test_iter_bible_entities_filter_kind(self, series_projects):
        bible_path, book_path = series_projects

        characters = list(iterBibleEntities(book_path, kind="character"))
        assert len(characters) == 2
        for e in characters:
            assert e.kind == "character"

    def test_iter_bible_entities_no_series(self, tmp_path: Path):
        book_path = tmp_path / "book"
        book_path.mkdir(parents=True)
        (book_path / "umbra").mkdir(parents=True)

        entities = list(iterBibleEntities(book_path))
        assert entities == []


class TestSheetBibleIntegration:
    """Tests for SheetManager bible integration."""

    def test_set_bible_entities(self, series_projects):
        bible_path, book_path = series_projects
        book_sheet = _makeManager(book_path / "umbra")

        bible_entities = loadBibleEntities(bible_path)
        bible_slots = loadBibleSlots(bible_path)

        book_sheet.setBibleEntities(bible_entities, bible_slots)

        # Bible entities should be accessible
        assert book_sheet.getEntity("Katniss") is not None
        assert book_sheet.getEntity("Peeta") is not None
        assert book_sheet.getEntity("Arena") is not None

        # Bible entities should be marked
        katniss = book_sheet.getEntity("Katniss")
        assert katniss.origin == "bible"

    def test_is_bible_entity(self, series_projects):
        bible_path, book_path = series_projects
        book_sheet = _makeManager(book_path / "umbra")

        bible_entities = loadBibleEntities(bible_path)
        bible_slots = loadBibleSlots(bible_path)

        book_sheet.setBibleEntities(bible_entities, bible_slots)

        assert book_sheet.isBibleEntity("Katniss")
        assert book_sheet.isBibleEntity("Peeta")

    def test_can_edit_entity(self, series_projects):
        bible_path, book_path = series_projects
        book_sheet = _makeManager(book_path / "umbra")

        bible_entities = loadBibleEntities(bible_path)
        bible_slots = loadBibleSlots(bible_path)

        book_sheet.setBibleEntities(bible_entities, bible_slots)

        assert not book_sheet.canEditEntity("Katniss")
        assert not book_sheet.canEditEntity("Peeta")

    def test_add_alias_bible_entity_blocked(self, series_projects):
        bible_path, book_path = series_projects
        book_sheet = _makeManager(book_path / "umbra")

        bible_entities = loadBibleEntities(bible_path)
        bible_slots = loadBibleSlots(bible_path)

        book_sheet.setBibleEntities(bible_entities, bible_slots)

        # Adding alias to bible entity should fail
        result = book_sheet.addAlias("Katniss", "NewAlias")
        assert not result

    def test_set_attr_bible_entity_blocked(self, series_projects):
        bible_path, book_path = series_projects
        book_sheet = _makeManager(book_path / "umbra")

        bible_entities = loadBibleEntities(bible_path)
        bible_slots = loadBibleSlots(bible_path)

        book_sheet.setBibleEntities(bible_entities, bible_slots)

        # Setting attr on bible entity should fail
        result = book_sheet.setAttr("Katniss", "note", "New note")
        assert not result

    def test_next_slot_with_bible(self, series_projects):
        bible_path, book_path = series_projects
        book_sheet = _makeManager(book_path / "umbra")

        bible_entities = loadBibleEntities(bible_path)
        bible_slots = loadBibleSlots(bible_path)

        book_sheet.setBibleEntities(bible_entities, bible_slots)

        # Bible has slots 1,2; book has slot 2; next should be 3
        slot = book_sheet.nextSlot()
        assert slot == 3

    def test_next_slot_all_bible_used(self, series_projects):
        bible_path, book_path = series_projects
        book_sheet = _makeManager(book_path / "umbra")

        # Mock bible having all slots 1-1000
        bible_slots = set(range(1, 1001))

        # Create entities with all slots
        for i in range(1, 1001):
            entity = EntityRow(tag=f"Char{i}", handle=f"char{i}", kind="character", attrs={"slot": str(i)})
            book_sheet._entityMap[entity.tag] = entity

        book_sheet.setBibleEntities([], bible_slots)

        slot = book_sheet.nextSlot()
        assert slot >= 1001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])