"""
UmbraEdit - Speaker Authoring Gate Rule Tests
==============================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from umbraedit.umbra.gates import OP_AUDIO_CHAPTER, OP_BUILD_RUN, GateScope, runGates


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
    def getItemData(self, tHandle: str):
        return None

    def iterEntities(self):
        return []


class _FakeProject:
    def __init__(self, root: Path, items: list) -> None:
        self.tree = _FakeTree(items)
        self.storage = _FakeStorage(root)
        self.index = _FakeIndex()


@pytest.fixture(autouse=True)
def _isolateGateRegistry():
    from umbraedit.umbra import gates as gatesMod

    saved = dict(gatesMod._gates)
    yield
    gatesMod._gates.clear()
    gatesMod._gates.update(saved)


def _sceneProject(tmp_path: Path, paragraphs: dict[str, str]) -> _FakeProject:
    """paragraphs: handle -> document body with dialogue paragraphs."""
    content = tmp_path / "content"
    items = []
    for handle, body in paragraphs.items():
        _writeDoc(content, handle, body)
        items.append(_FakeItem(handle, "NOVEL", handle))
    return _FakeProject(tmp_path, items)


@pytest.mark.umbra
def test_speakergates_R9_speakerUnassigned_noSpeaker(tmp_path: Path) -> None:
    """R9: a dialogue paragraph with no speaker blocks audio.chapter."""
    project = _sceneProject(
        tmp_path,
        {
            "h1": "# Scene\n\n\u201cHello,\u201d he said.\n",
        },
    )
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    assert report.blocked
    unassigned = [f for f in report.findings if f.ruleId == "speakerUnassigned"]
    assert len(unassigned) == 1


@pytest.mark.umbra
def test_speakergates_R9_speakerUnassigned_machine(tmp_path: Path) -> None:
    """R9: a machine-proposed speaker blocks audio.chapter."""
    project = _sceneProject(
        tmp_path,
        {
            "h1": "# Scene\n\n%Voice: spk=~guard src=machine\n\u201cHello,\u201d he said.\n",
        },
    )
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    assert report.blocked
    unassigned = [f for f in report.findings if f.ruleId == "speakerUnassigned"]
    assert len(unassigned) == 1
    assert unassigned[0].detail["spk"] == "~guard"


@pytest.mark.umbra
def test_speakergates_R9_speakerAssigned_clears(tmp_path: Path) -> None:
    """R9: an assigned speaker produces no speakerUnassigned finding."""
    project = _sceneProject(
        tmp_path,
        {
            "h1": "# Scene\n\n%Voice: spk=Bob\n\u201cHello,\u201d he said.\n",
        },
    )
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    assert not any(f.ruleId == "speakerUnassigned" for f in report.findings)


@pytest.mark.umbra
def test_speakergates_R9_noDialogue_skipped(tmp_path: Path) -> None:
    """R9: a paragraph without dialogue is not checked."""
    project = _sceneProject(
        tmp_path,
        {
            "h1": "# Scene\n\nJust narration.\n",
        },
    )
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    assert not report.blocked


@pytest.mark.umbra
def test_speakergates_R9_oneoffUnpromoted(tmp_path: Path) -> None:
    """R9: a one-off speaker with more than five dialogue paragraphs is
    advisory.
    """
    body = "\n".join(f"%Voice: spk=~guard\n\u201cLine {i},\u201d he said.\n" for i in range(6))
    project = _sceneProject(tmp_path, {"h1": body})
    report = runGates(
        OP_BUILD_RUN,
        GateScope(project=project, options={"lang": "en"}),
    )
    oneoff = [f for f in report.findings if f.ruleId == "oneoffUnpromoted"]
    assert len(oneoff) == 1
    assert oneoff[0].severity == "advisory"
    assert oneoff[0].detail["count"] == 6
    assert not report.blocked


@pytest.mark.umbra
def test_speakergates_R9_oneoffFiveOrFewer_ok(tmp_path: Path) -> None:
    """R9: five or fewer one-off paragraphs produce no finding."""
    body = "\n".join(f"%Voice: spk=~guard\n\u201cLine {i},\u201d he said.\n" for i in range(5))
    project = _sceneProject(tmp_path, {"h1": body})
    report = runGates(
        OP_BUILD_RUN,
        GateScope(project=project, options={"lang": "en"}),
    )
    assert not any(f.ruleId == "oneoffUnpromoted" for f in report.findings)


@pytest.mark.umbra
def test_speakergates_R9_emptyScope() -> None:
    """R9: an empty scope produces no findings."""
    report = runGates(OP_BUILD_RUN, GateScope(project=None))
    assert not report.blocked
    assert report.findings == []
