"""
UmbraEdit - Speaker Authoring Tests
====================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from umbraedit.umbra.dialogue import DialogueConfig, Span
from umbraedit.umbra.sheet import EntityRow
from umbraedit.umbra.speakers import (
    CHIP_ASSIGNED,
    CHIP_NEEDS_REVIEW,
    CHIP_NONE,
    CHIP_PROPOSED,
    CHIP_UNASSIGNED,
    addAliasesAutomatically,
    applySpeaker,
    chipForParagraph,
    enterProposal,
    loadReviewFlags,
    mergeParagraphs,
    proposeAlternation,
    resolvePick,
    saveReviewFlags,
    splitParagraph,
    tagColor,
    tagInitials,
    toggleReviewFlag,
    unattributedNames,
)
from umbraedit.umbra.voiceline import VoiceData


def _config() -> DialogueConfig:
    return DialogueConfig(quoteStyle=0)


def _entities() -> list[EntityRow]:
    return [
        EntityRow(
            tag="Bob",
            handle="h1",
            kind="character",
            displayName="Bob Vega",
            aliases=["Uncle Bob"],
            attrs={"fn": "Bob", "ln": "Vega"},
        ),
        EntityRow(
            tag="Ana",
            handle="h2",
            kind="character",
            displayName="Ana Soler",
            aliases=[],
            attrs={"fn": "Ana", "ln": "Soler"},
        ),
    ]


@pytest.mark.umbra
def test_speakers_R1_chip_assigned() -> None:
    """R1: an assigned speaker shows initials and a stable color."""
    chip = chipForParagraph(
        "%Voice: spk=Bob\nHello.",
        _entities(),
        lambda text: [],
        set(),
    )
    assert chip.kind == CHIP_ASSIGNED
    assert chip.tag == "Bob"
    assert chip.label == "BV"
    assert chip.color == tagColor("Bob")


@pytest.mark.umbra
def test_speakers_R1_chip_proposed() -> None:
    """R1: a machine proposal is a dashed proposed chip."""
    chip = chipForParagraph(
        "%Voice: spk=Bob src=machine\nHello.",
        _entities(),
        lambda text: [],
        set(),
    )
    assert chip.kind == CHIP_PROPOSED
    assert chip.dashed is True


@pytest.mark.umbra
def test_speakers_R1_chip_unassigned() -> None:
    """R1: a dialogue paragraph with no speaker is unassigned with '?'."""
    chip = chipForParagraph(
        "\u201cHello,\u201d he said.",
        _entities(),
        lambda text: [Span(0, 5, "dialogue")],
        set(),
    )
    assert chip.kind == CHIP_UNASSIGNED
    assert chip.label == "?"
    assert chip.color == "#c58a00"


@pytest.mark.umbra
def test_speakers_R1_chip_none() -> None:
    """R1: a paragraph with no dialogue span shows no chip."""
    chip = chipForParagraph(
        "Just narration.",
        _entities(),
        lambda text: [],
        set(),
    )
    assert chip.kind == CHIP_NONE


@pytest.mark.umbra
def test_speakers_R1_chip_needs_review() -> None:
    """R1: a flagged paragraph shows the needs-review chip."""
    chip = chipForParagraph(
        "%Voice: spk=Bob\nHello.",
        _entities(),
        lambda text: [],
        {("h1", 3)},
        handle="h1",
        lineNo=3,
    )
    assert chip.kind == CHIP_NEEDS_REVIEW


@pytest.mark.umbra
def test_speakers_R1_tagColor_stable() -> None:
    """R1: the tag color is stable across calls."""
    assert tagColor("Bob") == tagColor("Bob")
    assert tagColor("Bob") != tagColor("Ana")


@pytest.mark.umbra
def test_speakers_R1_tagInitials() -> None:
    """R1: initials come from the display name."""
    assert tagInitials("Bob", _entities()) == "BV"
    assert tagInitials("Ana", _entities()) == "AS"


@pytest.mark.umbra
def test_speakers_R2_applySpeaker_insert() -> None:
    """R2: assigning a speaker inserts a %Voice: line above the paragraph."""
    result = applySpeaker("Hello there.\n", "Bob", _entities())
    assert result.startswith("%Voice: spk=Bob\n")
    assert "Hello there." in result


@pytest.mark.umbra
def test_speakers_R2_applySpeaker_update() -> None:
    """R2: re-assigning updates the existing %Voice: line."""
    text = "%Voice: spk=Ana\nHello there.\n"
    result = applySpeaker(text, "Bob", _entities())
    assert "%Voice: spk=Bob" in result
    assert "%Voice: spk=Ana" not in result


@pytest.mark.umbra
def test_speakers_R2_applySpeaker_remove() -> None:
    """R2: a None tag removes the voice line."""
    text = "%Voice: spk=Bob\nHello there.\n"
    result = applySpeaker(text, None, _entities())
    assert "%Voice:" not in result
    assert "Hello there." in result


@pytest.mark.umbra
def test_speakers_R3_resolvePick_single() -> None:
    """R3: a known name matches exactly one entity."""
    matches, single = resolvePick("Bob", _entities())
    assert single is True
    assert len(matches) == 1
    assert matches[0].tag == "Bob"


@pytest.mark.umbra
def test_speakers_R3_resolvePick_alias() -> None:
    """R3: an alias matches its character."""
    matches, single = resolvePick("uncle bob", _entities())
    assert single is True
    assert matches[0].tag == "Bob"


@pytest.mark.umbra
def test_speakers_R3_resolvePick_ambiguous() -> None:
    """R3: two characters sharing a name return both matches."""
    entities = [*_entities(), EntityRow(tag="Bob2", handle="h3", kind="character", aliases=["Bob"], attrs={})]
    matches, single = resolvePick("Bob", entities)
    assert single is False
    assert {m.tag for m in matches} == {"Bob", "Bob2"}


@pytest.mark.umbra
def test_speakers_R3_resolvePick_unknown() -> None:
    """R3: an unknown name matches nothing."""
    matches, single = resolvePick("Nobody", _entities())
    assert matches == []
    assert single is False


@pytest.mark.umbra
def test_speakers_R4_enterProposal_alternation() -> None:
    """R4: alternating speakers A, B proposes A."""
    voices = [VoiceData(spk="Ana"), VoiceData(spk="Bob")]
    proposal = enterProposal(voices, False)
    assert proposal is not None
    assert proposal.tag == "Ana"
    assert proposal.reason == "alternation"


@pytest.mark.umbra
def test_speakers_R4_enterProposal_unclosedQuote() -> None:
    """R4: an unclosed quote proposes the same speaker."""
    voices = [VoiceData(spk="Bob")]
    proposal = enterProposal(voices, True)
    assert proposal is not None
    assert proposal.tag == "Bob"
    assert proposal.reason == "unclosed_quote"


@pytest.mark.umbra
def test_speakers_R4_enterProposal_none() -> None:
    """R4: no basis yields no proposal."""
    assert enterProposal([], False) is None
    assert enterProposal([VoiceData(spk="Bob")], False) is None


@pytest.mark.umbra
def test_speakers_R5_splitParagraph() -> None:
    """R5: the first part keeps the voice line; the second gets none."""
    text = "%Voice: spk=Bob\nLine one.\nLine two.\n"
    result = splitParagraph(text, 2)
    assert "%Voice: spk=Bob" in result.firstPart
    assert "%Voice:" not in result.secondPart
    assert "Line two." in result.secondPart


@pytest.mark.umbra
def test_speakers_R5_mergeParagraphs_kept() -> None:
    """R5: merging keeps the first voice line."""
    first = "%Voice: spk=Bob\nHello.\n"
    second = "Goodbye.\n"
    result = mergeParagraphs(first, second)
    assert "%Voice: spk=Bob" in result.merged
    assert result.dropped is None


@pytest.mark.umbra
def test_speakers_R5_mergeParagraphs_dropped() -> None:
    """R5: a different speaker/tone in the second part is reported."""
    first = "%Voice: spk=Bob tone=calm\nHello.\n"
    second = "%Voice: spk=Ana tone=excited:3\nGoodbye.\n"
    result = mergeParagraphs(first, second)
    assert result.dropped is not None
    assert "Ana" in result.dropped


@pytest.mark.umbra
def test_speakers_R7_reviewFlags_roundTrip(tmp_path: Path) -> None:
    """R7: review flags persist to review.json."""
    flags = {("h1", 3), ("h2", 7)}
    saveReviewFlags(tmp_path, flags)
    loaded = loadReviewFlags(tmp_path)
    assert loaded == flags


@pytest.mark.umbra
def test_speakers_R7_reviewFlags_toggle(tmp_path: Path) -> None:
    """R7: toggling a flag persists the change."""
    flags = toggleReviewFlag(tmp_path, "h1", 3)
    assert ("h1", 3) in flags
    flags = toggleReviewFlag(tmp_path, "h1", 3)
    assert ("h1", 3) not in flags


@pytest.mark.umbra
def test_speakers_R8_unattributedName() -> None:
    """R8: an attribution name matching no entity is flagged."""
    names = unattributedNames('[attr]said Marta.[/attr] "Hello," Bob said.', _entities())
    assert len(names) == 1
    assert names[0].name == "Marta"


@pytest.mark.umbra
def test_speakers_R8_attributedName_ok() -> None:
    """R8: a known name is not flagged."""
    names = unattributedNames("[attr]said Bob.[/attr]", _entities())
    assert names == []


@pytest.mark.umbra
def test_speakers_R10_settings_defaults() -> None:
    """R10: addAliasesAutomatically defaults false; proposeAlternation true."""
    assert addAliasesAutomatically(None) is False
    assert proposeAlternation(None) is True


@pytest.mark.umbra
def test_speakers_R10_settings_overridden() -> None:
    """R10: settings overrides are honored."""

    class Settings:
        def get(self, key: str, default: Any = None):
            return {"speakers.addAliasesAutomatically": True}.get(key, default)

    assert addAliasesAutomatically(Settings()) is True
    assert proposeAlternation(Settings()) is True
