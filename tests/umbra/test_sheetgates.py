"""
UmbraEdit - Sheet Gate Rule Tests
==================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from umbraedit.umbra.gates import (
    OP_AUDIO_CHAPTER,
    OP_BUILD_RUN,
    GateScope,
    registeredGates,
    runGates,
)

NOTE_HEADER = "%%%~orig%%%~\n\n"


def _writeDoc(contentPath: Path, handle: str, body: str) -> None:
    """Write a content file with the standard header separator."""
    contentPath.mkdir(parents=True, exist_ok=True)
    (contentPath / f"{handle}.md").write_text(f"+++\ntitle: T\n+++\n{body}", encoding="utf-8")


class _FakeItem:
    """Minimal stand-in for a ProjectItem."""

    def __init__(self, handle: str, className: str, name: str) -> None:
        from umbraedit.enum import nwItemClass

        self.itemHandle = handle
        self.itemName = name
        self.itemClass = nwItemClass[className]
        self.isFileType = lambda: True
        self.isDocumentLayout = lambda: False


class _FakeTree:
    def __init__(self, items: list) -> None:
        self._items = items

    def __iter__(self):
        return iter(self._items)


class _FakeStorage:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.contentPath = root / "content"
        self.storagePath = root


class _FakeProject:
    def __init__(self, root: Path, items: list) -> None:
        self.tree = _FakeTree(items)
        self.storage = _FakeStorage(root)
        self.index = _FakeIndex()


class _FakeIndex:
    """Minimal stand-in for NWIndex: no indexed items."""

    def getItemData(self, tHandle: str):
        return None


@pytest.fixture
def projRoot(tmp_path: Path) -> Path:
    """A fake project root with a content folder."""
    (tmp_path / "content").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture(autouse=True)
def _isolateGateRegistry():
    """Snapshot the gate registry and restore it after each test."""
    from umbraedit.umbra import gates as gatesMod

    saved = dict(gatesMod._gates)
    yield
    gatesMod._gates.clear()
    gatesMod._gates.update(saved)


@pytest.mark.umbra
def test_sheetgates_R8_rulesRegistered():
    """R8: the four sheet gate rules are registered on import."""
    ruleIds = {r.ruleId for r in registeredGates()}
    assert {"aliasCollision", "slotDuplicate", "toneNotInSet", "entityKindMissing"} <= ruleIds


@pytest.mark.umbra
def test_sheetgates_R8_aliasCollision(projRoot: Path):
    """R8/A3: two characters sharing an alias produce an advisory."""
    _writeDoc(projRoot / "content", "h1", "# Bob\n\n@tag: Bob\n@alias: Bobby\n@attr: kind | character\n")
    _writeDoc(projRoot / "content", "h2", "# Junior\n\n@tag: Junior\n@alias: Bobby\n@attr: kind | character\n")
    project = _FakeProject(
        projRoot,
        [
            _FakeItem("h1", "CHARACTER", "Bob"),
            _FakeItem("h2", "CHARACTER", "Junior"),
        ],
    )
    report = runGates(OP_BUILD_RUN, GateScope(project=project))
    collisions = [f for f in report.findings if f.ruleId == "aliasCollision"]
    assert len(collisions) == 1
    assert collisions[0].severity == "advisory"
    assert set(collisions[0].detail["tags"]) == {"Bob", "Junior"}
    assert not report.blocked


@pytest.mark.umbra
def test_sheetgates_R8_slotDuplicate_blocksBuild(projRoot: Path):
    """R8: duplicate slots block build.run."""
    _writeDoc(projRoot / "content", "h1", "# Bob\n\n@tag: Bob\n@attr: slot | 1\n@attr: kind | character\n")
    _writeDoc(projRoot / "content", "h2", "# Ana\n\n@tag: Ana\n@attr: slot | 1\n@attr: kind | character\n")
    project = _FakeProject(
        projRoot,
        [
            _FakeItem("h1", "CHARACTER", "Bob"),
            _FakeItem("h2", "CHARACTER", "Ana"),
        ],
    )
    report = runGates(OP_BUILD_RUN, GateScope(project=project))
    assert report.blocked
    dupes = [f for f in report.findings if f.ruleId == "slotDuplicate"]
    assert len(dupes) == 1
    assert dupes[0].severity == "block"
    assert dupes[0].detail["slot"] == 1


@pytest.mark.umbra
def test_sheetgates_R8_noDuplicateSlots_passes(projRoot: Path):
    """R8: unique slots produce no findings."""
    _writeDoc(projRoot / "content", "h1", "# Bob\n\n@tag: Bob\n@attr: slot | 1\n@attr: kind | character\n")
    _writeDoc(projRoot / "content", "h2", "# Ana\n\n@tag: Ana\n@attr: slot | 2\n@attr: kind | character\n")
    project = _FakeProject(
        projRoot,
        [
            _FakeItem("h1", "CHARACTER", "Bob"),
            _FakeItem("h2", "CHARACTER", "Ana"),
        ],
    )
    report = runGates(OP_BUILD_RUN, GateScope(project=project))
    assert not any(f.ruleId == "slotDuplicate" for f in report.findings)


@pytest.mark.umbra
def test_sheetgates_R8_toneNotInSet_blocksAudio(projRoot: Path):
    """R8/A6: an unknown tone in a %Voice: line blocks audio.chapter."""
    from umbraedit.umbra.sheet import SheetManager

    SheetManager(projRoot).loadTones()  # seed tones.json
    _writeDoc(projRoot / "content", "h1", "# Scene\n\n%Voice: spk=Bob tone=wistful\n“Hello,” he said.\n")
    project = _FakeProject(projRoot, [_FakeItem("h1", "NOVEL", "Scene")])
    report = runGates(OP_AUDIO_CHAPTER, GateScope(project=project))
    assert report.blocked
    tones = [f for f in report.findings if f.ruleId == "toneNotInSet"]
    assert len(tones) == 1
    assert tones[0].detail["tone"] == "wistful"
    # The annotation stays in the file
    text = (projRoot / "content" / "h1.md").read_text(encoding="utf-8")
    assert "tone=wistful" in text


@pytest.mark.umbra
def test_sheetgates_R8_knownTone_passes(projRoot: Path):
    """R8: a tone from the set passes the check."""
    from umbraedit.umbra.sheet import SheetManager

    SheetManager(projRoot).loadTones()  # seed tones.json
    _writeDoc(projRoot / "content", "h1", "# Scene\n\n%Voice: spk=Bob tone=happy:3\n“Hello,” he said.\n")
    project = _FakeProject(projRoot, [_FakeItem("h1", "NOVEL", "Scene")])
    report = runGates(OP_AUDIO_CHAPTER, GateScope(project=project))
    assert not any(f.ruleId == "toneNotInSet" for f in report.findings)


@pytest.mark.umbra
def test_sheetgates_R8_toneNotInSet_notOnBuild(projRoot: Path):
    """R8: toneNotInSet does not run on build.run (audio only)."""
    from umbraedit.umbra.sheet import SheetManager

    SheetManager(projRoot).loadTones()
    _writeDoc(projRoot / "content", "h1", "# Scene\n\n%Voice: spk=Bob tone=wistful\n“Hello,” he said.\n")
    project = _FakeProject(projRoot, [_FakeItem("h1", "NOVEL", "Scene")])
    report = runGates(OP_BUILD_RUN, GateScope(project=project))
    assert not any(f.ruleId == "toneNotInSet" for f in report.findings)


@pytest.mark.umbra
def test_sheetgates_R8_entityKindMissing(projRoot: Path):
    """R8: a place note without @attr: kind gets an advisory."""
    _writeDoc(projRoot / "content", "h1", "# Ohio\n\n@tag: Ohio\n")
    project = _FakeProject(projRoot, [_FakeItem("h1", "WORLD", "Ohio")])
    report = runGates(OP_BUILD_RUN, GateScope(project=project))
    missing = [f for f in report.findings if f.ruleId == "entityKindMissing"]
    assert len(missing) == 1
    assert missing[0].severity == "advisory"
    assert missing[0].detail["impliedKind"] == "place"
    assert "kind | place" in missing[0].fix


@pytest.mark.umbra
def test_sheetgates_R8_entityKindDeclared_passes(projRoot: Path):
    """R8: a note with @attr: kind produces no finding."""
    _writeDoc(projRoot / "content", "h1", "# Ohio\n\n@tag: Ohio\n@attr: kind | place\n")
    project = _FakeProject(projRoot, [_FakeItem("h1", "WORLD", "Ohio")])
    report = runGates(OP_BUILD_RUN, GateScope(project=project))
    assert not any(f.ruleId == "entityKindMissing" for f in report.findings)


@pytest.mark.umbra
def test_sheetgates_R8_handlesFilter(projRoot: Path):
    """R8: the scope handle filter limits which docs are checked."""
    _writeDoc(projRoot / "content", "h1", "# Bob\n\n@tag: Bob\n@attr: slot | 1\n@attr: kind | character\n")
    _writeDoc(projRoot / "content", "h2", "# Ana\n\n@tag: Ana\n@attr: slot | 1\n@attr: kind | character\n")
    project = _FakeProject(
        projRoot,
        [
            _FakeItem("h1", "CHARACTER", "Bob"),
            _FakeItem("h2", "CHARACTER", "Ana"),
        ],
    )
    report = runGates(OP_BUILD_RUN, GateScope(project=project, handles=["h1"]))
    assert not any(f.ruleId == "slotDuplicate" for f in report.findings)


@pytest.mark.umbra
def test_sheetgates_R8_emptyProject(projRoot: Path):
    """R8: no project or no docs yields no findings and no crash."""
    report = runGates(OP_BUILD_RUN, GateScope(project=None))
    assert not report.blocked
    project = _FakeProject(projRoot, [])
    report = runGates(OP_BUILD_RUN, GateScope(project=project))
    assert not report.blocked
