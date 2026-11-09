"""
UmbraEdit - Paragraph Unit Merge
=================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Merge logic for paragraph-level document units. Compares two versions
of a document against a common base, producing an aligned set of units
with conflict information where both sides changed the same region.

Qt-free.
"""  # noqa

from __future__ import annotations

import difflib

from dataclasses import dataclass

from umbraedit.umbra.units import Unit, iterUnits


@dataclass(frozen=True)
class Span:
    """A contiguous block of text within a unit.

    Attributes:
        text: The text content.
        start: Start offset within the unit's full text.
        end: End offset (exclusive).

    """

    text: str
    start: int
    end: int


@dataclass(frozen=True)
class UnitChange:
    """A change detected between two versions of a unit.

    Attributes:
        kind: Type of change: "text", "attr", "delete", "insert".
        unit: The unit this change applies to.
        old_text: Original text (for text changes).
        new_text: New text (for text changes).
        field: Attribute key for attribute changes.

    """

    kind: str
    unit: Unit | None
    old_text: str | None = None
    new_text: str | None = None
    field: str | None = None


@dataclass(frozen=True)
class SpanMatch:
    """A matched span between two document versions."""

    start_a: int
    end_a: int
    start_b: int
    end_b: int
    similarity: float


@dataclass(frozen=True)
class Change:
    """A difference between two document versions.

    Attributes:
        kind: Type of change: "text", "attr", "deleteEdit", "move", "docDelete".
        base: Base version unit (if any).
        ours: Our version unit (if any).
        theirs: Their version unit (if any).
        field: Attribute key for attribute changes.

    """

    kind: str
    base: Unit | None
    ours: Unit | None
    theirs: Unit | None
    field: str | None = None


@dataclass(frozen=True)
class MergeResult:
    """Result of merging base, ours, and theirs versions.

    Attributes:
        units: Merged sequence of units (conflicts resolved to ours text).
        conflicts: Unresolved conflicts requiring user choice.
        merged: Auto-merged items for review.

    """

    units: list[Unit]
    conflicts: list[Change]
    merged: list[Change]


def _unit_text(unit: Unit | None) -> str:
    """Return the full text of a unit."""
    if unit is None:
        return ""
    return "\n".join(unit.lines)


def _unit_key(unit: Unit | None) -> str:
    """Return a canonical comparison key for a unit."""
    if unit is None:
        return ""
    return "\n".join(line.strip() for line in unit.lines)


