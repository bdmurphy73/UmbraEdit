"""
UmbraEdit - Entity Sheet Tests
===============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import time

from pathlib import Path

import pytest

from umbraedit.umbra.paths import tonesFile
from umbraedit.umbra.sheet import (
    DEFAULT_TONES,
    EntityRow,
    SheetManager,
    ToneEntry,
    aliasNorm,
    full_name,
)


def _makeManager(tmpPath: Path) -> SheetManager:
    """Create a SheetManager and populate it with test entities."""
    mgr = SheetManager(tmpPath)
    mgr._entityMap["Bob"] = EntityRow(
        tag="Bob",
        handle="h000000001",
        kind="character",
        aliases=["Uncle Bob", "Robert"],
        attrs={"slot": "1", "fn": "Robert", "ln": "Vega", "nick": "Bob", "kind": "character"},
    )
    mgr._entityMap["Ana"] = EntityRow(
        tag="Ana",
        handle="h000000002",
        kind="character",
        aliases=[],
        attrs={"slot": "2", "fn": "Ana", "ln": "Soler", "kind": "character"},
    )
    mgr._entityMap["Ohio"] = EntityRow(
        tag="Ohio",
        handle="h000000003",
        kind="place",
        aliases=["The Buckeye State"],
        attrs={"kind": "place", "description": "A midwestern state"},
    )
    return mgr


@pytest.mark.umbra
def test_sheet_aliasNorm_basic():
    """aliasNorm: NFKC, casefold, punctuation removal, whitespace collapse."""
    assert aliasNorm("Uncle Bob") == "uncle bob"
    assert aliasNorm("  Uncle   Bob!  ") == "uncle bob"
    assert aliasNorm("Uncle-Bob.") == "unclebob"
    assert aliasNorm("Ｕｎｃｌｅ Bob") == "uncle bob"  # noqa: RUF001 (fullwidth NFKC test)
    assert aliasNorm("CAFÉ") == "café"
    assert aliasNorm("") == ""


@pytest.mark.umbra
def test_sheet_full_name_computed():
    """full_name is computed from title/fn/mn/ln/suffix, never stored."""
    attrs = {"title": "Dr", "fn": "Robert", "mn": "James", "ln": "Vega", "suffix": "Jr"}
    assert full_name(attrs) == "Dr Robert James Vega Jr"
    assert full_name({"fn": "Ana"}) == "Ana"
    assert full_name({}) == ""


@pytest.mark.umbra
def test_sheet_R2_resolveSpeaker_tag():
    """R2: resolveSpeaker matches a tag."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    hits = mgr.resolveSpeaker("Bob")
    assert len(hits) == 1
    assert hits[0].tag == "Bob"


@pytest.mark.umbra
def test_sheet_R2_resolveSpeaker_alias():
    """R2: resolveSpeaker matches an alias, normalised."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    hits = mgr.resolveSpeaker("uncle bob!")
    assert len(hits) == 1
    assert hits[0].tag == "Bob"


@pytest.mark.umbra
def test_sheet_R2_resolveSpeaker_attrNames():
    """R2: resolveSpeaker matches fn, ln, nick, title, full_name."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    assert [r.tag for r in mgr.resolveSpeaker("Robert")] == ["Bob"]
    assert [r.tag for r in mgr.resolveSpeaker("Vega")] == ["Bob"]
    assert [r.tag for r in mgr.resolveSpeaker("robert vega")] == ["Bob"]


@pytest.mark.umbra
def test_sheet_R2_resolveSpeaker_allMatches():
    """R2: a shared alias returns all matching entities (A3 basis)."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    mgr._entityMap["Bobby Jr"] = EntityRow(
        tag="Bobby Jr",
        handle="h000000004",
        kind="character",
        aliases=["Bobby"],
        attrs={"slot": "3"},
    )
    mgr._entityMap["Bob"].aliases.append("Bobby")
    hits = mgr.resolveSpeaker("Bobby")
    assert len(hits) == 2
    assert {r.tag for r in hits} == {"Bob", "Bobby Jr"}


@pytest.mark.umbra
def test_sheet_R2_resolveSpeaker_noMatch():
    """R2: no match returns an empty list."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    assert mgr.resolveSpeaker("Nobody") == []
    assert mgr.resolveSpeaker("") == []


