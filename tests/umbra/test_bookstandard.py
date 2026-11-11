"""
Tests for UmbraEdit Book Standard Gates (P30)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from umbraedit.enum import nwItemClass
from umbraedit.umbra.gates import OP_BUILD_RUN, OP_PUBLISH_PACKAGE, GateScope, runGates
from umbraedit.umbra.guide import GuideDoc, formatGuideDoc
from umbraedit.umbra.metadata import Metadata, saveMetadata


class _FakeItem:
    """Minimal stand-in for a ProjectItem."""

    def __init__(self, handle: str, class_name: str, name: str) -> None:
        self.itemHandle = handle
        self.itemName = name
        self.itemClass = nwItemClass[class_name]
        self.isFileType = lambda: True
        self.isDocumentLayout = lambda: True


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
        self.tree = type("FakeTree", (), {"__iter__": lambda self: iter(items)})()
        self.storage = type("FakeStorage", (), {"contentPath": root / "content", "storagePath": root})()
        self.docBuild = None


def _write_doc(content_path: Path, handle: str, body: str) -> None:
    content_path.mkdir(parents=True, exist_ok=True)
    (content_path / f"{handle}.md").write_text(f"+++\ntitle: T\n+++\n{body}", encoding="utf-8")


def _write_guide(content_path: Path, handle: str, kind: str, chapter: str = "", status: str = "draft", body: str = "") -> None:
    guide = GuideDoc(kind=kind, chapter=chapter, status=status, body=body)
    _write_doc(content_path, handle, formatGuideDoc(guide))


@pytest.fixture
def book_standard_project(tmp_path: Path):
    """Create a project with basic structure for Book Standard tests."""
    root = tmp_path / "project"
    content = root / "content"
    content.mkdir(parents=True)
    (root / "umbra").mkdir(parents=True)

    # Create metadata
    metadata = Metadata()
    metadata.book["title"] = "Test Book"
    metadata.book["author"] = "Test Author"
    metadata.book["language"] = "en"
    saveMetadata(root / "project", metadata)

    # Create chapters
    _write_doc(content, "ch1", "# Chapter 1\n\nContent here.")
    _write_doc(content, "ch2", "# Chapter 2\n\nMore content.")
    _write_doc(content, "ch3", "# Chapter 3\n\nEnd content.")

    # Create book entities
    import json
    (tmp_path / "project" / "umbra" / "sheet.json").write_text(json.dumps({
        "v": 1,
        "entities": [
            {"tag": "John", "handle": "char-john", "kind": "character", "aliases": [], "attrs": {"kind": "character", "slot": "1"}},
            {"tag": "Jane", "handle": "char-jane", "kind": "character", "aliases": [], "attrs": {"kind": "character", "slot": "2"}},
        ]
    }, separators=(",", ":")) + "\n", encoding="utf-8")

    # Create book entities (one shadows bible)
    _write_doc(content, "ch1", "# Chapter 1\n\nJohn said \"hello\" to Jane.")
    _write_doc(content, "ch2", "# Chapter 2\n\nJane replied.")
    _write_doc(content, "ch3", "# Chapter 3\n\nEnd.")

    # Create book sheet
    (tmp_path / "project" / "umbra" / "sheet.json").write_text(json.dumps({
        "v": 1,
        "entities": [
            {"tag": "John", "handle": "char-john", "kind": "character", "aliases": [], "attrs": {"kind": "character", "slot": "1"}},
        ]
    }, separators=(",", ":")) + "\n", encoding="utf-8")

    # Create series.json
    from umbraedit.umbra.edition import EditionInfo, EditionDoc, saveEdition
    edition_info = EditionInfo(
        v=1,
        editionId="en",
        language="en",
        source={"path": "..", "editionId": "main", "projectId": ""},
        docs={"ch1": EditionDoc(handle="ch1", baseTextHash="abc123", status="untranslated"),
              "ch2": EditionDoc(handle="ch2", baseTextHash="def456", status="untranslated"),
              "ch3": EditionDoc(handle="ch3", baseTextHash="ghi789", status="untranslated")},
        titleTemplate={"chapter": "Chapter {n}"},
        translatable=["book.title", "book.subtitle"],
        pending=["book.title", "book.subtitle"],
    )
    saveEdition(tmp_path / "project", edition_info)

    # Create fake projects
    class _FakeItem:
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
            self.tree = type("FakeTree", (), {"__iter__": lambda self: iter(items)})()
            self.storage = type("FakeStorage", (), {"contentPath": root / "content", "storagePath": root})()
            self.docBuild = None

    def _write_doc(content_path: Path, handle: str, body: str) -> None:
        content_path.mkdir(parents=True, exist_ok=True)
        (content_path / f"{handle}.md").write_text(f"+++\ntitle: T\n+++\n{body}", encoding="utf-8")

    def _write_guide(content_path: Path, handle: str, kind: str, chapter: str = "", status: str = "draft", body: str = "") -> None:
        guide = GuideDoc(kind=kind, chapter=chapter, status=status, body=body)
        _write_doc(content_path, handle, formatGuideDoc(guide))

    # Create items
    items = [
        _FakeItem("ch1", "NOVEL", "Chapter 1"),
        _FakeItem("ch2", "NOVEL", "Chapter 2"),
        _FakeItem("ch3", "NOVEL", "Chapter 3"),
    ]

    source_project = type("FakeProject", (), {
        "tree": type("FakeTree", (), {"__iter__": lambda self: iter([])})(),
        "storage": type("FakeStorage", (), {"contentPath": tmp_path / "project" / "content", "storagePath": tmp_path / "project"})(),
    })()

    book_project = type("FakeProject", (), {
        "tree": type("FakeTree", (), {"__iter__": lambda self: iter(items)})(),
        "storage": type("FakeStorage", (), {"contentPath": tmp_path / "project" / "content", "storagePath": tmp_path / "project"})(),
        "docBuild": type("DocBuild", (), {"getBool": lambda self, k: True, "_format": "PRINT_PDF"})()
    })()

    yield tmp_path / "project", source_project, book_project


class TestBookStandardGates:
    """Tests for Book Standard gate rules."""

    @pytest.mark.umbra
    def test_bs_straight_quotes_block(self, tmp_path: Path):
        """Straight quotes should trigger bsStraightQuotes gate."""
        from umbraedit.umbra.gates import OP_BUILD_RUN, GateScope, runGates
        from umbraedit.enum import nwItemClass

        class _FakeItem:
            def __init__(self, handle: str, class_name: str, name: str) -> None:
                self.itemHandle = handle
                self.itemName = name
                self.itemClass = nwItemClass[class_name]
                self.isFileType = lambda: True
                self.isDocumentLayout = lambda: True

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
                self.tree = type("FakeTree", (), {"__iter__": lambda self: iter(items)})()
                self.storage = type("FakeStorage", (), {"contentPath": root / "content", "storagePath": root})()
                self.docBuild = None

        class _FakeBuild:
            def __init__(self, format: str = "PRINT_PDF") -> None:
                self._format = format
                self._settings = {"epub.nestedToc": True}
            def getBool(self, key: str) -> bool:
                return self._settings.get(key, False)

        root = tmp_path / "project"
        content = root / "content"
        content.mkdir(parents=True)
        (root / "umbra").mkdir(parents=True)

        # Create metadata
        from umbraedit.umbra.metadata import Metadata, saveMetadata
        metadata = Metadata()
        metadata.book["title"] = "Test Book"
        metadata.book["author"] = "Test Author"
        metadata.book["language"] = "en"
        saveMetadata(root / "project", metadata)

        # Write chapter with straight quotes
        _write_doc(content, "ch4", '# Chapter 4\n\nHe said "hello" to her.')

        # Create items
        items = [_FakeItem("ch4", "NOVEL", "Chapter 4")]

        project = type("FakeProject", (), {
            "tree": type("FakeTree", (), {"__iter__": lambda self: iter(items)})(),
            "storage": type("FakeStorage", (), {"contentPath": root / "content", "storagePath": root})(),
            "docBuild": type("DocBuild", (), {"getBool": lambda self, k: True, "_format": "PRINT_PDF"})()
        })()

        # Create GateScope
        from umbraedit.umbra.gates import GateScope
        # Create test project with simple classes
        class TestItem:
            def __init__(self):
                self.itemHandle = "ch4"
                self.itemName = "Chapter 4"
                self.itemClass = type("Class", (), {"name": "NOVEL"})()
                self.index = None  # Add index attribute for gates

            def isFileType(self) -> bool:
                return True

            def isDocumentLayout(self) -> bool:
                return True

        class TestTree:
            def __iter__(self):
                return iter([TestItem()])

        class TestStorage:
            def __init__(self, root):
                self.contentPath = root / "content"
                self.storagePath = root

        class TestDocBuild:
            def getBool(self, key):
                return True
            _format = "PRINT_PDF"

        class TestProject:
            def __init__(self, root):
                self.tree = TestTree()
                self.storage = TestStorage(tmp_path / "project")
                self.docBuild = TestDocBuild()
                self.index = None  # Add index attribute for gates

        project = TestProject(tmp_path / "project")

        class TestSettings:
            def __init__(self, data: dict):
                self._data = data

            def getBool(self, key: str, default: bool = False) -> bool:
                return self._data.get(key, default)

        report = runGates(
            OP_BUILD_RUN,
            GateScope(project=project),
            settings=TestSettings({"format": "PRINT_PDF"}),
        )

        straight_quotes = [f for f in report.findings if f.ruleId == "bsStraightQuotes"]
        assert len(straight_quotes) > 0
        assert straight_quotes[0].severity == "block"


class TestBookStandardGateRegistration:
    """Test that Book Standard gates are registered."""

    @pytest.mark.umbra
    def test_bs_gates_registered(self):
        """All Book Standard gates should be registered."""
        from umbraedit.umbra.gates import _gates

        bs_gates = [
            "bsHeadingSkip",
            "bsDoubleSpace",
            "bsStraightQuotes",
            "bsMixedQuoteStyle",
            "bsDashUse",
            "bsEllipsisStyle",
            "bsEmptyChapter",
            "bsSceneBreakAtEdge",
            "bsFrontMatterOrder",
            "bsTocMissing",
            "bsOrphanFootnote",
        ]

        for gate_id in bs_gates:
            assert gate_id in _gates, f"Gate {gate_id} not registered"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])