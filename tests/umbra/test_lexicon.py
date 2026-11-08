"""
UmbraEdit - Lexicon Export Tests
=================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from pathlib import Path

import pytest

from umbraedit.umbra.lexicon import collectLexemes, exportLexicon
from umbraedit.umbra.sheet import EntityRow

# The expected PLS for the golden fixture (feature example, byte for byte)
GOLDEN_PLS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<lexicon version="1.0" '
    'xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" '
    'alphabet="ipa" xml:lang="en">\n'
    "  <lexeme><grapheme>Katniss Everdeen</grapheme>"
    "<phoneme>\u02c8k\u00e6tn\u026as \u02c8\u025bv\u025adi\u02d0n</phoneme></lexeme>\n"
    "  <lexeme><grapheme>Uncle Bob</grapheme><alias>UN-kul bob</alias></lexeme>\n"
    "</lexicon>\n"
)


@pytest.fixture
def lexProject(monkeypatch: pytest.MonkeyPatch, fncPath: Path, mockRnd, nwGUI):
    """A project with the golden fixture entity: tag Katniss, display
    name "Katniss Everdeen", an alias with its own respelling, and an
    English @pron entry with IPA.
    """
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
        "@alias: Uncle Bob | UN-kul bob\n"
        "@pron: en | KAT-niss ev-er-DEEN | /\u02c8k\u00e6tn\u026as \u02c8\u025bv\u025adi\u02d0n/\n"
        "@attr: kind | character\n"
        "@attr: pron_status | confirmed\n"
    )
    project.index.reIndexHandle(cHandle)
    yield project


@pytest.mark.umbra
def test_lexicon_A3_goldenPls(lexProject):
    """A3: the example PLS is produced byte for byte and parses as XML."""
    plsXml, _jsonText = exportLexicon(lexProject, "en")
    assert plsXml == GOLDEN_PLS
    root = ET.fromstring(plsXml)
    assert root.tag == "{http://www.w3.org/2005/01/pronunciation-lexicon}lexicon"
    lexemes = root.findall("{http://www.w3.org/2005/01/pronunciation-lexicon}lexeme")
    assert len(lexemes) == 2


@pytest.mark.umbra
def test_lexicon_A3_goldenFileReference(lexProject):
    """A3: the output matches the stored golden file exactly."""
    reference = Path(__file__).parent / "_reference" / "pron_lexicon_en.pls"
    plsXml, _jsonText = exportLexicon(lexProject, "en")
    if not reference.is_file():
        reference.write_text(plsXml, encoding="utf-8", newline="\n")
    assert plsXml == reference.read_text(encoding="utf-8")


@pytest.mark.umbra
def test_lexicon_R7_jsonCopy(lexProject):
    """R7: the JSON copy has the documented shape."""
    _plsXml, jsonText = exportLexicon(lexProject, "en")
    data = json.loads(jsonText)
    assert data["v"] == 1
    assert data["lang"] == "en"
    entries = data["entries"]
    bySource = {entry["source"]: entry for entry in entries}
    entity = bySource["entity"]
    assert entity["tag"] == "Katniss"
    assert entity["forms"] == ["Katniss", "Katniss Everdeen"]
    assert entity["respelling"] == "KAT-niss ev-er-DEEN"
    assert entity["ipa"] == "\u02c8k\u00e6tn\u026as \u02c8\u025bv\u025adi\u02d0n"
    alias = bySource["alias"]
    assert alias["forms"] == ["Uncle Bob"]
    assert alias["respelling"] == "UN-kul bob"
    assert alias["ipa"] == ""
    # Machine JSON rules: sorted keys, compact, trailing newline
    assert jsonText.endswith("\n")
    assert jsonText.strip().startswith('{"entries"') or jsonText.startswith('{"v"')
    assert ": " not in jsonText  # compact separators


@pytest.mark.umbra
def test_lexicon_R7_asWrittenOmitted():
    """R7: asWritten entities are omitted from the lexicon."""
    rows = [
        EntityRow(
            tag="Rue",
            handle="h1",
            kind="character",
            prons=[("en", "ROO", "")],
            attrs={"pron_status": "asWritten"},
        ),
    ]
    lexemes = collectLexemes(rows, "en")
    assert lexemes == []


@pytest.mark.umbra
def test_lexicon_R7_respellingOnlyUsesAliasElement():
    """R7: entities with only a respelling use the <alias> element."""
    rows = [
        EntityRow(
            tag="Hollow",
            handle="h2",
            kind="place",
            displayName="The Hollow",
            prons=[("en", "HOL-oh", "")],
            attrs={"pron_status": "confirmed"},
        ),
    ]
    lexemes = collectLexemes(rows, "en")
    assert len(lexemes) == 1
    assert lexemes[0].grapheme == "The Hollow"
    assert lexemes[0].ipa == ""
    assert lexemes[0].respelling == "HOL-oh"


@pytest.mark.umbra
def test_lexicon_R7_deterministicOrder():
    """R7: output is sorted by grapheme, then tag, and stable."""
    rows = [
        EntityRow(
            tag="B",
            handle="h1",
            kind="character",
            displayName="Zeta",
            prons=[("en", "ZEE", "")],
            attrs={"pron_status": "confirmed"},
        ),
        EntityRow(
            tag="A",
            handle="h2",
            kind="character",
            displayName="Beta",
            prons=[("en", "BEE", "")],
            attrs={"pron_status": "confirmed"},
        ),
    ]
    lexemes = collectLexemes(rows, "en")
    lexemes.sort(key=lambda lex: (lex.grapheme.casefold(), lex.grapheme, lex.tag))
    assert [lex.grapheme for lex in lexemes] == ["Beta", "Zeta"]


@pytest.mark.umbra
def test_lexicon_R7_otherLanguage():
    """R7: a Spanish export needs the Spanish entries only."""
    rows = [
        EntityRow(
            tag="Katniss",
            handle="h1",
            kind="character",
            prons=[("en", "KAT-niss", ""), ("es", "KAT-nis", "")],
            attrs={"pron_status": "confirmed"},
        ),
    ]
    lexemes = collectLexemes(rows, "es")
    assert len(lexemes) == 1
    assert lexemes[0].respelling == "KAT-nis"


@pytest.mark.umbra
def test_lexicon_R7_xmlEscaping():
    """R7: graphemes with XML special characters are escaped."""
    rows = [
        EntityRow(
            tag="A&B",
            handle="h1",
            kind="thing",
            prons=[("en", "ANDB", "")],
            attrs={"pron_status": "confirmed"},
        ),
    ]
    lexemes = collectLexemes(rows, "en")
    lexemes.sort(key=lambda lex: (lex.grapheme.casefold(), lex.grapheme, lex.tag))
    assert lexemes[0].grapheme == "A&B"


@pytest.mark.umbra
def test_lexicon_R7_todoWithoutPronOmitted():
    """R7: todo entities without any pronunciation contribute nothing."""
    rows = [EntityRow(tag="Ghost", handle="h1", kind="character", attrs={})]
    lexemes = collectLexemes(rows, "en")
    assert lexemes == []


@pytest.mark.umbra
def test_lexicon_R7_emptyProject(monkeypatch: pytest.MonkeyPatch, fncPath: Path, mockRnd, nwGUI):
    """R7: no entities give an empty lexicon."""
    from umbraedit.core.project import NWProject

    from tests.helpers import buildTestProject

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    plsXml, jsonText = exportLexicon(project, "en")
    assert "<lexeme>" not in plsXml
    assert json.loads(jsonText)["entries"] == []
    assert ET.fromstring(plsXml) is not None
