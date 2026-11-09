"""
UmbraEdit - Attribution Gate Rule Tests
=========================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from umbraedit.umbra.entityindex import EntityRow
from umbraedit.umbra.gates import OP_AUDIO_CHAPTER, GateScope, runGates


def _writeDoc(contentPath: Path, handle: str, body: str) -> None:
    contentPath.mkdir(parents=True, exist_ok=True)
    (contentPath / f"{handle}.md").write_text(f"+++\ntitle: T\n+++\n{body}", encoding="utf-8")


class _FakeItem:
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
        self.contentPath = root / "content"
        self.storagePath = root


class _FakeIndex:
    def __init__(self, entities: dict) -> None:
        self._entities = entities

    def getEntity(self, tag: str) -> EntityRow | None:
        return self._entities.get(tag)

    def iterEntities(self) -> list[EntityRow]:
        return list(self._entities.values())


class _FakeProject:
    def __init__(self, root: Path, items: list, index: _FakeIndex) -> None:
        self.tree = _FakeTree(items)
        self.storage = _FakeStorage(root)
        self.index = index


@pytest.fixture(autouse=True)
def _isolateGateRegistry():
    from umbraedit.umbra import gates as gatesMod

    saved = dict(gatesMod._gates)
    yield
    gatesMod._gates.clear()
    gatesMod._gates.update(saved)


def _sceneProject(tmp_path: Path, entities: dict, docs: dict) -> _FakeProject:
    """entities: tag -> EntityRow. docs: handle -> body text."""
    content = tmp_path / "content"
    items = []
    for handle, body in docs.items():
        _writeDoc(content, handle, body)
        items.append(_FakeItem(handle, "NOVEL", handle))
    # Every document is also a scene entity (handle = document handle)
    # carrying its @pov attribution.
    for handle in docs:
        entities.setdefault(
            handle,
            EntityRow(
                tag=handle,
                handle=handle,
                kind="character",
                attrs={"pov": "Narrator"},
            ),
        )
    index = _FakeIndex(entities)
    return _FakeProject(tmp_path, items, index)


@pytest.mark.umbra
def test_voicegates_R9_attribDropSameVoice_blocks(tmp_path: Path) -> None:
    """R9: drop for a speaker whose voice_matrix equals the narration
    voice's voice_matrix blocks audio.chapter.
    """
    narrator = EntityRow(
        tag="Narrator",
        handle="hn",
        kind="character",
        attrs={"voice_matrix": "vm-aaaaaaaaaaaa", "drop_attrib": "yes"},
    )
    bob = EntityRow(
        tag="Bob",
        handle="hb",
        kind="character",
        attrs={"voice_matrix": "vm-aaaaaaaaaaaa"},
    )
    docs = {
        "h1": "# Scene\n\n@pov: Narrator\n“Hello,” [attr:drop]said Bob.[/attr]\n",
    }
    project = _sceneProject(tmp_path, {"Narrator": narrator, "Bob": bob}, docs)
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    assert report.blocked
    drops = [f for f in report.findings if f.ruleId == "attribDropSameVoice"]
    assert len(drops) == 1


@pytest.mark.umbra
def test_voicegates_R9_attribDropSameVoice_diffVoice_ok(tmp_path: Path) -> None:
    """R9: drop is fine when the voices differ."""
    narrator = EntityRow(
        tag="Narrator",
        handle="hn",
        kind="character",
        attrs={"voice_matrix": "vm-aaaaaaaaaaaa"},
    )
    bob = EntityRow(
        tag="Bob",
        handle="hb",
        kind="character",
        attrs={"voice_matrix": "vm-bbbbbbbbbbbb"},
    )
    docs = {
        "h1": "# Scene\n\n@pov: Narrator\n“Hello,” [attr:drop]said Bob.[/attr]\n",
    }
    project = _sceneProject(tmp_path, {"Narrator": narrator, "Bob": bob}, docs)
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    assert not any(f.ruleId == "attribDropSameVoice" for f in report.findings)


@pytest.mark.umbra
def test_voicegates_R9_attribDropSameVoice_keep_ok(tmp_path: Path) -> None:
    """R9: keep (not drop) never blocks."""
    narrator = EntityRow(
        tag="Narrator",
        handle="hn",
        kind="character",
        attrs={"voice_matrix": "vm-aaaaaaaaaaaa"},
    )
    bob = EntityRow(
        tag="Bob",
        handle="hb",
        kind="character",
        attrs={"voice_matrix": "vm-aaaaaaaaaaaa"},
    )
    docs = {
        "h1": "# Scene\n\n@pov: Narrator\n“Hello,” [attr:keep]said Bob.[/attr]\n",
    }
    project = _sceneProject(tmp_path, {"Narrator": narrator, "Bob": bob}, docs)
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    assert not any(f.ruleId == "attribDropSameVoice" for f in report.findings)


@pytest.mark.umbra
def test_voicegates_R9_attribProposalOpen(tmp_path: Path) -> None:
    """R9: an unaccepted [attr:proposal] span is advisory."""
    docs = {
        "h1": "# Scene\n\n“Hello,” [attr:proposal]said Bob.[/attr]\n",
    }
    project = _sceneProject(tmp_path, {}, docs)
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    proposals = [f for f in report.findings if f.ruleId == "attribProposalOpen"]
    assert len(proposals) == 1
    assert proposals[0].severity == "advisory"
    # No drop-same-voice finding (the proposal is not a drop)
    assert not any(f.ruleId == "attribDropSameVoice" for f in report.findings)


@pytest.mark.umbra
def test_voicegates_R9_emptyScope() -> None:
    """R9: an empty scope produces no findings."""
    report = runGates(OP_AUDIO_CHAPTER, GateScope(project=None))
    assert not report.blocked
    assert report.findings == []
