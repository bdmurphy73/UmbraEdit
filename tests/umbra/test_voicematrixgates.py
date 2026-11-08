"""
UmbraEdit - Voice Matrix Gate Rule Tests
=========================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from umbraedit.umbra.entityindex import EntityRow
from umbraedit.umbra.gates import OP_AUDIO_CHAPTER, OP_SYNC_PUSH, GateScope, runGates
from umbraedit.umbra.voicematrix import buildVoiceMatrix


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
    """Simple in-memory index stub with entity rows."""

    def __init__(self) -> None:
        self._entities: dict[str, EntityRow] = {}

    def setEntity(self, tag: str, attrs: dict[str, str]) -> None:
        self._entities[tag] = EntityRow(tag=tag, handle=f"h{tag}", kind="character", attrs=dict(attrs))

    def getEntity(self, tag: str) -> EntityRow | None:
        return self._entities.get(tag)

    def iterEntities(self) -> list[EntityRow]:
        return sorted(self._entities.values(), key=lambda r: r.tag)


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


def _chapterProject(
    tmp_path: Path, voices: dict[str, str], prons: dict[str, str] | None = None
) -> tuple[_FakeProject, _FakeIndex]:
    """voices: tag -> voice_matrix code. prons: tag -> @pron respelling."""
    content = tmp_path / "content"
    index = _FakeIndex()
    prons = prons or {}
    for tag, code in voices.items():
        body = f"# {tag}\n\n@tag: {tag}\n@attr: kind | character\n"
        if tag in prons:
            body += f"@pron: en | {prons[tag]}\n@attr: pron_status | confirmed\n"
        if code:
            body += f"@attr: voice_matrix | {code}\n"
        _writeDoc(content, f"h{tag}", body)
        index.setEntity(
            tag, {"kind": "character", "voice_matrix": code, "pron_status": "confirmed" if tag in prons else ""}
        )
    _writeDoc(
        content, "hCh1", "# Chapter 1\n\n%Voice: spk=Bob\n“Hello,” Bob said.\n%Voice: spk=Ana\n“Hi,” Ana replied.\n"
    )
    project = _FakeProject(
        tmp_path,
        [
            _FakeItem("hBob", "CHARACTER", "Bob"),
            _FakeItem("hAna", "CHARACTER", "Ana"),
            _FakeItem("hCh1", "NOVEL", "Chapter 1"),
        ],
        index,
    )
    return project, index


@pytest.mark.umbra
def test_voicematrixgates_R8_voiceMatrixMissing(tmp_path: Path) -> None:
    """R8: a speaker with no voice_matrix code blocks the chapter."""
    project, _ = _chapterProject(tmp_path, {"Bob": "", "Ana": "vm-aaaaaaaaaaaa"})
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    missing = [f for f in report.findings if f.ruleId == "voiceMatrixMissing"]
    assert report.blocked
    assert {f.detail["tag"] for f in missing} == {"Bob"}


@pytest.mark.umbra
def test_voicematrixgates_R8_voiceMatrixUnknown(tmp_path: Path) -> None:
    """R8: a code not in the registry blocks the chapter."""
    project, _ = _chapterProject(tmp_path, {"Bob": "vm-000000000000", "Ana": ""})
    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    unknown = [f for f in report.findings if f.ruleId == "voiceMatrixUnknown"]
    assert report.blocked
    assert {f.detail["code"] for f in unknown} == {"vm-000000000000"}


@pytest.mark.umbra
def test_voicematrixgates_R8_voiceMatrixCorrupt(tmp_path: Path) -> None:
    """R8: a trailer hash mismatch blocks audio.chapter and sync.push."""
    from umbraedit.umbra.voicestore import VoiceStore

    project, index = _chapterProject(tmp_path, {"Bob": "", "Ana": ""})
    store = VoiceStore(project.storage.storagePath)
    data = buildVoiceMatrix("e", "m", "en", "l")
    code = store.importVoiceMatrix(data)
    index.setEntity("Bob", {"kind": "character", "voice_matrix": code})
    project.index.setEntity("Bob", {"kind": "character", "voice_matrix": code})
    # Flip a byte in the stored asset
    assetPath = store._assets.assetPath(store.getVoiceEntry(code).assetId)
    corrupted = bytearray(assetPath.read_bytes())
    corrupted[22] ^= 0xFF
    assetPath.write_bytes(corrupted)

    for op in (OP_AUDIO_CHAPTER, OP_SYNC_PUSH):
        report = runGates(op, GateScope(project=project, options={"lang": "en"}))
        corrupt = [f for f in report.findings if f.ruleId == "voiceMatrixCorrupt"]
        assert report.blocked
        assert len(corrupt) == 1


@pytest.mark.umbra
def test_voicematrixgates_R8_voiceMatrixLanguage(tmp_path: Path) -> None:
    """R8: a matrix that does not speak the edition language blocks."""
    from umbraedit.umbra.voicestore import VoiceStore

    project, index = _chapterProject(tmp_path, {"Bob": "", "Ana": ""})
    store = VoiceStore(project.storage.storagePath)
    data = buildVoiceMatrix("e", "m", "en", "l")
    code = store.importVoiceMatrix(data)
    index.setEntity("Bob", {"kind": "character", "voice_matrix": code})
    project.index.setEntity("Bob", {"kind": "character", "voice_matrix": code})

    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "zh"}),
    )
    lang = [f for f in report.findings if f.ruleId == "voiceMatrixLanguage"]
    assert report.blocked
    assert len(lang) == 1
    assert lang[0].detail["lang"] == "zh"


@pytest.mark.umbra
def test_voicematrixgates_R8_voiceMatrixRetired(tmp_path: Path) -> None:
    """R8: a retired code still in use is advisory, not blocking."""
    from umbraedit.umbra.voicestore import VoiceStore

    project, index = _chapterProject(tmp_path, {"Bob": "", "Ana": ""}, prons={"Bob": "BOB", "Ana": "ANA"})
    store = VoiceStore(project.storage.storagePath)
    data = buildVoiceMatrix("e", "m", "en", "l")
    code = store.importVoiceMatrix(data)
    # Both speakers use the same (soon-retired) matrix
    index.setEntity("Bob", {"kind": "character", "voice_matrix": code, "pron_status": "confirmed"})
    index.setEntity("Ana", {"kind": "character", "voice_matrix": code, "pron_status": "confirmed"})
    entry = store.getVoiceEntry(code)
    entry.retired = True
    store._saveRegistry()

    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    retired = [f for f in report.findings if f.ruleId == "voiceMatrixRetired"]
    assert len(retired) == 2
    assert all(f.severity == "advisory" for f in retired)
    assert not report.blocked


@pytest.mark.umbra
def test_voicematrixgates_R8_allVoicesPresentClears(tmp_path: Path) -> None:
    """R8: when every speaker has a valid matrix for the language, no
    voice matrix findings are raised.
    """
    from umbraedit.umbra.voicestore import VoiceStore

    project, index = _chapterProject(tmp_path, {"Bob": "", "Ana": ""}, prons={"Bob": "BOB", "Ana": "ANA"})
    store = VoiceStore(project.storage.storagePath)
    data = buildVoiceMatrix("e", "m", "en", "l")
    code = store.importVoiceMatrix(data)
    index.setEntity("Bob", {"kind": "character", "voice_matrix": code, "pron_status": "confirmed"})
    index.setEntity("Ana", {"kind": "character", "voice_matrix": code, "pron_status": "confirmed"})

    report = runGates(
        OP_AUDIO_CHAPTER,
        GateScope(project=project, options={"lang": "en"}),
    )
    vmFindings = [f for f in report.findings if f.ruleId.startswith("voiceMatrix")]
    assert vmFindings == []


@pytest.mark.umbra
def test_voicematrixgates_R8_emptyScope() -> None:
    """R8: an empty scope produces no findings."""
    report = runGates(OP_AUDIO_CHAPTER, GateScope(project=None))
    assert not report.blocked
    assert report.findings == []
