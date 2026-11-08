"""
UmbraEdit - Sheet Note Editing
===============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Rewrites the keyword block of an entity note when aliases or attributes
change. Everything outside the keyword block is preserved byte for
byte. Qt-free; the GUI layer routes the result through the editor
document when the note is open so undo works.
"""  # noqa

from __future__ import annotations

from dataclasses import dataclass, field

from umbraedit.umbra.sheet import CHARACTER_COLUMNS

# Canonical column order for @attr lines: built-ins first (in column
# order), then custom columns (x_ keys) sorted alphabetically.
_ATTR_ORDER: dict[str, int] = {key: i for i, key in enumerate(CHARACTER_COLUMNS)}


@dataclass
class SheetEdit:
    """A pending sheet edit for one note.

    Attributes:
        aliases: The full new list of aliases (without pronunciation).
        pronunciations: Alias text -> pronunciation, when present.
        attrs: The full new dict of attributes.

    """

    aliases: list[str] = field(default_factory=list)
    pronunciations: dict[str, str] = field(default_factory=dict)
    attrs: dict[str, str] = field(default_factory=dict)


def _attrSortKey(key: str) -> tuple[int, str]:
    """Sort @attr keys: built-ins in column order, custom after, then
    anything unknown, alphabetically within each group.
    """
    if key in _ATTR_ORDER:
        return 0, f"{_ATTR_ORDER[key]:04d}{key}"
    if key.startswith("x_"):
        return 1, key
    return 2, key


def _keywordLine(key: str, value: str) -> str:
    """Build one canonical keyword line."""
    return f"{key}: {value}" if value else f"{key}:"


def _splitKeywordLine(line: str) -> tuple[str, str] | None:
    """Split a keyword line into (key, raw value), or None."""
    stripped = line.strip()
    if not stripped.startswith("@"):
        return None
    key, _, value = stripped.partition(":")
    return key.strip(), value.strip()


def keywordBlockRange(lines: list[str]) -> tuple[int, int] | None:
    """Return the (start, end) slice of the keyword block.

    The keyword block is the first contiguous run of lines starting
    with `@`. Returns None when the note has no keyword block.
    """
    start = -1
    for i, line in enumerate(lines):
        if line.startswith("@"):
            start = i
            break
        # The block must start before any prose: allow blank lines and
        # the title, stop at the first non-empty non-keyword line.
        if line.strip() and not line.startswith("#"):
            return None
    if start < 0:
        return None
    end = start
    while end < len(lines) and lines[end].startswith("@"):
        end += 1
    return start, end


def renderKeywordBlock(edit: SheetEdit, keepLines: list[str]) -> list[str]:
    """Render the new keyword block lines.

    `keepLines` are the existing keyword lines. `@tag` and any upstream
    keywords keep their original relative order; `@alias` and `@attr`
    lines are rebuilt from the edit in canonical order.
    """
    keep: list[str] = []
    for line in keepLines:
        parsed = _splitKeywordLine(line)
        if parsed is None:
            keep.append(line)
            continue
        key, _ = parsed
        if key == "@alias":
            continue  # rebuilt
        if key == "@attr":
            continue  # rebuilt
        keep.append(line)

    aliasLines: list[str] = []
    for alias in edit.aliases:
        pron = edit.pronunciations.get(alias, "")
        value = f"{alias} | {pron}" if pron else alias
        aliasLines.append(_keywordLine("@alias", value))

    attrLines: list[str] = []
    for key in sorted(edit.attrs, key=_attrSortKey):
        value = edit.attrs[key]
        attrLines.append(_keywordLine("@attr", f"{key} | {value}" if value else key))

    return keep + aliasLines + attrLines


def aliasNormKey(text: str) -> str:
    """Normalise an alias for identity checks (delegates to aliasNorm)."""
    from umbraedit.umbra.sheet import aliasNorm

    return aliasNorm(text)


def parseSheetNote(text: str) -> SheetEdit:
    """Read the aliases and attributes of a note into a SheetEdit."""
    edit = SheetEdit()
    lines = text.split("\n")
    block = keywordBlockRange(lines)
    if block is None:
        return edit
    for line in lines[block[0] : block[1]]:
        parsed = _splitKeywordLine(line)
        if parsed is None:
            continue
        key, value = parsed
        if key == "@alias":
            name, pron = value.partition("|")[0].strip(), value.partition("|")[2].strip()
            if name:
                edit.aliases.append(name)
                if pron:
                    edit.pronunciations[name] = pron
        elif key == "@attr":
            attrKey, _, attrValue = value.partition("|")
            attrKey = attrKey.strip()
            if attrKey:
                edit.attrs[attrKey] = attrValue.strip()
    return edit


def applySheetEdit(text: str, edit: SheetEdit) -> str:
    """Return the note text with the keyword block rewritten.

    Everything outside the keyword block is preserved byte for byte.
    If the note has no keyword block, one is created directly after the
    first line (the title), followed by a blank line.
    """
    lines = text.split("\n")
    block = keywordBlockRange(lines)

    if block is None:
        # No keyword block: insert one after the first line. The first
        # line is the note title; if the note is empty, the block is
        # simply prepended.
        if not lines or (len(lines) == 1 and not lines[0]):
            newBlock = renderKeywordBlock(edit, [])
            return "\n".join([*newBlock, ""])
        insertAt = 1
        head = lines[:insertAt]
        tail = lines[insertAt:]
        newBlock = renderKeywordBlock(edit, [])
        return "\n".join(head + newBlock + [""] + tail)

    start, end = block
    newBlock = renderKeywordBlock(edit, lines[start:end])
    return "\n".join(lines[:start] + newBlock + lines[end:])
