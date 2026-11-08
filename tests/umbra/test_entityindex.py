"""
UmbraEdit - Entity Index Tests
===============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from umbraedit.umbra.entityindex import EntityIndex

if TYPE_CHECKING:  # pragma: no cover
    from pathlib import Path

    from tests.helpers import MockRnd


@pytest.fixture
def idx() -> EntityIndex:
    """A fresh entity index for each test."""
    return EntityIndex()


def _scanDoc(idx: EntityIndex, handle: str, text: str) -> None:
    """Simulate the index flow: scanStarted, then keyword recording."""
    idx.scanStarted(handle, text)


@pytest.mark.umbra
def test_entityindex_R1_scanStarted_parsesTag(idx: EntityIndex):
    """R1: scanStarted records the tag and display name."""
    idx.scanStarted("h1", "# Bob Vega\n\n@tag: Bob | Bob Vega\n@alias: Uncle Bob\n")
    record = idx._records["h1"]
    assert record.tag == "Bob"
    assert record.displayName == "Bob Vega"


@pytest.mark.umbra
def test_entityindex_R1_recordAlias(idx: EntityIndex):
    """R1: @alias values are recorded, one per line."""
    idx.scanStarted("h1", "# Bob\n\n@tag: Bob\n@alias: Uncle Bob\n@alias: Robert\n")
    idx.recordKeyword("h1", "@alias", ["Uncle Bob"])
    idx.recordKeyword("h1", "@alias", ["Robert"])
    assert idx._records["h1"].aliases == [("Uncle Bob", ""), ("Robert", "")]


@pytest.mark.umbra
def test_entityindex_R1_aliasWithPronunciation(idx: EntityIndex):
    """R1: an alias pronunciation after a pipe is kept separate (P07)."""
    idx.recordKeyword("h1", "@alias", ["Uncle Bob | UN-kul bob"])
    assert idx._records["h1"].aliases == [("Uncle Bob", "UN-kul bob")]


@pytest.mark.umbra
def test_entityindex_R1_recordAttr(idx: EntityIndex):
    """R1: @attr key/value pairs are recorded."""
    idx.recordKeyword("h1", "@attr", ["kind | character"])
    idx.recordKeyword("h1", "@attr", ["slot | 1"])
    assert idx._records["h1"].attrs == {"kind": "character", "slot": "1"}


@pytest.mark.umbra
def test_entityindex_R1_rescanReplacesRecord(idx: EntityIndex):
    """R1: rescanning a document replaces its record (external edits)."""
    idx.scanStarted("h1", "# Bob\n\n@tag: Bob\n")
    idx.recordKeyword("h1", "@attr", ["slot | 1"])
    idx.scanStarted("h1", "# Bob\n\n@tag: Bob\n")  # edit removed the attr
    assert idx._records["h1"].attrs == {}


@pytest.mark.umbra
def test_entityindex_R1_dropHandle(idx: EntityIndex):
    """R1: dropping a handle removes its record."""
    idx.scanStarted("h1", "# Bob\n\n@tag: Bob\n")
    idx.dropHandle("h1")
    assert "h1" not in idx._records
    idx.dropHandle("missing")  # no error


@pytest.mark.umbra
def test_entityindex_R1_clear(idx: EntityIndex):
    """R1: clear removes all records."""
    idx.scanStarted("h1", "# Bob\n\n@tag: Bob\n")
    idx.scanStarted("h2", "# Ohio\n\n@tag: Ohio\n")
    idx.clear()
    assert idx._records == {}


class _FakeItem:
    """Minimal stand-in for a ProjectItem."""

    def __init__(self, className: str) -> None:
        from umbraedit.enum import nwItemClass

        self.itemClass = nwItemClass[className]


class _FakeTree:
    def __init__(self, items: dict) -> None:
        self._items = items

    def __getitem__(self, handle: str):
        return self._items.get(handle)


class _FakeProject:
    def __init__(self, items: dict) -> None:
        self.tree = _FakeTree(items)


@pytest.mark.umbra
def test_entityindex_R1_getEntity(idx: EntityIndex):
    """R1: getEntity returns an EntityRow for a tag."""
    project = _FakeProject({"h1": _FakeItem("CHARACTER")})
    idx.scanStarted("h1", "# Bob\n\n@tag: Bob | Bob Vega\n@alias: Uncle Bob\n@attr: slot | 1\n")
    idx.recordKeyword("h1", "@alias", ["Uncle Bob"])
    idx.recordKeyword("h1", "@attr", ["slot | 1"])
    row = idx.getEntity(project, "Bob")
    assert row is not None
    assert row.tag == "Bob"
    assert row.handle == "h1"
    assert row.kind == "character"
    assert row.aliases == ["Uncle Bob"]
    assert row.attrs == {"slot": "1"}


@pytest.mark.umbra
def test_entityindex_R1_getEntity_caseInsensitive(idx: EntityIndex):
    """R1: tag lookup falls back to case-insensitive matching."""
    project = _FakeProject({"h1": _FakeItem("CHARACTER")})
    idx.scanStarted("h1", "# Bob\n\n@tag: Bob\n")
    assert idx.getEntity(project, "BOB") is not None
    assert idx.getEntity(project, "Nobody") is None
    assert idx.getEntity(project, "") is None


@pytest.mark.umbra
def test_entityindex_R1_getEntity_kinds(idx: EntityIndex):
    """R1: kind comes from the item class (A8 basis)."""
    project = _FakeProject({
        "h1": _FakeItem("CHARACTER"),
        "h2": _FakeItem("WORLD"),
        "h3": _FakeItem("OBJECT"),
        "h4": _FakeItem("ENTITY"),
    })
    idx.scanStarted("h1", "# A\n\n@tag: Ana\n")
    idx.scanStarted("h2", "# P\n\n@tag: Ohio\n")
    idx.scanStarted("h3", "# T\n\n@tag: Lamp\n")
    idx.scanStarted("h4", "# O\n\n@tag: Guild\n")
    assert idx.getEntity(project, "Ana").kind == "character"
    assert idx.getEntity(project, "Ohio").kind == "place"
    assert idx.getEntity(project, "Lamp").kind == "thing"
    assert idx.getEntity(project, "Guild").kind == "organisation"


@pytest.mark.umbra
def test_entityindex_R1_iterEntities(idx: EntityIndex):
    """R1: iterEntities returns all tagged entities, filterable by kind."""
    project = _FakeProject({
        "h1": _FakeItem("CHARACTER"),
        "h2": _FakeItem("WORLD"),
    })
    idx.scanStarted("h1", "# A\n\n@tag: Ana\n")
    idx.scanStarted("h2", "# P\n\n@tag: Ohio\n")
    idx.scanStarted("h3", "# No tag here\n")
    allRows = idx.iterEntities(project)
    assert [r.tag for r in allRows] == ["Ana", "Ohio"]
    places = idx.iterEntities(project, kind="place")
    assert [r.tag for r in places] == ["Ohio"]
    chars = idx.iterEntities(project, kind="character")
    assert [r.tag for r in chars] == ["Ana"]


@pytest.mark.umbra
def test_entityindex_R1_entityHandle(idx: EntityIndex):
    """R1: entityHandle maps a tag back to its document handle."""
    idx.scanStarted("h1", "# A\n\n@tag: Ana\n")
    assert idx.entityHandle("ana") == "h1"
    assert idx.entityHandle("Ghost") is None


@pytest.mark.umbra
def test_entityindex_P07_recordPron(idx: EntityIndex):
    """P07 R1: @pron values are recorded as (lang, respelling, ipa)."""
    idx.recordKeyword("h1", "@pron", ["en | KAT-niss ev-er-DEEN | /\u02c8k\u00e6tn\u026as/"])
    idx.recordKeyword("h1", "@pron", ["es | KAT-nis"])
    assert idx._records["h1"].prons == [
        ("en", "KAT-niss ev-er-DEEN", "\u02c8k\u00e6tn\u026as"),
        ("es", "KAT-nis", ""),
    ]


@pytest.mark.umbra
def test_entityindex_P07_recordPron_bracketDelims(idx: EntityIndex):
    """P07 R1: square-bracket IPA delimiters are stripped too."""
    idx.recordKeyword("h1", "@pron", ["en | KAT | [k\u00e6t]"])
    assert idx._records["h1"].prons == [("en", "KAT", "k\u00e6t")]


@pytest.mark.umbra
def test_entityindex_P07_entityRowPronFields(idx: EntityIndex):
    """P07 R1: getEntity carries prons and alias respellings."""
    project = _FakeProject({"h1": _FakeItem("CHARACTER")})
    idx.scanStarted("h1", "# Bob\n\n@tag: Bob | Bob Vega\n@alias: Uncle Bob | UN-kul bob\n")
    idx.recordKeyword("h1", "@alias", ["Uncle Bob | UN-kul bob"])
    idx.recordKeyword("h1", "@pron", ["en | BOB | /b\u0252b/"])
    row = idx.getEntity(project, "Bob")
    assert row is not None
    assert row.displayName == "Bob Vega"
    assert row.prons == [("en", "BOB", "b\u0252b")]
    assert row.aliasPron == {"Uncle Bob": "UN-kul bob"}


@pytest.mark.umbra
def test_entityindex_P07_integrationWithRealIndex(monkeypatch: pytest.MonkeyPatch, fncPath, mockRnd, nwGUI):
    """P07: the real index records @pron via a project scan."""
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
        "@pron: en | KAT-niss ev-er-DEEN | /\u02c8k\u00e6tn\u026as/\n"
        "@attr: kind | character\n"
        "@attr: pron_status | confirmed\n"
    )
    project.index.reIndexHandle(cHandle)

    row = project.index.getEntity("Katniss")
    assert row is not None
    assert row.prons == [("en", "KAT-niss ev-er-DEEN", "\u02c8k\u00e6tn\u026as")]
    assert row.displayName == "Katniss Everdeen"
    assert row.attrs["pron_status"] == "confirmed"


@pytest.mark.umbra
def test_entityindex_R1_integrationWithRealIndex(
    monkeypatch: pytest.MonkeyPatch,
    fncPath: Path,
    mockRnd: MockRnd,
    nwGUI: object,
):
    """R1/A8: the real index records @alias/@attr via a project scan."""
    from umbraedit.core.project import NWProject

    from tests.helpers import C, buildTestProject

    project = NWProject()
    mockRnd.reset()
    buildTestProject(project, fncPath)

    # A character note with aliases and attributes
    cHandle = project.newFile("Bob Vega", C.hCharRoot)
    assert isinstance(cHandle, str)
    aDoc = project.storage.getDocument(cHandle)
    aDoc.writeDocument(
        "# Bob Vega\n\n"
        "@tag: Bob | Bob Vega\n"
        "@alias: Uncle Bob\n"
        "@attr: kind | character\n"
        "@attr: slot | 1\n"
        "@attr: x_birthplace | Ohio\n"
    )
    project.index.reIndexHandle(cHandle)

    # A place note without a kind declaration
    wHandle = project.newFile("Ohio", C.hWorldRoot)
    assert isinstance(wHandle, str)
    aDoc = project.storage.getDocument(wHandle)
    aDoc.writeDocument("# Ohio\n\n@tag: Ohio\n@attr: kind | place\n")
    project.index.reIndexHandle(wHandle)

    # The index exposes the entity queries
    row = project.index.getEntity("Bob")
    assert row is not None
    assert row.tag == "Bob"
    assert row.kind == "character"
    assert row.aliases == ["Uncle Bob"]
    assert row.attrs == {"kind": "character", "slot": "1", "x_birthplace": "Ohio"}

    allRows = project.index.iterEntities()
    assert {r.tag for r in allRows} == {"Bob", "Ohio"}
    assert [r.tag for r in project.index.iterEntities(kind="place")] == ["Ohio"]
