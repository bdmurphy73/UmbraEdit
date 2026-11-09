"""
UmbraEdit - Utterance Derivation Tests
=======================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from umbraedit.umbra.sheet import EntityRow
from umbraedit.umbra.utterances import (
    UNKNOWN_SPEAKER,
    _restoreShortcodes,
    _splitParagraphIntoSegments,
    _stripShortcodes,
    _utteranceHash,
    deriveUtterances,
)


def _makeIndex(entities: dict[str, Any]) -> Any:
    class _Index:
        def __init__(self, ents: dict[str, Any]):
            self._ents = ents

        def getEntity(self, tag: str) -> EntityRow | None:
            return self._ents.get(tag)

        def iterEntities(self):
            return list(self._ents.values())

    return _Index(entities)


def _makeProject(root: Path, idx: Any) -> Any:
    class _Storage:
        def __init__(self, r: Path):
            self.storagePath = r
            self.contentPath = r / "content"

    class _Project:
        def __init__(self, r: Path, idx: Any):
            self.storage = _Storage(r)
            self.index = idx

    return _Project(root, idx)


@pytest.fixture
def utteranceProject(tmp_path: Path, mockRnd: Any, nwGUI: Any):
    """A project with one document containing the A1 example paragraph."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, tmp_path)
    return project


@pytest.mark.umbra
def test_utterances_R1_exampleParagraph(tmp_path: Path) -> None:
    """R1/A1: the example paragraph derives exactly three records and
    the join invariant holds.
    """
    index = _makeIndex({})
    bob = EntityRow(
        tag="Bob",
        handle="hb",
        kind="character",
        aliases=["Uncle Bob"],
        attrs={"fn": "Bob", "ln": "Vega", "voice_matrix": "vm-bbbbbbbbbbbb"},
    )
    index._ents["Bob"] = bob
    index._ents["hb"] = bob
    project = _makeProject(tmp_path, index)

    text = "“You’re late,” said Uncle Bob. “Get in.”"  # noqa: RUF001
    utts = deriveUtterances("h000000000000e", text, project, index=index)
    assert len(utts) == 3

    # Record 1: dialogue "You’re late,"  # noqa: RUF003
    assert utts[0].kind == "dialogue"
    assert utts[0].speaker == "Bob"
    assert utts[0].text == "“You’re late,”"  # noqa: RUF001
    assert utts[0].tone == "neutral"
    assert utts[0].toneI == 2
    assert utts[0].src == "author"

    # Record 2: narration "said Uncle Bob." attribution
    assert utts[1].kind == "narration"
    assert utts[1].speaker == "narrator"
    assert utts[1].text == "said Uncle Bob."
    assert utts[1].attribution is True
    assert utts[1].skip is None

    # Record 3: dialogue "Get in.”
    assert utts[2].kind == "dialogue"
    assert utts[2].speaker == "Bob"
    assert utts[2].text == "“Get in.”"

    # Join invariant: text + joinAfter rebuilds paragraph
    joined = ""
    for u in utts:
        joined += u.text + u.joinAfter
    assert joined == text


@pytest.mark.umbra
def test_utterances_R1_joinInvariantWithShortcodes(tmp_path: Path) -> None:
    """R1: the join invariant holds when shortcodes are present."""
    index = _makeIndex({})
    project = _makeProject(tmp_path, index)
    text = "[attr]said Bob.[/attr] “Hello.”"
    utts = deriveUtterances("h1", text, project, index=index)
    joined = "".join(u.text + u.joinAfter for u in utts)
    # Shortcodes removed
    assert "[attr]" not in joined
    assert "[/attr]" not in joined
    # The visible text is preserved
    assert "said Bob." in joined
    assert "“Hello.”" in joined


@pytest.mark.umbra
def test_utterances_R2_whitespaceFragmentNotUtterance(tmp_path: Path) -> None:
    """R2: whitespace-only fragments are not utterances."""
    index = _makeIndex({})
    project = _makeProject(tmp_path, index)
    text = "   \n\n  "
    utts = deriveUtterances("h1", text, project, index=index)
    assert utts == []


