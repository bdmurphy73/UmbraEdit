"""UmbraEdit - Voice Line Parser Tests.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""

from __future__ import annotations

import pytest

from umbraedit.umbra.voiceline import VoiceData, formatVoiceLine, isVoiceLine, parseVoiceLine


@pytest.mark.umbra
def test_umbra_voiceline_R1_parseBasic():
    """R1: Parse a basic %Voice: line."""
    data = parseVoiceLine("%Voice: spk=Bob tone=excited:3")
    assert data is not None
    assert data.spk == "Bob"
    assert data.tone == "excited:3"


@pytest.mark.umbra
def test_umbra_voiceline_R1_notVoiceLine():
    """R1: Non-Voice lines return None."""
    assert parseVoiceLine("% some comment") is None
    assert parseVoiceLine("Regular text") is None
    assert parseVoiceLine("") is None
    assert parseVoiceLine("%Narration: test") is None


@pytest.mark.umbra
def test_umbra_voiceline_R1_isVoiceLine():
    """R1: isVoiceLine detects %Voice: lines."""
    assert isVoiceLine("%Voice: spk=Bob")
    assert isVoiceLine("%Voice:")
    assert not isVoiceLine("%Voice")
    assert not isVoiceLine("% Narration")


@pytest.mark.umbra
def test_umbra_voiceline_R1_allKeys():
    """R1: All keys are parsed correctly."""
    line = "%Voice: spk=Bob src=machine tone=calm ntone=neutral lang=en-GB scope=scene"
    data = parseVoiceLine(line)
    assert data.spk == "Bob"
    assert data.src == "machine"
    assert data.tone == "calm"
    assert data.ntone == "neutral"
    assert data.lang == "en-GB"
    assert data.scope == "scene"


@pytest.mark.umbra
def test_umbra_voiceline_R1_unknownKeys():
    """R1: Unknown keys are preserved in extra."""
    data = parseVoiceLine("%Voice: spk=Bob custom_key=value")
    assert data.spk == "Bob"
    assert data.extra == {"custom_key": "value"}


@pytest.mark.umbra
def test_umbra_voiceline_A1_roundTripCanonical():
    """A1: parse then format returns the same line for canonical input."""
    canonical = "%Voice: spk=Bob tone=excited:3"
    data = parseVoiceLine(canonical)
    result = formatVoiceLine(data)
    assert result == canonical


@pytest.mark.umbra
def test_umbra_voiceline_A1_roundTripAllKeys():
    """A1: Round trip with all keys."""
    canonical = "%Voice: spk=Ana src=machine tone=calm:2 ntone=neutral lang=en-GB scope=scene"
    data = parseVoiceLine(canonical)
    result = formatVoiceLine(data)
    assert result == canonical


@pytest.mark.umbra
def test_umbra_voiceline_A1_roundTrip200Lines():
    """A1: Round trip for 200 generated canonical lines."""
    speakers = ["Bob", "Ana", "Carlos", "narrator", "~one_off"]
    tones = ["calm", "excited:1", "happy:2", "sad:3", None]
    lines = []
    for i in range(200):
        spk = speakers[i % len(speakers)]
        tone = tones[i % len(tones)]
        parts = [f"spk={spk}"]
        if tone:
            parts.append(f"tone={tone}")
        lines.append(f"%Voice: {' '.join(parts)}")

    for line in lines:
        data = parseVoiceLine(line)
        result = formatVoiceLine(data)
        assert result == line, f"Round trip failed for: {line}"


@pytest.mark.umbra
def test_umbra_voiceline_R1_formatCanonicalOrder():
    """R1: Keys are written in canonical order regardless of parse order."""
    data = VoiceData(tone="calm", spk="Bob", lang="en")
    result = formatVoiceLine(data)
    # spk comes before tone, tone comes before lang
    assert result.index("spk=") < result.index("tone=") < result.index("lang=")


@pytest.mark.umbra
def test_umbra_voiceline_R1_nonCanonicalNormalised():
    """R1: Non-canonical input is normalised on format."""
    data = parseVoiceLine("%Voice: lang=en spk=Bob")
    result = formatVoiceLine(data)
    assert result == "%Voice: spk=Bob lang=en"


@pytest.mark.umbra
def test_umbra_voiceline_R1_emptyVoice():
    """R1: A bare %Voice: line parses with no fields set."""
    data = parseVoiceLine("%Voice:")
    assert data is not None
    assert data.spk is None
    result = formatVoiceLine(data)
    assert result == "%Voice:"


@pytest.mark.umbra
def test_umbra_voiceline_R1_narratorSpeaker():
    """R1: narrator as a speaker value."""
    data = parseVoiceLine("%Voice: spk=narrator")
    assert data.spk == "narrator"


@pytest.mark.umbra
def test_umbra_voiceline_R1_oneOffSpeaker():
    """R1: One-off speaker with ~label."""
    data = parseVoiceLine("%Voice: spk=~some_one_off")
    assert data.spk == "~some_one_off"