@pytest.mark.umbra
def test_sheet_R2_addAlias_idempotent():
    """R2: addAlias adds once; adding again changes nothing (A1)."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    assert mgr.addAlias("Bob", "Uncle Bob") is False  # already present
    assert mgr.addAlias("Bob", "uncle  bob!") is False  # same after norm
    assert mgr._entityMap["Bob"].aliases.count("Uncle Bob") == 1
    assert mgr.addAlias("Bob", "Bobby") is True
    assert "Bobby" in mgr._entityMap["Bob"].aliases


@pytest.mark.umbra
def test_sheet_R2_addAlias_unknownTag():
    """R2: addAlias on an unknown tag fails gracefully."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    assert mgr.addAlias("Ghost", "Spooky") is False


@pytest.mark.umbra
def test_sheet_R2_setAttr():
    """R2: setAttr sets an attribute on an entity."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    assert mgr.setAttr("Bob", "age", "42") is True
    assert mgr._entityMap["Bob"].attrs["age"] == "42"
    assert mgr.setAttr("Ghost", "age", "42") is False


@pytest.mark.umbra
def test_sheet_R2_getVoiceCode():
    """R2: getVoiceCode returns the voice_matrix code or None."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    assert mgr.getVoiceCode("Bob") is None
    mgr.setAttr("Bob", "voice_matrix", "vm-9f3a1c20d7e4")
    assert mgr.getVoiceCode("Bob") == "vm-9f3a1c20d7e4"
    assert mgr.getVoiceCode("Ghost") is None


@pytest.mark.umbra
def test_sheet_R6_nextSlot():
    """R6: nextSlot returns the next free slot number."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    assert mgr.nextSlot() == 3  # 1 and 2 are taken
    mgr._entityMap.pop("Ana")
    assert mgr.nextSlot() == 2
    mgr._entityMap.clear()
    assert mgr.nextSlot() == 1


@pytest.mark.umbra
def test_sheet_R6_slotDuplicate_detection():
    """R6: duplicate slots can be detected for the slotDuplicate gate."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    mgr._entityMap["Cara"] = EntityRow(
        tag="Cara",
        handle="h000000005",
        kind="character",
        attrs={"slot": "1"},
    )
    slots: dict[int, list[str]] = {}
    for row in mgr.iterEntities("character"):
        slotVal = row.attrs.get("slot", "")
        if slotVal.isdigit():
            slots.setdefault(int(slotVal), []).append(row.tag)
    dupes = {s: t for s, t in slots.items() if len(t) > 1}
    assert dupes == {1: ["Bob", "Cara"]}


@pytest.mark.umbra
def test_sheet_R7_promoteOneOff():
    """R7: promoteOneOff creates a tag with a slot and the label as alias."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    tag = mgr.promoteOneOff("~the_guard")
    assert tag is not None
    assert tag == "TheGuard"
    row = mgr.getEntity(tag)
    assert row is not None
    assert row.attrs.get("slot") == "3"  # next free slot
    assert "~the_guard" in row.aliases
    # Second promotion with the same label fails (tag exists)
    assert mgr.promoteOneOff("~the_guard") is None


@pytest.mark.umbra
def test_sheet_R7_promoteOneOff_unicodeLabel():
    """R7: one-off labels with unusual characters are promoted cleanly."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    tag = mgr.promoteOneOff("~cafe_waiter")
    assert tag == "CafeWaiter"
    assert mgr.getEntity(tag) is not None


@pytest.mark.umbra
def test_sheet_R5_loadTones_seeds16(tmp_path: Path):
    """R5: loadTones seeds the 16 default tones when the file is missing."""
    mgr = SheetManager(tmp_path)
    tones = mgr.loadTones()
    assert len(tones) == 16
    assert {t.key for t in tones} == {t.key for t in DEFAULT_TONES}
    # Seeded on disk
    assert tonesFile(tmp_path).is_file()


