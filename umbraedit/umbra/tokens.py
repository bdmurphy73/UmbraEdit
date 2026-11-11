"""
UmbraEdit - Character Slot Tokens and Template Variables
========================================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import logging
import re

from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Regex for {charN attr} tokens where N is a slot number and attr is
# an optional attribute key.
TOKEN_RE = re.compile(r"\{char(\d+)(?:\s+(\S+))?\}")

# Regex for {{variable}} template variables
VARIABLE_RE = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")

# Known attribute keys
KNOWN_ATTRS: frozenset[str] = frozenset({"fn", "mn", "ln", "nick", "title", "suffix", "full_name"})


@dataclass(frozen=True)
class Token:
    """A parsed character slot token found in text.

    Attributes:
        start: Character offset of the opening brace in the source text.
        end: Character offset just past the closing brace.
        slot: The character slot number (1-based).
        attr: The attribute key (e.g. "fn", "mn", "ln", "full_name"),
            or empty string when the token has no attribute (defaults
            to full_name).
        raw: The exact raw text of the token including braces.

    """

    start: int
    end: int
    slot: int
    attr: str
    raw: str


@dataclass(frozen=True)
class Unresolved:
    """An unresolved token found during resolution.

    Attributes:
        token: The token that could not be resolved.
        reason: A human-readable reason describing why resolution
            failed.
        line: The 1-based line number within the text where the token
            appears, or None if line information is unavailable.

    """

    token: Token
    reason: str
    line: int | None = None


def findTokens(text: str) -> list[Token]:
    """Find all character slot tokens in text.

    Scans the text for ``{charN attr}`` patterns where ``N`` is a slot
    number and ``attr`` is an optional attribute key. Returns tokens in
    document order.

    Args:
        text: The source text to scan.

    Returns:
        A list of :class:`Token` objects, one per match found.

    """
    tokens: list[Token] = []
    for match in TOKEN_RE.finditer(text):
        slot = int(match.group(1))
        attr = match.group(2) or ""
        tokens.append(
            Token(
                start=match.start(),
                end=match.end(),
                slot=slot,
                attr=attr,
                raw=match.group(0),
            )
        )
    return tokens


def resolveTokens(text: str, project: Any, edition: str | None = None) -> tuple[str, list[Unresolved]]:
    """Resolve all character slot tokens in text.

    Replaces each ``{charN attr}`` token with the corresponding
    attribute value from the character sheet for slot ``N``. If the
    slot has no character assigned, or the attribute is empty/unknown,
    the token is left in place and an :class:`Unresolved` record is
    added.

    Args:
        text: The source text containing tokens.
        project: The project object; its tree and storage are used to
            load the entity sheets.
        edition: Optional edition identifier (unused in this release,
            reserved for per-edition sheets).

    Returns:
        A tuple of ``(resolved_text, unresolved_list)`` where
        ``resolved_text`` has all resolvable tokens replaced and
        ``unresolved_list`` lists each token that could not be
        resolved.

    """
    from umbraedit.umbra.sheet import SheetManager

    storagePath = project.storage.storagePath
    if not storagePath:
        return text, []

    manager = SheetManager(storagePath)
    manager.buildFromProject(project)

    tokens = findTokens(text)
    if not tokens:
        return text, []

    # Process tokens in reverse order so that replacements don't
    # invalidate earlier offsets.
    result = text
    unresolved: list[Unresolved] = []
    for token in sorted(tokens, key=lambda t: t.start, reverse=True):
        row = None
        for candidate in manager.iterEntities():
            slotVal = candidate.attrs.get("slot", "")
            if slotVal.isdigit() and int(slotVal) == token.slot:
                row = candidate
                break

        if row is None:
            # No character assigned to this slot
            line = _lineNumber(text, token.start)
            unresolved.append(
                Unresolved(
                    token=token,
                    reason=f"Slot {token.slot} has no character assigned.",
                    line=line,
                )
            )
            continue

        attrKey = token.attr or "full_name"
        value = row.attrs.get(attrKey, "")

        if not value:
            line = _lineNumber(text, token.start)
            unresolved.append(
                Unresolved(
                    token=token,
                    reason=(f"Slot {token.slot} has no value for attribute '{attrKey}'."),
                    line=line,
                )
            )
            continue

        # Replace the token with its resolved value
        result = result[: token.start] + value + result[token.end :]

    return result, unresolved


def _lineNumber(text: str, offset: int) -> int:
    """Return the 1-based line number of a character offset."""
    return text[:offset].count("\n") + 1


def isKnownAttr(attr: str) -> bool:
    """Return True when ``attr`` is a known attribute key.

    Known keys are the built-in character attributes; custom keys
    starting with ``x_`` are always considered known.
    """
    if not attr:
        return True  # empty attr defaults to full_name
    if attr in KNOWN_ATTRS:
        return True
    return bool(attr.startswith("x_"))


# Variable resolution for {{...}} templates
def findVariables(text: str) -> list[str]:
    """Find all {{variable}} template variables in text.

    Returns a list of variable paths (e.g., "book.title", "format.isbn").
    """
    return VARIABLE_RE.findall(text)


def resolveVariables(
    text: str, project: Any, edition: str | None = None, fmt: str = "paperback"
) -> tuple[str, list[str]]:
    """Resolve all {{variable}} template variables in text.

    Args:
        text: The source text containing variables.
        project: The project object; its storage is used to load metadata.
        edition: Optional edition identifier.
        fmt: The format being built (paperback, hardback, epub, audiobook).

    Returns:
        A tuple of ``(resolved_text, unresolved_list)`` where
        ``resolved_text`` has all resolvable variables replaced and
        ``unresolved_list`` lists each variable that could not be resolved.

    """
    from umbraedit.umbra.metadata import VARIABLE_RE, formatValuesForBuild, loadMetadata
    from umbraedit.umbra.paths import metadataFile

    storagePath = project.storage.storagePath
    if not storagePath:
        return text, []

    metaFile = metadataFile(storagePath)
    if not metaFile.is_file():
        return text, []

    metadata = loadMetadata(storagePath)
    values = formatValuesForBuild(metadata, fmt, edition)

    unresolved: list[str] = []

    def replace(match: re.Match) -> str:
        var_path = match.group(1)
        parts = var_path.split(".")
        if not parts:
            unresolved.append(var_path)
            return match.group(0)

        obj: Any = values
        for part in parts:
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            else:
                unresolved.append(var_path)
                return match.group(0)

        if obj is None:
            unresolved.append(var_path)
            return match.group(0)

        return str(obj)

    result = VARIABLE_RE.sub(replace, text)
    return result, unresolved


def preprocessText(
    text: str, project: Any, edition: str | None = None, fmt: str = "paperback"
) -> tuple[str, list[Unresolved], list[str]]:
    """Preprocess text for export: resolve both {charN} tokens and {{variables}}.

    This is the main entry point for the tokenizer.preprocess hook.
    Runs character token resolution first, then variable resolution.

    Args:
        text: The source text.
        project: The project object.
        edition: Optional edition identifier.
        fmt: The format being built.

    Returns:
        A tuple of ``(resolved_text, unresolved_tokens, unresolved_variables)``.

    """
    # First resolve character tokens
    text, unresolved_tokens = resolveTokens(text, project, edition)

    # Then resolve template variables
    text, unresolved_variables = resolveVariables(text, project, edition, fmt)

    return text, unresolved_tokens, unresolved_variables