def _text_similarity(a: str, b: str) -> float:
    """Return similarity ratio between two strings (0.0 to 1.0)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def align_units(a_units: list[Unit], b_units: list[Unit]) -> list[tuple[Unit | None, Unit | None]]:
    """Align two lists of units into matched pairs.

    Uses exact text matching first (longest common subsequence on exact
    unit keys), then fuzzy matching for remaining gaps using
    SequenceMatcher similarity >= 0.6.
    """
    if not a_units and not b_units:
        return []

    a_keys = [_unit_key(u) for u in a_units]
    b_keys = [_unit_key(u) for u in b_units]

    n, m = len(a_keys), len(b_keys)

    # Build LCS table
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if a_keys[i] == b_keys[j]:
                dp[i][j] = 1 + dp[i + 1][j + 1]
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])

    # Build match maps: a_index -> b_index and b_index -> a_index
    a_to_b: dict[int, int] = {}
    b_to_a: dict[int, int] = {}
    i, j = 0, 0
    while i < n and j < m:
        if a_keys[i] == b_keys[j]:
            a_to_b[i] = j
            b_to_a[j] = i
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1

    # Build result by walking through both lists
    results: list[tuple[Unit | None, Unit | None]] = []
    i, j = 0, 0
    while i < n or j < m:
        if i < n and j < m and i in a_to_b and a_to_b[i] == j:
            # Matched pair
            results.append((a_units[i], b_units[j]))
            i += 1
            j += 1
        elif i < n and i not in a_to_b:
            # a[i] is not matched to anything
            results.append((a_units[i], None))
            i += 1
        elif j < m and j not in b_to_a:
            # b[j] is not matched to anything
            results.append((None, b_units[j]))
            j += 1
        else:
            # Shouldn't happen with correct LCS, but advance both
            i += 1
            j += 1

    return results


def _diff_units(base_units: list[Unit], ours_units: list[Unit]) -> list[Change]:
    """Compute diff between base and ours units."""
    if not base_units and not ours_units:
        return []

    matcher = _align_texts(base_units, ours_units)
    changes: list[Change] = []

    for i, (b, o) in enumerate(matcher):
        if b is None and o is not None:
            changes.append(
                Change(
                    kind="insert",
                    base=None,
                    ours=o,
                    theirs=None,
                )
            )
        elif b is not None and o is None:
            changes.append(
                Change(
                    kind="delete",
                    base=b,
                    ours=None,
                    theirs=None,
                )
            )
        elif b is not None and o is not None:
            if _unit_text(b) != _unit_text(o):
                changes.append(
                    Change(
                        kind="text",
                        base=b,
                        ours=o,
                        theirs=None,
                    )
                )

    return changes


def _align_texts(a_units: list[Unit], b_units: list[Unit]) -> list[tuple[Unit | None, Unit | None]]:
    """Align text units using difflib on their text keys."""
    a_keys = [_unit_key(u) for u in a_units]
    b_keys = [_unit_key(u) for u in b_units]

    matcher = difflib.SequenceMatcher(None, a_keys, b_keys, autojunk=False)

    result: list[tuple[Unit | None, Unit | None]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                result.append((a_units[i], b_units[j]))
        elif tag == "delete":
            for i in range(i1, i2):
                result.append((a_units[i], None))
        elif tag == "insert":
            for j in range(j1, j2):
                result.append((None, b_units[j]))
        elif tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                a_idx = i1 + k if k < i2 - i1 else None
                b_idx = j1 + k if k < j2 - j1 else None
                if a_idx is not None and b_idx is not None:
                    result.append((a_units[a_idx], b_units[b_idx]))
                elif a_idx is not None:
                    result.append((a_units[a_idx], None))
                elif b_idx is not None:
                    result.append((None, b_units[b_idx]))

    return result


def merge_units(base: str, ours: str, theirs: str) -> MergeResult:
    """Merge three document versions.

    Args:
        base: The common ancestor document text.
        ours: Our version of the document text.
        theirs: Their version of the document text.

    Returns:
        MergeResult with merged units, conflicts, and auto-merged items.

    """
    base_units = list(iterUnits(base))
    ours_units = list(iterUnits(ours))
    theirs_units = list(iterUnits(theirs))

    # Compute diffs from base to each side
    base_ours = _diff_units(base_units, ours_units)
    base_theirs = _diff_units(base_units, theirs_units)

    # Build merged result: start with base, apply changes
    merged_units: list[Unit] = []
    conflicts: list[Change] = []
    merged_auto: list[Change] = []

    bi = 0
    oi = 0
    ti = 0

    while bi < len(base_units) or oi < len(ours_units) or ti < len(theirs_units):
        b_unit = base_units[bi] if bi < len(base_units) else None
        o_unit = ours_units[oi] if oi < len(ours_units) else None
        t_unit = theirs_units[ti] if ti < len(theirs_units) else None

        # Check if all three agree
        if b_unit is not None and o_unit is not None and t_unit is not None:
            if _unit_text(b_unit) == _unit_text(o_unit) == _unit_text(t_unit):
                merged_units.append(b_unit)
                bi += 1
                oi += 1
                ti += 1
                continue

        # Handle insertion (only ours or theirs has content)
        if b_unit is None and o_unit is not None and t_unit is not None:
            if _unit_text(o_unit) == _unit_text(t_unit):
                merged_units.append(o_unit)
                oi += 1
                ti += 1
                continue
            if _unit_text(o_unit) == "":
                merged_units.append(t_unit)
                ti += 1
                continue
            if _unit_text(t_unit) == "":
                merged_units.append(o_unit)
                oi += 1
                continue
            # Both added different content - conflict
            conflicts.append(
                Change(
                    kind="text",
                    base=None,
                    ours=o_unit,
                    theirs=t_unit,
                )
            )
            merged_units.append(o_unit)
            oi += 1
            ti += 1
            continue

        # Handle deletion (only ours or theirs is None)
        if b_unit is not None and o_unit is None and t_unit is None:
            # Both deleted - no change
            bi += 1
            oi += 1
            ti += 1
            continue
        if b_unit is not None and o_unit is None and t_unit is not None:
            # Only ours deleted - conflict
            conflicts.append(
                Change(
                    kind="deleteEdit",
                    base=b_unit,
                    ours=None,
                    theirs=t_unit,
                )
            )
            merged_units.append(t_unit)
            bi += 1
            oi += 1
            ti += 1
            continue
        if b_unit is not None and o_unit is not None and t_unit is None:
            # Only theirs deleted - conflict
            conflicts.append(
                Change(
                    kind="deleteEdit",
                    base=b_unit,
                    ours=o_unit,
                    theirs=None,
                )
            )
            merged_units.append(o_unit)
            bi += 1
            oi += 1
            ti += 1
            continue

        # All three present - check for differences
        if b_unit is not None and o_unit is not None and t_unit is not None:
            b_text = _unit_text(b_unit)
            o_text = _unit_text(o_unit)
            t_text = _unit_text(t_unit)

            if b_text == o_text == t_text:
                merged_units.append(b_unit)
            elif o_text == t_text and b_text != o_text:
                merged_units.append(o_unit)
            elif o_text == b_text and t_text != b_text:
                merged_units.append(t_unit)
            elif t_text == b_text and o_text != b_text:
                merged_units.append(o_unit)
            else:
                # All three different - conflict
                conflicts.append(
                    Change(
                        kind="text",
                        base=b_unit,
                        ours=o_unit,
                        theirs=t_unit,
                    )
                )
                merged_units.append(o_unit)

        bi += 1
        oi += 1
        ti += 1

    return MergeResult(
        units=merged_units,
        conflicts=conflicts,
        merged=merged_auto,
    )


def apply_choices(result: MergeResult, choices: dict[int, str]) -> str:
    """Apply user choices to resolve conflicts.

    Args:
        result: The merge result from merge_units.
        choices: Mapping of conflict index to choice ("ours", "theirs",
                 "both").

    Returns:
        Merged text with all conflicts resolved.

    """
    result_units: list[Unit] = []
    conflict_map: dict[int, Change] = {i: c for i, c in enumerate(result.conflicts)}

    for i, unit in enumerate(result.units):
        if i in conflict_map:
            conflict = conflict_map[i]
            choice = choices.get(i, "ours")
            if choice == "ours" and conflict.ours is not None:
                result_units.append(conflict.ours)
            elif choice == "theirs" and conflict.theirs is not None:
                result_units.append(conflict.theirs)
            elif choice == "both" and conflict.ours is not None and conflict.theirs is not None:
                combined_lines = list(conflict.ours.lines) + list(conflict.theirs.lines)
                result_units.append(
                    Unit(
                        kind=conflict.ours.kind,
                        lines=combined_lines,
                        startLine=conflict.ours.startLine,
                    )
                )
            else:
                result_units.append(unit)
        else:
            result_units.append(unit)

    return "\n".join("\n".join(u.lines) if u.lines else "" for u in result_units)


def word_diff(a: str, b: str) -> list[tuple[str, str]]:
    """Word-level diff between two strings.

    Returns list of (op, word) tuples where op is one of:
    "equal", "delete", "insert".
    """
    a_words = a.split()
    b_words = b.split()

    matcher = difflib.SequenceMatcher(None, a_words, b_words, autojunk=False)
    result: list[tuple[str, str]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for w in a_words[i1:i2]:
                result.append(("equal", w))
        elif tag == "delete":
            for w in a_words[i1:i2]:
                result.append(("delete", w))
        elif tag == "insert":
            for w in b_words[j1:j2]:
                result.append(("insert", w))
        elif tag == "replace":
            for w in a_words[i1:i2]:
                result.append(("delete", w))
            for w in b_words[j1:j2]:
                result.append(("insert", w))

    return result
