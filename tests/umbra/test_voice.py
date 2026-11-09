"""
UmbraEdit - Tone, Narration Voice and Attribution Tests
========================================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import pytest

from umbraedit.umbra.sheet import EntityRow
from umbraedit.umbra.voice import (
    ATTR_DROP,
    ATTR_INHERIT,
    ATTR_KEEP,
    AttrSpan,
    UnitVoice,
    UtteranceSpan,
    effectiveDialogueTone,
    effectiveDrop,
    effectiveNarrationTone,
    effectiveUtteranceSpeaker,
    narrationSpeaker,
    parseAttrSpans,
    parseTone,
    parseUnitVoice,
    parseUttSpans,
    toneNeutral,
)
from umbraedit.umbra.voiceline import VoiceData


@pytest.mark.umbra
def test_voice_R1_parseTone_basic() -> None:
    """R1: parse a tone key with default intensity 2."""
    t = parseTone("happy")
    assert t is not None
    assert t.key == "happy"
    assert t.intensity == 2
    assert str(t) == "happy"


@pytest.mark.umbra
def test_voice_R1_parseTone_intensity() -> None:
    """R1: parse tone with intensity 1 and 3."""
    t = parseTone("excited:3")
    assert t is not None
    assert t.key == "excited"
    assert t.intensity == 3
    assert str(t) == "excited:3"

    t = parseTone("calm:1")
    assert t is not None
    assert t.intensity == 1
    assert str(t) == "calm:1"


@pytest.mark.umbra
def test_voice_R1_parseTone_invalid() -> None:
    """R1: invalid tone values return None."""
    assert parseTone("") is None
    assert parseTone("happy:0") is None
    assert parseTone("happy:4") is None
    assert parseTone("happy:x") is None
    assert parseTone("happy-3") is None


@pytest.mark.umbra
def test_voice_R3_effectiveDialogueTone() -> None:
    """R3: effective dialogue tone = unit.tone or neutral:2."""
    unit = UnitVoice(tone=parseTone("happy:3"))
    scene = UnitVoice(tone=parseTone("sad"))
    assert effectiveDialogueTone(unit, scene) == parseTone("happy:3")

    unit = UnitVoice()
    assert effectiveDialogueTone(unit, scene) == toneNeutral()


@pytest.mark.umbra
def test_voice_R3_effectiveNarrationTone() -> None:
    """R3: effective narration tone = unit.ntone or scene.ntone or neutral."""
    unit = UnitVoice(ntone=parseTone("calm"))
    scene = UnitVoice(ntone=parseTone("tense"))
    assert effectiveNarrationTone(unit, scene) == parseTone("calm")

    unit = UnitVoice()
    scene = UnitVoice(ntone=parseTone("tense"))
    assert effectiveNarrationTone(unit, scene) == parseTone("tense")

    unit = UnitVoice()
    scene = UnitVoice()
    assert effectiveNarrationTone(unit, scene) == toneNeutral()


@pytest.mark.umbra
def test_voice_R3_parseUnitVoice_scene() -> None:
    """R3: a scope=scene %Voice: line sets the scene narration tone."""
    text = "%Voice: scope=scene ntone=calm\n\nParagraph text."
    uv = parseUnitVoice(text)
    assert uv.sceneTone == parseTone("calm")
    assert uv.ntone == parseTone("calm")


@pytest.mark.umbra
def test_voice_R3_parseUnitVoice_paragraph() -> None:
    """R3: a paragraph %Voice: line sets paragraph tone and ntone."""
    text = "%Voice: spk=Bob tone=happy:3 ntone=tense\n\n“Hello,” he said."
    uv = parseUnitVoice(text)
    assert uv.tone == parseTone("happy:3")
    assert uv.ntone == parseTone("tense")
    assert uv.sceneTone is None


@pytest.mark.umbra
def test_voice_R3_narrationSpeaker_pov() -> None:
    """R3: narration speaker = @pov tag if set."""
    row = EntityRow(tag="Scene1", handle="h1", kind="character", attrs={"pov": "Ana"})
    index = _FakeIndex({"Scene1": row})
    assert narrationSpeaker("Scene1", index) == "Ana"


@pytest.mark.umbra
def test_voice_R3_narrationSpeaker_povWithDisplay() -> None:
    """R3: @pov display part after pipe is ignored."""
    row = EntityRow(tag="Scene1", handle="h1", kind="character", attrs={"pov": "Ana | Ana Soler"})
    index = _FakeIndex({"Scene1": row})
    assert narrationSpeaker("Scene1", index) == "Ana"


@pytest.mark.umbra
def test_voice_R3_narrationSpeaker_default() -> None:
    """R3: narration speaker defaults to narrator."""
    row = EntityRow(tag="Scene1", handle="h1", kind="character", attrs={})
    index = _FakeIndex({"Scene1": row})
    assert narrationSpeaker("Scene1", index) == "narrator"
    assert narrationSpeaker("Missing", index) == "narrator"
    assert narrationSpeaker("Scene1", None) == "narrator"


@pytest.mark.umbra
def test_voice_R6_effectiveDrop_spanDrop() -> None:
    """R6: span drop/keep decides immediately."""
    span = AttrSpan(0, 5, "said Bob", ATTR_DROP)
    assert effectiveDrop(span) is True
    span = AttrSpan(0, 5, "said Bob", ATTR_KEEP)
    assert effectiveDrop(span) is False


@pytest.mark.umbra
def test_voice_R6_effectiveDrop_inherit_speakerYes() -> None:
    """R6: inherit with speaker drop_attrib=yes drops."""
    span = AttrSpan(0, 5, "said Bob", ATTR_INHERIT)
    speaker = EntityRow(tag="Bob", handle="h1", kind="character", attrs={"drop_attrib": "yes"})
    assert effectiveDrop(span, speaker) is True


@pytest.mark.umbra
def test_voice_R6_effectiveDrop_inherit_speakerNo() -> None:
    """R6: inherit with speaker drop_attrib=no keeps."""
    span = AttrSpan(0, 5, "said Bob", ATTR_INHERIT)
    speaker = EntityRow(tag="Bob", handle="h1", kind="character", attrs={"drop_attrib": "no"})
    assert effectiveDrop(span, speaker) is False


@pytest.mark.umbra
def test_voice_R6_effectiveDrop_inherit_setting() -> None:
    """R6: inherit falls back to project setting audio.dropAttributions."""
    span = AttrSpan(0, 5, "said Bob", ATTR_INHERIT)
    speaker = EntityRow(tag="Bob", handle="h1", kind="character", attrs={})
    assert effectiveDrop(span, speaker) is False

    class Settings:
        def getBool(self, key: str, default: bool = False) -> bool:
            return True if key == "audio.dropAttributions" else default

    assert effectiveDrop(span, speaker, Settings()) is True


@pytest.mark.umbra
def test_voice_R8_parseUttSpans() -> None:
    """R8: parse [utt:spk=...;tone=...] spans."""
    text = "[utt:spk=Ana;tone=happy:2]Override.[/utt]"
    spans = parseUttSpans(text)
    assert len(spans) == 1
    assert spans[0].spk == "Ana"
    assert spans[0].tone == parseTone("happy:2")
    assert spans[0].inner == "Override."
    assert text[spans[0].start : spans[0].end] == "[utt:spk=Ana;tone=happy:2]Override.[/utt]"


@pytest.mark.umbra
def test_voice_R8_effectiveUtteranceSpeaker() -> None:
    """R8: utt span speaker wins over paragraph voice spk."""
    utt = UtteranceSpan(0, 10, "x", spk="Ana", tone=None)
    pv = VoiceData(spk="Bob")
    assert effectiveUtteranceSpeaker(pv, utt) == "Ana"

    utt = UtteranceSpan(0, 10, "x", spk=None, tone=None)
    assert effectiveUtteranceSpeaker(pv, utt) == "Bob"

    assert effectiveUtteranceSpeaker(None, None) is None


@pytest.mark.umbra
def test_voice_parseAttrSpans_basic() -> None:
    """ParseAttrSpans finds [attr], [attr:drop], [attr:keep], [attr:proposal]."""
    text = "[attr]said Bob.[/attr] [attr:drop]went away.[/attr]"
    spans = parseAttrSpans(text)
    assert len(spans) == 2
    assert spans[0].mode == ATTR_INHERIT
    assert spans[0].inner == "said Bob."
    assert spans[1].mode == ATTR_DROP
    assert spans[1].inner == "went away."


@pytest.mark.umbra
def test_voice_parseAttrSpans_unmatchedOpen() -> None:
    """Unmatched open tags are skipped."""
    text = "[attr]said Bob."
    assert parseAttrSpans(text) == []


@pytest.mark.umbra
def test_voice_parseAttrSpans_overlap_skipped() -> None:
    """Overlapping spans: simple FIFO matching."""
    text = "[attr]said Bob.[/attr] extra [attr:keep]kept.[/attr]"
    spans = parseAttrSpans(text)
    assert len(spans) == 2


class _FakeIndex:
    def __init__(self, entities: dict) -> None:
        self._entities = entities

    def getEntity(self, tag: str) -> EntityRow | None:
        return self._entities.get(tag)
