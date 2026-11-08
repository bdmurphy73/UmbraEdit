"""
UmbraEdit - Voice Matrix Store Tests
======================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from umbraedit.umbra.voicestore import VoiceEntry, VoiceStore

if TYPE_CHECKING:  # pragma: no cover
    from tests.helpers import MockRnd


def _makeStore(projectPath: Path) -> VoiceStore:
    return VoiceStore(projectPath)


@pytest.fixture
def voiceStore(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    mockRnd: MockRnd,
    nwGUI: object,
):
    """A VoiceStore over a real test project."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)
    return VoiceStore(project.storage.storagePath)


@pytest.mark.umbra
def test_voicestore_R2_importAndCode(voiceStore: VoiceStore) -> None:
    """R2: importing a matrix stores it and returns its code."""
    from umbraedit.umbra.voicematrix import buildVoiceMatrix

    data = buildVoiceMatrix(
        engine="xtts-v2",
        modelRef="bob",
        languages="en",
        label="Deep raspy",
        created="2026-11-06T21:02:11Z",
    )
    code = voiceStore.importVoiceMatrix(data)
    assert code.startswith("vm-")
    assert len(code) == 15
    entry = voiceStore.getVoiceEntry(code)
    assert entry is not None
    assert entry.label == "Deep raspy"
    assert entry.kind == "character"
    assert len(entry.assetId) == 8  # AssetStore content id (sha256[:8])
    # Round-trip: the stored asset parses back to the same code
    back = voiceStore.getVoiceMatrix(code)
    assert back == data


@pytest.mark.umbra
def test_voicestore_R2_dedup(voiceStore: VoiceStore) -> None:
    """R2: importing identical bytes returns the existing code."""
    from umbraedit.umbra.voicematrix import buildVoiceMatrix

    data = buildVoiceMatrix("e", "m", "en", "l")
    code1 = voiceStore.importVoiceMatrix(data)
    code2 = voiceStore.importVoiceMatrix(data)
    assert code1 == code2
    assert len(voiceStore.listVoices()) == 1


@pytest.mark.umbra
def test_voicestore_R2_immutableAsset(voiceStore: VoiceStore) -> None:
    """R2: imported assets are immutable."""
    from umbraedit.umbra.voicematrix import buildVoiceMatrix

    data = buildVoiceMatrix("e", "m", "en", "l")
    code = voiceStore.importVoiceMatrix(data)
    entry = voiceStore.getVoiceEntry(code)
    assert entry is not None
    asset = voiceStore._assets.getAsset(entry.assetId)
    assert asset["attrs"].get("immutable") is True


@pytest.mark.umbra
def test_voicestore_R2_getVoiceMatrix(voiceStore: VoiceStore) -> None:
    """R2: getVoiceMatrix returns the stored bytes."""
    from umbraedit.umbra.voicematrix import buildVoiceMatrix, parseVoiceMatrix

    data = buildVoiceMatrix("e", "m", "en", "l")
    code = voiceStore.importVoiceMatrix(data)
    back = voiceStore.getVoiceMatrix(code)
    assert back == data
    assert parseVoiceMatrix(back).code == code


@pytest.mark.umbra
def test_voicestore_R2_getVoiceMatrixUnknown() -> None:
    """R2: unknown code returns None."""
    store = VoiceStore(Path("/tmp/nonexistent-voice-store"))
    assert store.getVoiceMatrix("vm-000000000000") is None


@pytest.mark.umbra
def test_voicestore_R3_getVoice(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    mockRnd: MockRnd,
    nwGUI: object,
):
    """R3: getVoice resolves the entity's voice_matrix attribute."""
    from umbraedit.core.project import NWProject
    from umbraedit.umbra.sheetedit import applySheetEdit, parseSheetNote
    from umbraedit.umbra.voicematrix import buildVoiceMatrix

    from tests.helpers import C, buildTestProject

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)
    store = VoiceStore(project.storage.storagePath)

    cHandle = project.newFile("Bob Vega", C.hCharRoot)
    assert isinstance(cHandle, str)
    aDoc = project.storage.getDocument(cHandle)
    aDoc.writeDocument("# Bob Vega\n\n@tag: Bob | Bob Vega\n@attr: kind | character\n")
    project.index.reIndexHandle(cHandle)

    # No voice_matrix yet
    assert store.getVoice("Bob", "en", index=project.index) is None

    # Import a matrix and assign it to Bob
    data = buildVoiceMatrix("xtts-v2", "bob", "en", "Bob", created="2026-11-06T21:02:11Z")
    code = store.importVoiceMatrix(data)
    docFile = project.storage.contentPath / f"{cHandle}.md"
    text = docFile.read_text(encoding="utf-8")
    edit = parseSheetNote(text)
    edit.attrs["voice_matrix"] = code
    docFile.write_text(applySheetEdit(text, edit), encoding="utf-8", newline="\n")
    project.index.reIndexHandle(cHandle)

    voice = store.getVoice("Bob", "en", index=project.index)
    assert voice is not None
    assert voice.code == code
    assert voice.label == "Bob"


@pytest.mark.umbra
def test_voicestore_listVoices(voiceStore: VoiceStore) -> None:
    """ListVoices excludes retired voices by default."""
    from umbraedit.umbra.voicematrix import buildVoiceMatrix

    voiceStore.importVoiceMatrix(buildVoiceMatrix("e1", "m1", "en", "Voice One"))
    voiceStore.importVoiceMatrix(buildVoiceMatrix("e2", "m2", "en", "Voice Two"))
    voices = voiceStore.listVoices()
    assert len(voices) == 2
    assert all(not v.retired for v in voices)


@pytest.mark.umbra
def test_voicestore_entryDefaults() -> None:
    """VoiceEntry builds from a registry dict."""
    entry = VoiceEntry(
        code="vm-bf7bbe800d63",
        label="Deep raspy male",
        kind="character",
        engine="xtts-v2",
        languages=["en"],
        assetId="bf7bbe80",
        createdAt="2026-11-06T21:02:11Z",
        retired=False,
    )
    assert entry.code == "vm-bf7bbe800d63"
    assert entry.assetId == "bf7bbe80"
