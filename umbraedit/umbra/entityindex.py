"""
UmbraEdit - Entity Index
=========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Collects entity sheet data (`@tag`, `@alias`, `@attr` lines) from
documents as they are indexed, and exposes entity queries. Qt-free.
"""  # noqa

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any

from umbraedit.constants import nwItemClass
from umbraedit.umbra.sheet import ENTITY_KINDS, EntityRow

logger = logging.getLogger(__name__)

# Map from item class to entity kind
_CLASS_KIND: dict[nwItemClass, str] = {
    nwItemClass.CHARACTER: "character",
    nwItemClass.WORLD: "place",
    nwItemClass.OBJECT: "thing",
    nwItemClass.ENTITY: "organisation",
}


@dataclass
class _EntityRecord:
    """Raw sheet data collected from one document."""

    tag: str = ""
    displayName: str = ""
    aliases: list[tuple[str, str]] = field(default_factory=list)  # (alias, pronunciation)
    attrs: dict[str, str] = field(default_factory=dict)
    prons: list[tuple[str, str, str]] = field(default_factory=list)  # (lang, respelling, ipa)
    origin: str = "book"  # "book" or "bible"


def _splitValue(value: str) -> tuple[str, str]:
    """Split a keyword value into (name, display) on the first pipe."""
    name, _, display = value.partition("|")
    return name.strip(), display.strip()


def _stripIpaDelims(text: str) -> str:
    """Strip matching surrounding IPA delimiters (`/.../` or `[...]`)."""
    if len(text) >= 2 and text[0] == "/" and text[-1] == "/":
        return text[1:-1].strip()
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        return text[1:-1].strip()
    return text


class EntityIndex:
    """Holds entity sheet data collected during indexing.

    The data is collected by `core.index` when documents are scanned:
    `scanStarted` resets the record for a document, and `recordKeyword`
    adds `@alias` and `@attr` values as they are parsed. Queries take
    the project object to resolve the entity kind from the item class.
    """

    def __init__(self) -> None:
        self._records: dict[str, _EntityRecord] = {}
        self._scanning: set[str] = set()

    ##
    #  Collection (called from core.index)
    ##

    def scanStarted(self, tHandle: str, text: str) -> None:
        """Reset the record for a document about to be scanned, and
        record its tag from the text directly.
        """
        record = _EntityRecord()
        for line in text.splitlines():
            if not line.startswith("@"):
                continue
            key, _, value = line.partition(":")
            if key.strip() == "@tag":
                name, display = _splitValue(value)
                record.tag = name
                record.displayName = display
                break
        self._records[tHandle] = record

    def recordKeyword(self, tHandle: str, key: str, values: list[str]) -> None:
        """Record an `@alias`, `@attr` or `@pron` keyword value.

        Values are pre-split by the index scanner, one value per list
        entry. An `@alias` value may contain a pronunciation after a
        pipe; an `@attr` value is `key | value`; an `@pron` value is
        `lang | respelling [| ipa]` with the IPA written between
        slashes. Note: the index scanner splits values on commas, so
        `@pron` fields must not contain commas.
        """
        record = self._records.get(tHandle)
        if record is None:
            record = _EntityRecord()
            self._records[tHandle] = record

        if key == "@alias":
            for value in values:
                alias, pronunciation = _splitValue(value)
                if alias:
                    record.aliases.append((alias, pronunciation))
        elif key == "@attr":
            for value in values:
                attrKey, attrValue = _splitValue(value)
                if attrKey:
                    record.attrs[attrKey] = attrValue
        elif key == "@pron":
            for value in values:
                lang, _, rest = value.partition("|")
                lang = lang.strip()
                if not lang:
                    continue
                respelling, _, ipaRaw = rest.partition("|")
                ipa = _stripIpaDelims(ipaRaw.strip())
                record.prons.append((lang, respelling.strip(), ipa))

    def dropHandle(self, tHandle: str) -> None:
        """Drop all data for a document handle."""
        self._records.pop(tHandle, None)
        self._scanning.discard(tHandle)

    def clear(self) -> None:
        """Clear all collected data."""
        self._records.clear()
        self._scanning.clear()

    ##
    #  Queries
    ##

    def _kindForHandle(self, project: Any, tHandle: str) -> str:
        """Resolve the entity kind for a handle from the item class."""
        item = project.tree[tHandle] if project else None
        if item is None:
            return ""
        kind = _CLASS_KIND.get(item.itemClass, "")
        if kind:
            return kind
        # Fall back to an explicit @attr: kind value if it is a known kind
        record = self._records.get(tHandle)
        if record and record.attrs.get("kind", "") in ENTITY_KINDS:
            return record.attrs["kind"]
        return ""

    def getEntity(self, project: Any, tag: str) -> EntityRow | None:
        """Return the entity for a tag, or None.

        Tag matching is exact first, then case-insensitive, mirroring
        how the tag index resolves tags.
        """
        if not tag:
            return None
        record = None
        rHandle = ""
        for tHandle, tRecord in self._records.items():
            if tRecord.tag and tRecord.tag == tag:
                record, rHandle = tRecord, tHandle
                break
        if record is None:
            fold = tag.casefold()
            for tHandle, tRecord in self._records.items():
                if tRecord.tag and tRecord.tag.casefold() == fold:
                    record, rHandle = tRecord, tHandle
                    break
        if record is None or not record.tag:
            return None
        return EntityRow(
            tag=record.tag,
            handle=rHandle,
            kind=self._kindForHandle(project, rHandle),
            displayName=record.displayName,
            aliases=[alias for alias, _ in record.aliases],
            attrs=dict(record.attrs),
            prons=list(record.prons),
            aliasPron={alias: pron for alias, pron in record.aliases if pron},
            origin=record.origin,
        )

    def iterEntities(self, project: Any, kind: str | None = None) -> list[EntityRow]:
        """Return all tagged entities, optionally filtered by kind."""
        rows: list[EntityRow] = []
        for tHandle, record in self._records.items():
            if not record.tag:
                continue
            entityKind = self._kindForHandle(project, tHandle)
            if not entityKind:
                continue
            if kind is not None and entityKind != kind:
                continue
            rows.append(
                EntityRow(
                    tag=record.tag,
                    handle=tHandle,
                    kind=entityKind,
                    displayName=record.displayName,
                    aliases=[alias for alias, _ in record.aliases],
                    attrs=dict(record.attrs),
                    prons=list(record.prons),
                    aliasPron={alias: pron for alias, pron in record.aliases if pron},
                    origin=record.origin,
                )
            )
        rows.sort(key=lambda r: r.tag.casefold())
        return rows

    def entityHandle(self, tag: str) -> str | None:
        """Return the handle of the document holding a tag, or None."""
        for tHandle, record in self._records.items():
            if record.tag and record.tag.casefold() == tag.casefold():
                return tHandle
        return None
