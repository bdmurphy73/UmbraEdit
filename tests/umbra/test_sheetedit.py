"""
UmbraEdit - Sheet Note Editing Tests
=====================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import pytest

from umbraedit.umbra.sheetedit import (
    SheetEdit,
    applySheetEdit,
    keywordBlockRange,
    parseSheetNote,
)

NOTE = """# Bob Vega

@tag: Bob | Bob Vega
@alias: Uncle Bob
@attr: kind | character
@attr: slot | 1

Bob walked into the room.

“Hello,” he said.
"""


@pytest.mark.umbra
def test_sheetedit_R3_addAlias():
    """R3: adding an alias inserts one @alias line, rest unchanged."""
    edit = parseSheetNote(NOTE)
    edit.aliases.append("Robert")
    result = applySheetEdit(NOTE, edit)
    assert "@alias: Robert" in result
    assert "@alias: Uncle Bob" in result
    # Everything after the keyword block is byte-for-byte identical
    tail = "Bob walked into the room.\n\n“Hello,” he said.\n"
    assert result.endswith(tail)
    assert "# Bob Vega" in result
    assert result.count("@alias:") == 2


@pytest.mark.umbra
def test_sheetedit_R3_addAliasIdempotent():
    """R3: applying the same alias twice changes nothing (A1)."""
    edit = parseSheetNote(NOTE)
    once = applySheetEdit(NOTE, edit)
    twice = applySheetEdit(once, parseSheetNote(once))
    assert once == twice


@pytest.mark.umbra
def test_sheetedit_R3_setAttr_preservesTail():
    """R3: setting an attribute changes only the keyword block (A2)."""
    edit = parseSheetNote(NOTE)
    edit.attrs["x_birthplace"] = "Ohio"
    result = applySheetEdit(NOTE, edit)
    assert "@attr: x_birthplace | Ohio" in result
    before, _, _ = NOTE.partition("\n\n")
    rBefore, _, _ = result.partition("@alias")
    assert before in rBefore  # title line untouched


@pytest.mark.umbra
def test_sheetedit_R3_canonicalOrder():
    """R3: @attr lines are written in canonical column order."""
    edit = parseSheetNote(NOTE)
    edit.attrs = {"x_custom": "1", "voice": "Deep", "fn": "Robert", "slot": "1"}
    result = applySheetEdit(NOTE, edit)
    attrLines = [line for line in result.split("\n") if line.startswith("@attr")]
    keys = [line.split(":")[1].partition("|")[0].strip() for line in attrLines]
    # slot before fn (column order), x_custom after built-ins
    assert keys == ["slot", "fn", "voice", "x_custom"]


@pytest.mark.umbra
def test_sheetedit_R3_aliasWithPronunciation():
    """R3: a pronunciation round-trips through the pipe."""
    edit = parseSheetNote(NOTE)
    edit.aliases = ["Uncle Bob"]
    edit.pronunciations["Uncle Bob"] = "UN-kul bob"
    result = applySheetEdit(NOTE, edit)
    assert "@alias: Uncle Bob | UN-kul bob" in result
    again = parseSheetNote(result)
    assert again.pronunciations == {"Uncle Bob": "UN-kul bob"}


@pytest.mark.umbra
def test_sheetedit_R3_removeAlias():
    """R3: removing an alias drops the line."""
    edit = parseSheetNote(NOTE)
    edit.aliases = []
    result = applySheetEdit(NOTE, edit)
    assert "@alias:" not in result


@pytest.mark.umbra
def test_sheetedit_R3_noKeywordBlock():
    """R3: a note without a keyword block gets one after the title."""
    note = "# New Entity\n\nSome prose here.\n"
    edit = SheetEdit(aliases=["The Stranger"], attrs={"kind": "character"})
    result = applySheetEdit(note, edit)
    lines = result.split("\n")
    assert lines[0] == "# New Entity"
    assert lines[1] == "@alias: The Stranger"
    assert "@attr: kind | character" in lines
    assert "Some prose here." in result


@pytest.mark.umbra
def test_sheetedit_R3_emptyNote():
    """R3: an empty note gets a keyword block."""
    edit = SheetEdit(attrs={"kind": "place"})
    result = applySheetEdit("", edit)
    assert "@attr: kind | place" in result


@pytest.mark.umbra
def test_sheetedit_R3_preservesUpstreamKeywords():
    """R3: upstream keywords (@pov etc.) keep their order."""
    note = "# Scene\n\n@tag: Scene1\n@pov: Ana\n@char: Bob\n"
    edit = parseSheetNote(note)
    edit.aliases = ["Al"]
    result = applySheetEdit(note, edit)
    lines = [line for line in result.split("\n") if line.startswith("@")]
    assert lines == ["@tag: Scene1", "@pov: Ana", "@char: Bob", "@alias: Al"]


@pytest.mark.umbra
def test_sheetedit_R3_crlfPreserved():
    """R3: untouched CRLF lines keep their bytes; new lines use LF."""
    note = "# Bob\r\n\r\n@tag: Bob\r\n@alias: Uncle Bob\r\n\r\nProse.\r\n"
    edit = parseSheetNote(note)
    edit.aliases = ["Uncle Bob", "Bobby"]
    result = applySheetEdit(note, edit)
    # New keyword lines are written with LF (the fork's data rule)
    assert "@alias: Bobby\n" in result
    # Untouched lines keep their original CRLF bytes
    assert "Prose.\r\n" in result
    assert "# Bob\r\n" in result


@pytest.mark.umbra
def test_sheetedit_R3_keywordBlockRange():
    """R3: the keyword block is the first contiguous run of @ lines."""
    lines = ["# T", "", "@tag: X", "@alias: Y", "", "Prose"]
    assert keywordBlockRange(lines) == (2, 4)
    assert keywordBlockRange(["# T", "", "Prose"]) is None
    assert keywordBlockRange([]) is None


@pytest.mark.umbra
def test_sheetedit_R3_unicodeAttrs():
    """R3: unicode attribute values round-trip."""
    note = "# 老王\n\n@tag: Wang\n"
    edit = SheetEdit(attrs={"kind": "character", "nick": "老王"})
    result = applySheetEdit(note, edit)
    assert "@attr: nick | 老王" in result


@pytest.mark.umbra
def test_sheetedit_R3_largeNote():
    """R3: a large note is processed without corruption."""
    prose = " ".join(["word"] * 50_000)
    note = f"# Big\n\n@tag: Big\n\n{prose}\n"
    edit = parseSheetNote(note)
    edit.attrs["x_note"] = "value"
    result = applySheetEdit(note, edit)
    assert "@attr: x_note | value" in result
    assert prose in result
