"""
UmbraEdit - Merge Tests
=======================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from umbraedit.umbra.merge import (
    Change,
    MergeResult,
    Unit,
    align_units,
    apply_choices,
    merge_units,
    word_diff,
)
from umbraedit.umbra.units import UnitKind


def _unit(kind: UnitKind, text: str, start_line: int = 1) -> Unit:
    return Unit(kind=kind, lines=[text], startLine=start_line)


def _text_unit(text: str, start_line: int = 1) -> Unit:
    return _unit(UnitKind.PARAGRAPH, text, start_line)


def test_merge_units_identical() -> None:
    base = ours = theirs = "Hello world."
    result = merge_units(base, ours, theirs)
    assert len(result.conflicts) == 0
    assert len(result.merged) == 0
    assert len(result.units) == 1


def test_merge_units_ours_only_change() -> None:
    base = "Hello world."
    ours = "Hello world!"
    theirs = "Hello world."
    result = merge_units(base, ours, theirs)
    assert len(result.conflicts) == 0
    assert len(result.units) == 1
    assert result.units[0].lines[0] == "Hello world!"


def test_merge_units_theirs_only_change() -> None:
    base = "Hello world."
    ours = "Hello world."
    theirs = "Hello world!"
    result = merge_units(base, ours, theirs)
    assert len(result.conflicts) == 0
    assert len(result.units) == 1
    assert result.units[0].lines[0] == "Hello world!"


def test_merge_units_both_change_same() -> None:
    base = "Hello world."
    ours = theirs = "Hello world!"
    result = merge_units(base, ours, theirs)
    assert len(result.conflicts) == 0
    assert result.units[0].lines[0] == "Hello world!"


def test_merge_units_both_change_differently() -> None:
    base = "Hello world."
    ours = "Hello world!"
    theirs = "Hello universe."
    result = merge_units(base, ours, theirs)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].kind == "text"
    assert result.conflicts[0].base is not None
    assert result.conflicts[0].ours is not None
    assert result.conflicts[0].theirs is not None


def test_align_units_empty() -> None:
    assert align_units([], []) == []


def test_align_units_identical() -> None:
    u1 = _text_unit("Hello")
    u2 = _text_unit("World")
    matches = align_units([u1, u2], [u1, u2])
    assert len(matches) == 2
    assert matches[0][0] is u1
    assert matches[0][1] is u1
    assert matches[1][0] is u2
    assert matches[1][1] is u2


def test_align_units_insertion() -> None:
    u1 = _text_unit("First")
    u2 = _text_unit("Third")
    matches = align_units([u1, u2], [u1, _text_unit("Second"), u2])
    assert len(matches) == 3
    assert matches[0][0] is u1
    assert matches[0][1] is u1
    assert matches[1][0] is None
    assert matches[1][1] is not None
    assert matches[1][1].lines[0] == "Second"
    assert matches[2][0] is u2
    assert matches[2][1] is u2


def test_align_units_deletion() -> None:
    u1 = _text_unit("First")
    u2 = _text_unit("Third")
    matches = align_units([u1, _text_unit("Second"), u2], [u1, u2])
    assert len(matches) == 3
    assert matches[0][0] is u1
    assert matches[0][1] is u1
    assert matches[1][0] is not None
    assert matches[1][1] is None
    assert matches[1][0].lines[0] == "Second"
    assert matches[2][0] is u2
    assert matches[2][1] is u2


def test_word_diff_identical() -> None:
    result = word_diff("Hello world", "Hello world")
    assert result == [("equal", "Hello"), ("equal", "world")]


def test_word_diff_insertion() -> None:
    result = word_diff("Hello", "Hello world")
    assert ("insert", "world") in result
    assert ("equal", "Hello") in result


def test_word_diff_deletion() -> None:
    result = word_diff("Hello world", "Hello")
    assert ("delete", "world") in result
    assert ("equal", "Hello") in result


def test_word_diff_replacement() -> None:
    result = word_diff("Hello world", "Hello there")
    assert ("delete", "world") in result
    assert ("insert", "there") in result
    assert ("equal", "Hello") in result


def test_merge_units_empty() -> None:
    result = merge_units("", "", "")
    assert len(result.units) == 1
    assert len(result.conflicts) == 0


def test_merge_units_only_ours_added() -> None:
    base = ""
    ours = "New text.\n"
    theirs = ""
    result = merge_units(base, ours, theirs)
    assert len(result.conflicts) == 0
    assert len(result.units) == 1
    assert result.units[0].lines[0] == "New text."


def test_merge_units_only_theirs_added() -> None:
    base = ""
    ours = ""
    theirs = "New text.\n"
    result = merge_units(base, ours, theirs)
    assert len(result.conflicts) == 0
    assert len(result.units) == 1
    assert result.units[0].lines[0] == "New text."


def test_apply_choices_ours() -> None:
    base = Unit(UnitKind.PARAGRAPH, ["Base text."], 1)
    ours = Unit(UnitKind.PARAGRAPH, ["Ours text."], 1)
    theirs = Unit(UnitKind.PARAGRAPH, ["Theirs text."], 1)
    result = MergeResult(
        units=[ours],
        conflicts=[Change(kind="text", base=base, ours=ours, theirs=theirs)],
        merged=[],
    )
    result_text = apply_choices(result, {0: "ours"})
    assert result_text == "Ours text."


def test_apply_choices_theirs() -> None:
    base = Unit(UnitKind.PARAGRAPH, ["Base text."], 1)
    ours = Unit(UnitKind.PARAGRAPH, ["Ours text."], 1)
    theirs = Unit(UnitKind.PARAGRAPH, ["Theirs text."], 1)
    result = MergeResult(
        units=[ours],
        conflicts=[Change(kind="text", base=base, ours=ours, theirs=theirs)],
        merged=[],
    )
    result_text = apply_choices(result, {0: "theirs"})
    assert result_text == "Theirs text."


def test_apply_choices_both() -> None:
    base = Unit(UnitKind.PARAGRAPH, ["Base text."], 1)
    ours = Unit(UnitKind.PARAGRAPH, ["Ours text."], 1)
    theirs = Unit(UnitKind.PARAGRAPH, ["Theirs text."], 1)
    result = MergeResult(
        units=[ours],
        conflicts=[Change(kind="text", base=base, ours=ours, theirs=theirs)],
        merged=[],
    )
    result_text = apply_choices(result, {0: "both"})
    assert "Ours text." in result_text
    assert "Theirs text." in result_text


def test_word_diff_empty() -> None:
    result = word_diff("", "")
    assert result == []


def test_word_diff_only_insertion() -> None:
    result = word_diff("", "Hello world")
    assert result == [("insert", "Hello"), ("insert", "world")]


def test_word_diff_only_deletion() -> None:
    result = word_diff("Hello world", "")
    assert result == [("delete", "Hello"), ("delete", "world")]
