"""
UmbraEdit - Pronunciation Tests
================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from umbraedit.umbra.pronunciation import (
    STATUS_AS_WRITTEN,
    STATUS_CONFIRMED,
    STATUS_TODO,
    PronSpan,
    Pronunciations,
    entityHasPron,
    getPronunciation,
    parsePronNote,
    pronunciationSpans,
    runPronPreview,
    validateIpa,
)


@pytest.fixture
def pronProject(monkeypatch: pytest.MonkeyPatch, fncPath: Path, mockRnd, nwGUI):
    """A real test project with two entity notes, one with pron data."""
    from umbraedit.core.project import NWProject

    from tests.helpers import C, buildTestProject

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    cHandle = project.newFile("Katniss Everdeen", C.hCharRoot)
    assert isinstance(cHandle, str)
    aDoc = project.storage.getDocument(cHandle)
    aDoc.writeDocument(
        "# Katniss Everdeen\n\n"
        "@tag: Katniss | Katniss Everdeen\n"
        "@alias: Catnip\n"
        "@pron: en | KAT-niss ev-er-DEEN | /\u02c8k\u00e6tn\u026as \u02c8\u025bv\u025adi\u02d0n/\n"
        "@attr: kind | character\n"
        "@attr: pron_status | confirmed\n"
    )
    project.index.reIndexHandle(cHandle)

    wHandle = project.newFile("Hollow", C.hWorldRoot)
    assert isinstance(wHandle, str)
    aDoc = project.storage.getDocument(wHandle)
    aDoc.writeDocument("# The Hollow\n\n@tag: Hollow | The Hollow\n@attr: kind | place\n")
    project.index.reIndexHandle(wHandle)

    yield project


@pytest.mark.umbra
def test_pronunciation_R1_validateIpa_valid():
    """R1: valid IPA strings produce no errors."""
    assert validateIpa("") == []
    assert validateIpa("\u02c8k\u00e6tn\u026as") == []
    assert validateIpa("\u02c8\u025bv\u025adi\u02d0n") == []
    assert validateIpa("a\u02d0b\u0329") == []  # length mark, syllabic mark
    assert validateIpa("t\u0361s") == []  # tie bar
    assert validateIpa("a\u0303") == []  # combining diacritic
    assert validateIpa("\u03b8\u00f0\u014b") == []  # theta, eth, eng


@pytest.mark.umbra
def test_pronunciation_R1_validateIpa_unbalancedSlash():
    """R1/A4: an unbalanced slash is rejected, naming the position."""
    text = "\u02c8k\u00e6tn\u026as/"
    errors = validateIpa(text)
    assert len(errors) == 1
    assert "position" in errors[0]
    assert str(len(text) - 1) in errors[0]


@pytest.mark.umbra
def test_pronunciation_R1_validateIpa_unbalancedBracket():
    """R1: unbalanced square brackets are rejected with a position."""
    assert any("[" in err for err in validateIpa("[k\u00e6t"))
    assert any("]" in err for err in validateIpa("k\u00e6t]"))


@pytest.mark.umbra
def test_pronunciation_R1_validateIpa_invalidCharacter():
    """R1: characters outside the allowed set are named."""
    errors = validateIpa("k#t")
    assert len(errors) == 1
    assert "#" in errors[0]
    assert "U+0023" in errors[0]


@pytest.mark.umbra
def test_pronunciation_R1_getPronunciation_entity(pronProject):
    """R1: an @pron entry for the language is returned with source entity."""
    pron = getPronunciation(pronProject, "Katniss", "en")
    assert pron is not None
    assert pron.respelling == "KAT-niss ev-er-DEEN"
    assert pron.ipa == "\u02c8k\u00e6tn\u026as \u02c8\u025bv\u025adi\u02d0n"
    assert pron.status == STATUS_CONFIRMED
    assert pron.source == "entity"


@pytest.mark.umbra
def test_pronunciation_R1_getPronunciation_none(pronProject):
    """R1: no entry and no alias respelling gives None (status todo)."""
    assert getPronunciation(pronProject, "Hollow", "en") is None
    assert getPronunciation(pronProject, "Ghost", "en") is None


@pytest.mark.umbra
def test_pronunciation_R1_getPronunciation_aliasFallback(pronProject):
    """R1: an alias respelling is the fallback, with source alias."""
    from tests.helpers import C

    cHandle = pronProject.newFile("Bob Vega", C.hCharRoot)
    assert isinstance(cHandle, str)
    aDoc = pronProject.storage.getDocument(cHandle)
    aDoc.writeDocument("# Bob Vega\n\n@tag: Bob | Bob Vega\n@alias: Uncle Bob | UN-kul bob\n")
    pronProject.index.reIndexHandle(cHandle)

    pron = getPronunciation(pronProject, "Bob", "en")
    assert pron is not None
    assert pron.respelling == "UN-kul bob"
    assert pron.source == "alias"


@pytest.mark.umbra
def test_pronunciation_R1_getPronunciation_asWritten(pronProject):
    """R1: an asWritten entity yields an empty Pron with the status."""
    from tests.helpers import C

    cHandle = pronProject.newFile("Rue", C.hCharRoot)
    assert isinstance(cHandle, str)
    aDoc = pronProject.storage.getDocument(cHandle)
    aDoc.writeDocument("# Rue\n\n@tag: Rue\n@attr: pron_status | asWritten\n")
    pronProject.index.reIndexHandle(cHandle)

    pron = getPronunciation(pronProject, "Rue", "en")
    assert pron is not None
    assert pron.status == STATUS_AS_WRITTEN
    assert pron.respelling == ""
    assert pron.ipa == ""


@pytest.mark.umbra
def test_pronunciation_R1_setPronunciation_writesNote(pronProject):
    """R1: setPronunciation adds the @pron line and confirms status."""
    errors = Pronunciations(pronProject).setPronunciation("Hollow", "en", "HOL-oh")
    assert errors == []
    text = (pronProject.storage.contentPath / _handleOf(pronProject, "Hollow")).read_text(encoding="utf-8")
    assert "@pron: en | HOL-oh" in text
    assert "@attr: pron_status | confirmed" in text
    # The index sees the new entry immediately
    pron = getPronunciation(pronProject, "Hollow", "en")
    assert pron is not None
    assert pron.respelling == "HOL-oh"


def _handleOf(project, tag: str) -> str:
    """Return the note file name for a tag."""
    handle = project.index.entityHandle(tag)
    assert handle is not None
    return f"{handle}.md"


@pytest.mark.umbra
def test_pronunciation_R1_setPronunciation_replacesPerLang(pronProject):
    """R1: setting a language again replaces that entry, keeps others."""
    mgr = Pronunciations(pronProject)
    assert mgr.setPronunciation("Katniss", "es", "KAT-nis ev-er-DIN") == []
    assert mgr.setPronunciation("Katniss", "es", "KAT-nis") == []
    pronEs = mgr.getPronunciation("Katniss", "es")
    assert pronEs is not None and pronEs.respelling == "KAT-nis"
    pronEn = mgr.getPronunciation("Katniss", "en")
    assert pronEn is not None and pronEn.respelling == "KAT-niss ev-er-DEEN"
    text = (pronProject.storage.contentPath / _handleOf(pronProject, "Katniss")).read_text(encoding="utf-8")
    assert text.count("@pron:") == 2


@pytest.mark.umbra
def test_pronunciation_R1_setPronunciation_invalidIpaRejected(pronProject):
    """R1: an invalid IPA is rejected without writing."""
    mgr = Pronunciations(pronProject)
    before = (pronProject.storage.contentPath / _handleOf(pronProject, "Hollow")).read_text(encoding="utf-8")
    errors = mgr.setPronunciation("Hollow", "en", "HOL", "k\u00e6t/")
    assert errors
    after = (pronProject.storage.contentPath / _handleOf(pronProject, "Hollow")).read_text(encoding="utf-8")
    assert before == after


@pytest.mark.umbra
def test_pronunciation_R1_markAsWritten(pronProject):
    """R1: markAsWritten sets the pron_status attribute."""
    assert Pronunciations(pronProject).markAsWritten("Hollow") is True
    text = (pronProject.storage.contentPath / _handleOf(pronProject, "Hollow")).read_text(encoding="utf-8")
    assert "@attr: pron_status | asWritten" in text
    assert Pronunciations(pronProject).markAsWritten("Ghost") is False


@pytest.mark.umbra
def test_pronunciation_R2_pronClasses():
    """R2: the covered classes exclude PLOT and TIMELINE."""
    from umbraedit.umbra.pronunciation import PRON_CLASSES

    assert "CHARACTER" in PRON_CLASSES
    assert "WORLD" in PRON_CLASSES
    assert "OBJECT" in PRON_CLASSES
    assert "ENTITY" in PRON_CLASSES
    assert "PLOT" not in PRON_CLASSES
    assert "TIMELINE" not in PRON_CLASSES


@pytest.mark.umbra
def test_pronunciation_R5_runPronPreview():
    """R5: the preview command runs without a shell, placeholders filled."""
    ok, output = runPronPreview(["/bin/echo", "{text}|{ipa}"], "KAT-niss", "\u02c8k\u00e6t")
    assert ok
    assert "KAT-niss|\u02c8k\u00e6t" in output


@pytest.mark.umbra
def test_pronunciation_R5_runPronPreview_none():
    """R5: no command configured is a clean no."""
    ok, output = runPronPreview([], "KAT-niss", "")
    assert not ok
    assert "previewCommand" in output


@pytest.mark.umbra
def test_pronunciation_R5_runPronPreview_missingBinary():
    """R5: a missing binary is a clean error, not an exception."""
    ok, output = runPronPreview(["/no/such/binary_here"], "x", "")
    assert not ok
    assert "not found" in output


@pytest.mark.umbra
def test_pronunciation_R8_pronunciationSpans(pronProject):
    """R8: mentions of pronounced entities carry their pronunciation."""
    text = "Katniss Everdeen walked into the Hollow and saw Catnip."
    spans = pronunciationSpans(text, "en", pronProject)
    katniss = next(s for s in spans if text[s.start : s.end] == "Katniss Everdeen")
    assert katniss.tag == "Katniss"
    assert katniss.respelling == "KAT-niss ev-er-DEEN"
    assert katniss.ipa == "\u02c8k\u00e6tn\u026as \u02c8\u025bv\u025adi\u02d0n"
    # Hollow has no pronunciation yet: no span for it
    assert all(text[s.start : s.end] != "Hollow" for s in spans)


@pytest.mark.umbra
def test_pronunciation_R8_pronunciationSpans_alias(pronProject):
    """R8: an alias mention uses the alias respelling."""
    from tests.helpers import C

    cHandle = pronProject.newFile("Bob Vega", C.hCharRoot)
    assert isinstance(cHandle, str)
    aDoc = pronProject.storage.getDocument(cHandle)
    aDoc.writeDocument("# Bob Vega\n\n@tag: Bob | Bob Vega\n@alias: Uncle Bob | UN-kul bob\n")
    pronProject.index.reIndexHandle(cHandle)

    spans = pronunciationSpans("Uncle Bob waved.", "en", pronProject)
    assert len(spans) == 1
    assert spans[0].tag == "Bob"
    assert spans[0].respelling == "UN-kul bob"
    assert spans[0].ipa == ""


@pytest.mark.umbra
def test_pronunciation_parsePronNote_pronStatusValues():
    """ParsePronNote reads all three status values."""
    body = "# X\n\n@tag: X\n@attr: pron_status | asWritten\n"
    assert parsePronNote(body).status == STATUS_AS_WRITTEN
    body = "# X\n\n@tag: X\n@attr: pron_status | nonsense\n"
    assert parsePronNote(body).status == STATUS_TODO


@pytest.mark.umbra
def test_pronunciation_R1_entityHasPron(pronProject):
    """EntityHasPron checks the per-language entries."""
    row = pronProject.index.getEntity("Katniss")
    assert row is not None
    assert entityHasPron(row, "en") is True
    assert entityHasPron(row, "es") is False


@pytest.mark.umbra
def test_pronunciation_R1_pronSpanType():
    """PronSpan carries the fields used by the utterance index (P11)."""
    span = PronSpan(0, 5, "Katniss", "KAT-niss", "\u02c8k\u00e6t")
    assert (span.start, span.end, span.tag, span.respelling, span.ipa) == (
        0,
        5,
        "Katniss",
        "KAT-niss",
        "\u02c8k\u00e6t",
    )
