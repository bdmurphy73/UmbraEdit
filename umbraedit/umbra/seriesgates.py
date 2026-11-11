"""
UmbraEdit - Series Bible Gate Rules
====================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for the Series Bible (P26): missing bible, bible changed.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_AUDIO_CHAPTER,
    OP_BUILD_RUN,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.series import (
    checkBibleChanged,
    getBiblePath,
    loadSeries,
    markBibleSeen,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _bibleMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block: series.json points to a missing bible project."""
    project = scope.project
    if not project:
        return
    storage_path = project.storage.storagePath
    if not storage_path:
        return

    series = loadSeries(storage_path)
    if not series.is_valid():
        return  # No series configured, not an error

    bible_path = getBiblePath(storage_path, series)
    if not bible_path or not bible_path.exists():
        yield Finding(
            ruleId="bibleMissing",
            severity="block",
            message=f"Series bible not found at '{series.bible}'",
            fix="Restore the bible project or update series.json with the correct path",
            handle="series",
            detail={"series": series.series, "biblePath": series.bible},
        )


def _bibleChangedFindings(scope: Any) -> Iterable[Finding]:
    """Advisory: bible changed since last build."""
    project = scope.project
    if not project:
        return
    storage_path = project.storage.storagePath
    if not storage_path:
        return

    series = loadSeries(storage_path)
    if not series.is_valid():
        return  # No series configured

    bible_path = getBiblePath(storage_path, series)
    if not bible_path or not bible_path.exists():
        return  # Missing bible handled by bibleMissing gate

    # Check if bible changed since last build
    changed, current_counter = checkBibleChanged(storage_path, bible_path)
    if not changed:
        return

    # Update the seen counter so this advisory fires once per bible change
    markBibleSeen(storage_path, bible_path)

    yield Finding(
        ruleId="bibleChanged",
        severity="advisory",
        message=f"Series bible '{series.series}' has changed since last build",
        fix="Review the bible changes and rebuild if needed",
        handle="series",
        detail={
            "series": series.series,
            "biblePath": series.bible,
            "changeCounter": current_counter,
        },
    )


def _seriesTagShadowFindings(scope: Any) -> Iterable[Finding]:
    """Advisory: a tag is defined in both book and bible (book wins)."""
    project = scope.project
    if not project:
        return
    storage_path = project.storage.storagePath
    if not storage_path:
        return

    series = loadSeries(storage_path)
    if not series.is_valid():
        return

    bible_path = getBiblePath(storage_path, series)
    if not bible_path or not bible_path.exists():
        return

    # Get all bible entity tags
    from umbraedit.umbra.sheet import SheetManager

    bible_sheet = SheetManager(bible_path / "umbra")
    bible_sheet.buildFromProject(str(bible_path))
    bible_tags = {e.tag for e in bible_sheet.iterEntities()}

    # Get all book entity tags
    book_sheet = SheetManager(storage_path / "umbra")
    book_sheet.buildFromProject(str(storage_path))
    book_tags = {e.tag for e in book_sheet.iterEntities()}

    # Find shadows (tags in both)
    for tag in bible_tags & book_tags:
        yield Finding(
            ruleId="seriesTagShadow",
            severity="advisory",
            message=f"Tag '{tag}' is defined in both book and series bible (book version takes precedence)",
            fix="Remove the book entry to use the bible version, or keep it to override",
            handle="series",
            detail={"tag": tag, "series": series.series},
        )


registerGate(
    GateRule(
        ruleId="bibleMissing",
        title="Series Bible Missing",
        operations=frozenset({OP_BUILD_RUN, OP_AUDIO_CHAPTER}),
        defaultSeverity="block",
        relaxable=False,
        check=_bibleMissingFindings,
    )
)

registerGate(
    GateRule(
        ruleId="bibleChanged",
        title="Series Bible Changed",
        operations=frozenset({OP_BUILD_RUN, OP_AUDIO_CHAPTER}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_bibleChangedFindings,
    )
)

registerGate(
    GateRule(
        ruleId="seriesTagShadow",
        title="Series Tag Shadow",
        operations=frozenset({OP_BUILD_RUN, OP_AUDIO_CHAPTER}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_seriesTagShadowFindings,
    )
)
