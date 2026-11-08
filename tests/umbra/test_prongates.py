"""
UmbraEdit - Pronunciation Gate Rule Tests
==========================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from umbraedit.umbra.gates import OP_AUDIO_CHAPTER, OP_BUILD_RUN, GateScope, runGates


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

    def __getitem__(self, handle: str):
        return next((item for item in self._items if item.itemHandle == handle), None)


class _FakeIndex:
    def getItemData(self, tHandle: str):
        return None


class _FakeStorage:
    def __init__(self, root: Path) -> None:
        self.contentPath = root / "content"
        self.storagePath = root


class _FakeProject:
    def __init__(self, root: Path, items: list) -> None:
        self.tree = _FakeTree(items)
        self.storage = _FakeStorage(root)
        self.index = _FakeIndex()


@pytest.fixture(autouse=True)
def _isolateGateRegistry():
    """Snapshot the gate registry and restore it after each test."""
    from umbraedit.umbra import gates as gatesMod

    saved = dict(gatesMod._gates)
    yield
    gatesMod._gates.clear()
    gatesMod._gates.update(saved)


@pytest.fixture
def chapterProject(tmp_path: Path):
    """A project with two entities and one chapter mentioning both."""
    content = tmp_path / "content"
    _writeDoc(content, "hKat", "# Katniss Everdeen\n\n@tag: Katniss | Katniss Everdeen\n@attr: kind | character\n")
    _writeDoc(content, "hHollow", "# The Hollow\n\n@tag: Hollow | The Hollow\n@attr: kind | place\n")
    _writeDoc(content, "hCh1", "# Chapter 1\n\nKatniss walked into the Hollow and shivered.\n")
    return _FakeProject(
        tmp_path,
        [
            _FakeItem("hKat", "CHARACTER", "Katniss Everdeen"),
            _FakeItem("hHollow", "WORLD", "The Hollow"),
            _FakeItem("hCh1", "NOVEL", "Chapter 1"),
        ],
    )


@pytest.mark.umbra
def test_prongates_A1_blockedForBoth(chapterProject):
    """A1: both mentioned entities block the chapter when todo."""
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=chapterProject, handles=["hCh1"], options={"lang": "en"}),
    )
    missing = [f for f in report.findings if f.ruleId == "pronunciationMissing"]
    assert report.blocked
    assert {f.detail["tag"] for f in missing} == {"Katniss", "Hollow"}


@pytest.mark.umbra
def test_prongates_A1_clearedAfterFix(chapterProject, tmp_path: Path):
    """A1: after one pron and one asWritten the gate clears."""
    content = tmp_path / "content"
    _writeDoc(
        content,
        "hKat",
        "# Katniss Everdeen\n\n@tag: Katniss | Katniss Everdeen\n"
        "@pron: en | KAT-niss ev-er-DEEN\n"
        "@attr: kind | character\n@attr: pron_status | confirmed\n",
    )
    _writeDoc(
        content,
        "hHollow",
        "# The Hollow\n\n@tag: Hollow | The Hollow\n@attr: kind | place\n@attr: pron_status | asWritten\n",
    )
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=chapterProject, handles=["hCh1"], options={"lang": "en"}),
    )
    assert not any(f.ruleId == "pronunciationMissing" for f in report.findings)


@pytest.mark.umbra
def test_prongates_A5_languageMissing(chapterProject, tmp_path: Path):
    """A5: an Spanish edition names the entities lacking @pron: es."""
    content = tmp_path / "content"
    _writeDoc(
        content,
        "hKat",
        "# Katniss Everdeen\n\n@tag: Katniss | Katniss Everdeen\n"
        "@pron: en | KAT-niss ev-er-DEEN\n"
        "@attr: kind | character\n@attr: pron_status | confirmed\n",
    )
    _writeDoc(
        content,
        "hHollow",
        "# The Hollow\n\n@tag: Hollow | The Hollow\n"
        "@pron: en | HOL-oh\n"
        "@attr: kind | place\n@attr: pron_status | confirmed\n",
    )
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=chapterProject, handles=["hCh1"], options={"lang": "es"}),
    )
    langMissing = [f for f in report.findings if f.ruleId == "pronunciationLanguageMissing"]
    assert report.blocked
    assert {f.detail["tag"] for f in langMissing} == {"Katniss", "Hollow"}
    for finding in langMissing:
        assert finding.detail["lang"] == "es"
        assert "es" in finding.fix


@pytest.mark.umbra
def test_prongates_R9_languagePresent_clears(chapterProject, tmp_path: Path):
    """R9: with @pron: es entries the language gate is silent."""
    content = tmp_path / "content"
    _writeDoc(
        content,
        "hKat",
        "# Katniss Everdeen\n\n@tag: Katniss | Katniss Everdeen\n"
        "@pron: es | KAT-nis ev-er-DIN\n"
        "@attr: kind | character\n@attr: pron_status | confirmed\n",
    )
    _writeDoc(
        content,
        "hHollow",
        "# The Hollow\n\n@tag: Hollow | The Hollow\n"
        "@pron: es | HOL-oh\n"
        "@attr: kind | place\n@attr: pron_status | confirmed\n",
    )
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=chapterProject, handles=["hCh1"], options={"lang": "es"}),
    )
    assert not any(f.ruleId == "pronunciationLanguageMissing" for f in report.findings)
    assert not any(f.ruleId == "pronunciationMissing" for f in report.findings)


@pytest.mark.umbra
def test_prongates_R9_invalidIpa_blocksAudio(chapterProject, tmp_path: Path):
    """R9: invalid IPA blocks the audio chapter build."""
    content = tmp_path / "content"
    _writeDoc(
        content,
        "hKat",
        "# Katniss Everdeen\n\n@tag: Katniss | Katniss Everdeen\n"
        "@pron: en | KAT-niss | /\u02c8k\u00e6tn/\n"
        "@attr: kind | character\n@attr: pron_status | confirmed\n",
    )
    _writeDoc(
        content,
        "hHollow",
        "# The Hollow\n\n@tag: Hollow | The Hollow\n"
        "@pron: en | HOL-oh | /h\u0252l\n"
        "@attr: kind | place\n@attr: pron_status | confirmed\n",
    )
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=chapterProject, handles=["hCh1"], options={"lang": "en"}),
    )
    invalid = [f for f in report.findings if f.ruleId == "pronunciationInvalidIpa"]
    assert report.blocked
    assert len(invalid) == 1
    assert "Unbalanced '/'" in invalid[0].message
    assert invalid[0].detail["tag"] == "Hollow"


@pytest.mark.umbra
def test_prongates_R9_invalidIpa_buildRunOnlyForAudio(chapterProject, tmp_path: Path):
    """R9: on build.run the IPA check runs only for audio targets."""
    content = tmp_path / "content"
    _writeDoc(
        content,
        "hKat",
        "# K\n\n@tag: Katniss\n@pron: en | KAT | /\u02c8k\u00e6t\n"
        "@attr: kind | character\n@attr: pron_status | confirmed\n",
    )
    scope = GateScope(project=chapterProject, options={"lang": "en"})

    report = runGates(OP_BUILD_RUN, replaceScope(scope, {"audio": True}))
    assert any(f.ruleId == "pronunciationInvalidIpa" for f in report.findings)

    report = runGates(OP_BUILD_RUN, replaceScope(scope, {"audio": False}))
    assert not any(f.ruleId == "pronunciationInvalidIpa" for f in report.findings)


def replaceScope(scope: GateScope, options: dict) -> GateScope:
    """Return a copy of the scope with new options."""
    from dataclasses import replace

    return replace(scope, options=options)


@pytest.mark.umbra
def test_prongates_R9_nameUntracked_advisory(chapterProject):
    """R9: capitalised words without a sheet are an advisory finding."""
    content = chapterProject.storage.contentPath
    body = " ".join(["Katniss met Rillifane there."] * 4)
    _writeDoc(content, "hCh1", f"# Chapter 1\n\n{body}\n")
    report = runGates(
        OP_BUILD_RUN,
        GateScope(project=chapterProject, options={"lang": "en"}),
    )
    untracked = [f for f in report.findings if f.ruleId == "nameUntracked"]
    assert len(untracked) == 1
    assert untracked[0].severity == "advisory"
    assert untracked[0].detail["word"] == "Rillifane"
    assert not report.blocked


@pytest.mark.umbra
def test_prongates_R9_pronunciationStale(monkeypatch: pytest.MonkeyPatch, fncPath: Path, mockRnd, nwGUI):
    """R9: a changed display name after confirmation is flagged."""
    # A real project whose index holds the entity (staleEntities reads
    # it through project.index)
    from umbraedit.core.project import NWProject
    from umbraedit.umbra.pronunciation import Pronunciations

    from tests.helpers import C, buildTestProject

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)
    cHandle = project.newFile("Katniss Everdeen", C.hCharRoot)
    assert isinstance(cHandle, str)
    aDoc = project.storage.getDocument(cHandle)
    aDoc.writeDocument(
        "# Katniss Everdeen\n\n@tag: Katniss | Katniss Everdeen\n"
        "@pron: en | KAT-niss ev-er-DEEN\n"
        "@attr: kind | character\n@attr: pron_status | confirmed\n"
    )
    project.index.reIndexHandle(cHandle)

    mgr = Pronunciations(project)
    assert mgr.updatePronSeen() is True
    report = runGates(OP_AUDIO_CHAPTER, GateScope(project=project, options={"lang": "en"}))
    assert not any(f.ruleId == "pronunciationStale" for f in report.findings)

    # The author renames the display name externally
    aDoc.writeDocument(
        "# Katniss Everdeen II\n\n@tag: Katniss | Katniss Everdeen II\n"
        "@pron: en | KAT-niss ev-er-DEEN\n"
        "@attr: kind | character\n@attr: pron_status | confirmed\n"
    )
    project.index.reIndexHandle(cHandle)
    report = runGates(OP_AUDIO_CHAPTER, GateScope(project=project, options={"lang": "en"}))
    stale = [f for f in report.findings if f.ruleId == "pronunciationStale"]
    assert len(stale) == 1
    assert stale[0].severity == "advisory"


@pytest.mark.umbra
def test_prongates_R9_scopeOperationSet(chapterProject):
    """RunGates stamps the operation into the scope for the checks."""
    from umbraedit.umbra.gates import getGate

    rule = getGate("pronunciationMissing")
    assert rule is not None
    seen: list[str] = []

    def spy(scope) -> list:
        seen.append(scope.operation)
        return []

    from umbraedit.umbra.gates import Finding  # noqa: F401 — re-exported for readers

    rule2 = type(rule)(
        ruleId="spyRule",
        title="Spy",
        operations=frozenset({OP_BUILD_RUN}),
        defaultSeverity="advisory",
        relaxable=False,
        check=spy,
    )
    from umbraedit.umbra import gates as gatesMod

    gatesMod.registerGate(rule2)
    runGates(OP_BUILD_RUN, GateScope(project=chapterProject))
    assert seen == [OP_BUILD_RUN]


@pytest.mark.umbra
def test_prongates_R9_emptyScope(chapterProject):
    """R9: an empty scope produces no findings and no crash."""
    report = runGates(OP_AUDIO_CHAPTER, GateScope(project=None))
    assert not report.blocked