@pytest.mark.umbra
def test_utterances_R3_noSpeakerUnknown(tmp_path: Path) -> None:
    """R3: a dialogue span with no speaker gets speaker "unknown"."""
    index = _makeIndex({})
    project = _makeProject(tmp_path, index)
    text = "“Hello,” he said."
    utts = deriveUtterances("h1", text, project, index=index)
    dialogue = [u for u in utts if u.kind == "dialogue"]
    assert len(dialogue) == 1
    assert dialogue[0].speaker == UNKNOWN_SPEAKER


@pytest.mark.umbra
def test_utterances_R3_machineProposal(tmp_path: Path) -> None:
    """R3: a machine proposal gives src "machine"."""
    index = _makeIndex({})
    project = _makeProject(tmp_path, index)
    text = "%Voice: spk=~guard src=machine\n“Hello,” he said."
    utts = deriveUtterances("h1", text, project, index=index)
    dialogue = [u for u in utts if u.kind == "dialogue"]
    assert len(dialogue) == 1
    assert dialogue[0].src == "machine"


@pytest.mark.umbra
def test_utterances_R4_stableIds(tmp_path: Path) -> None:
    """R4: ids follow u-<handle>-<para>-<k> format."""
    index = _makeIndex({})
    project = _makeProject(tmp_path, index)
    text = "“Hello.” “Goodbye.”"
    utts = deriveUtterances("h000000000001", text, project, index=index)
    assert utts[0].id == "u-h000000000001-0000-0"
    assert utts[1].id == "u-h000000000001-0000-1"


@pytest.mark.umbra
def test_utterances_R6_voiceIdentity(tmp_path: Path) -> None:
    """R6: the voice matrix code is the voice; null when none."""
    index = _makeIndex({})
    project = _makeProject(tmp_path, index)
    text = "“Hello,” Bob said."
    utts = deriveUtterances("h1", text, project, index=index)
    dialogue = [u for u in utts if u.kind == "dialogue"]
    assert len(dialogue) == 1
    assert dialogue[0].voice is None  # Bob not in index, no matrix


@pytest.mark.umbra
def test_utterances_stripShortcodes() -> None:
    """Shortcodes are stripped and restored correctly."""
    clean, removed = _stripShortcodes("[attr]hello[/attr] world")
    assert clean == "\u0000STRIP0\u0000hello world"
    assert removed[0][1] == "[attr]hello[/attr]"
    restored = _restoreShortcodes(clean, removed)
    assert restored == "[attr]hello[/attr] world"


@pytest.mark.umbra
def test_utterances_splitSegments(tmp_path: Path) -> None:
    """Segment splitting isolates attributions within dialogue."""
    from umbraedit.umbra.dialogue import DialogueConfig, findDialogueSpans

    text = "“Hello,” said Bob."
    spans = findDialogueSpans(text, DialogueConfig())
    segments = _splitParagraphIntoSegments(text, spans)
    kinds = [s[2] for s in segments]
    assert "dialogue" in kinds
    assert "narration" in kinds


@pytest.mark.umbra
def test_utterances_hashDeterministic() -> None:
    """Utterance hashes are deterministic."""
    h1 = _utteranceHash("dialogue", "Bob", "Hello", "calm", 2, "en", None, [])
    h2 = _utteranceHash("dialogue", "Bob", "Hello", "calm", 2, "en", None, [])
    assert h1 == h2
    assert len(h1) == 64


@pytest.mark.umbra
def test_utterances_narrationSpeaker_pov(tmp_path: Path) -> None:
    """R3: narration speaker resolves @pov."""
    narrator = EntityRow(
        tag="Narrator",
        handle="hn",
        kind="character",
        attrs={"voice_matrix": "vm-nnnnnnnnnnnn"},
    )
    ana = EntityRow(
        tag="Ana",
        handle="ha",
        kind="character",
        attrs={"fn": "Ana", "voice_matrix": "vm-aaaaaaaaaaaa"},
    )
    scene = EntityRow(
        tag="hs",
        handle="hs",
        kind="character",
        attrs={"pov": "Ana"},
    )
    index = _makeIndex({"Narrator": narrator, "Ana": ana, "hs": scene})
    project = _makeProject(tmp_path, index)
    text = "“Hello,” Bob said."
    utts = deriveUtterances("hs", text, project, index=index)
    narration = [u for u in utts if u.kind == "narration"]
    assert len(narration) == 1
    assert narration[0].speaker == "Ana"