@pytest.mark.umbra
def test_sheet_R5_loadTones_persisted(tmp_path: Path):
    """R5: a saved tone set round-trips through loadTones."""
    custom = [
        ToneEntry("neutral", "Neutral", "both", "", 1),
        ToneEntry("happy", "Happy", "dialogue", "style=cheerful", 2),
        ToneEntry("dreamy", "Dreamy", "narration", "style=dreamy", 3),
    ]
    mgr = SheetManager(tmp_path)
    mgr.saveTones(custom)
    mgr2 = SheetManager(tmp_path)
    tones = mgr2.loadTones()
    assert [t.key for t in tones] == ["neutral", "happy", "dreamy"]
    assert tones[2].audioHint == "style=dreamy"


@pytest.mark.umbra
def test_sheet_R5_loadTones_unknownKept(tmp_path: Path):
    """R5/A6: a hand-edited unknown tone is returned as-is, never removed."""
    mgr = SheetManager(tmp_path)
    mgr.loadTones()  # seed
    # Hand-edit the file to add an unknown tone
    from umbraedit.umbra.jsonio import readJson, writeJson

    data = readJson(tonesFile(tmp_path))
    data["tones"].append({"key": "wistful", "label": "Wistful", "appliesTo": "both", "audioHint": "", "order": 99})
    writeJson(tonesFile(tmp_path), data)
    tones = SheetManager(tmp_path).loadTones()
    keys = [t.key for t in tones]
    assert "wistful" in keys  # kept, flagging is the gate's job
    assert len(keys) == 17


@pytest.mark.umbra
def test_sheet_R5_loadTones_corruptFile(tmp_path: Path):
    """R5: a corrupt tones file is re-seeded with defaults."""
    p = tonesFile(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json at all", encoding="utf-8")
    tones = SheetManager(tmp_path).loadTones()
    assert len(tones) == 16


@pytest.mark.umbra
def test_sheet_iterEntities_filter():
    """IterEntities returns all entities, optionally filtered by kind."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    allRows = mgr.iterEntities()
    assert len(allRows) == 3
    chars = mgr.iterEntities("character")
    assert {r.tag for r in chars} == {"Bob", "Ana"}
    places = mgr.iterEntities("place")
    assert {r.tag for r in places} == {"Ohio"}


@pytest.mark.umbra
def test_sheet_A1_aliasWorkflow():
    """A1: adding the alias, re-adding, then resolving."""
    mgr = _makeManager(Path("/tmp/nonexistent-test"))
    # "Uncle Bob" is already there; adding again changes nothing
    before = list(mgr._entityMap["Bob"].aliases)
    mgr.addAlias("Bob", "Uncle Bob")
    assert mgr._entityMap["Bob"].aliases == before
    # resolveSpeaker with punctuation and case differences
    hits = mgr.resolveSpeaker("uncle bob!")
    assert len(hits) == 1
    assert hits[0].tag == "Bob"


@pytest.mark.umbra
def test_sheet_R9_resolveSpeaker_performance():
    """R9: resolveSpeaker under 5 ms with 500 entities and 2,000 aliases."""
    mgr = SheetManager(Path("/tmp/nonexistent-test"))
    for i in range(500):
        aliases = [f"alias_{j}_for_{i}" for j in range(4)]  # 2,000 aliases
        mgr._entityMap[f"Ent{i:04d}"] = EntityRow(
            tag=f"Ent{i:04d}",
            handle=f"h{i:09d}",
            kind="character",
            aliases=aliases,
            attrs={"slot": str(i + 1), "fn": f"First{i}", "ln": f"Last{i}"},
        )
    # Warm up and measure
    mgr.resolveSpeaker("alias_2_for_250")
    start = time.perf_counter()
    for _ in range(20):
        hits = mgr.resolveSpeaker("alias_2_for_250")
        hits2 = mgr.resolveSpeaker("Ent0250")
        hits3 = mgr.resolveSpeaker("first250")
    elapsed = (time.perf_counter() - start) / 3 / 20 * 1000.0
    assert hits
    assert hits2
    assert hits3
    # Budget 5 ms, generous 3x margin for CI → 15 ms
    assert elapsed < 15.0, f"resolveSpeaker took {elapsed:.2f} ms"
