"""UmbraEdit - Dialogue Span Tests.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""

from __future__ import annotations

import pytest

from umbraedit.umbra.dialogue import (
    QUOTE_CURLY,
    QUOTE_FRENCH,
    QUOTE_GERMAN,
    QUOTE_STRAIGHT,
    DialogueConfig,
    findDialogueSpans,
)


@pytest.mark.umbra
def test_umbra_dialogue_A4_curlyQuotes():
    """A4: Curly quote dialogue detection."""
    config = DialogueConfig(quoteStyle=QUOTE_CURLY)
    text = "\u201cYou\u2019re late,\u201d said Bob. \u201cGet in.\u201d"
    spans = findDialogueSpans(text, config)
    kinds = [s.kind for s in spans]
    assert kinds == ["dialogue", "narration", "dialogue"]


@pytest.mark.umbra
def test_umbra_dialogue_A4_straightQuotes():
    """A4: Straight quote dialogue detection."""
    config = DialogueConfig(quoteStyle=QUOTE_STRAIGHT)
    text = '"You\'re late," said Bob. "Get in."'
    spans = findDialogueSpans(text, config)
    kinds = [s.kind for s in spans]
    assert kinds == ["dialogue", "narration", "dialogue"]


@pytest.mark.umbra
def test_umbra_dialogue_A4_germanQuotes():
    """A4: German quote style (low open, high close)."""
    config = DialogueConfig(quoteStyle=QUOTE_GERMAN)
    text = "\u201eDu bist sp\u00e4t\u201c sagte Bob. \u201cKomm rein.\u201c"
    spans = findDialogueSpans(text, config)
    kinds = [s.kind for s in spans]
    assert "dialogue" in kinds


@pytest.mark.umbra
def test_umbra_dialogue_A4_frenchQuotes():
    """A4: French quote style (guillemets)."""
    config = DialogueConfig(quoteStyle=QUOTE_FRENCH)
    text = "\u00abTu es en retard\u00bb dit Bob. \u00abEntre.\u00bb"
    spans = findDialogueSpans(text, config)
    kinds = [s.kind for s in spans]
    assert "dialogue" in kinds


@pytest.mark.umbra
def test_umbra_dialogue_A4_dashStyle():
    """A4: Dash-style dialogue detection."""
    config = DialogueConfig(quoteStyle=QUOTE_CURLY, dashStyle=True)
    text = "\u2014 Hello there.\n\u2014 Good morning."
    spans = findDialogueSpans(text, config)
    kinds = [s.kind for s in spans]
    assert "dialogue" in kinds


@pytest.mark.umbra
def test_umbra_dialogue_A4_unclosedQuote():
    """A4: An unclosed quote extends to end of paragraph."""
    config = DialogueConfig(quoteStyle=QUOTE_CURLY, allowOpenEnd=True)
    text = "\u201cThis dialogue never ends"
    spans = findDialogueSpans(text, config)
    assert len(spans) == 1
    assert spans[0].kind == "dialogue"
    assert spans[0].end == len(text)


@pytest.mark.umbra
def test_umbra_dialogue_A4_unclosedQuoteNoAllowEnd():
    """A4: An unclosed quote with allowOpenEnd=False is narration."""
    config = DialogueConfig(quoteStyle=QUOTE_CURLY, allowOpenEnd=False)
    text = "\u201cThis never ends"
    spans = findDialogueSpans(text, config)
    assert len(spans) == 1
    assert spans[0].kind == "narration"


@pytest.mark.umbra
def test_umbra_dialogue_A4_narrationOnly():
    """A4: A paragraph with no dialogue is all narration."""
    config = DialogueConfig(quoteStyle=QUOTE_CURLY)
    text = "This is plain narration with no dialogue."
    spans = findDialogueSpans(text, config)
    assert len(spans) == 1
    assert spans[0].kind == "narration"


@pytest.mark.umbra
def test_umbra_dialogue_A4_emptyParagraph():
    """A4: An empty paragraph returns no spans."""
    config = DialogueConfig(quoteStyle=QUOTE_CURLY)
    spans = findDialogueSpans("", config)
    assert spans == []
