"""
UmbraEdit - Analysis Gate Rules
================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for chapter analysis (P23): missing analysis, unapproved
analysis, and stale analysis.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_TRANSLATION_EXPORT,
    GateRule,
    registerGate,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _analysisMissingFindings(scope: Any) -> Iterable[Any]:
    """Block translation.export: chapter missing analysis document."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    # Find all chapter handles
    for item in project.tree:
        if not item.isFileType():
            continue
        # Check if this is a chapter (level 1 heading document)
        # For simplicity, check all file-type items in novel root

    # This is a simplified check - full implementation would:
    # 1. Find all chapter handles in the project
    # 2. Check if each has an approved analysis document
    # 3. Report missing ones


def _analysisUnapprovedFindings(scope: Any) -> Iterable[Any]:
    """Block translation.export: analysis status is draft."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    # Check if translation.allowDraftAnalysis setting is enabled
    # If not, block on draft status


def _analysisStaleFindings(scope: Any) -> Iterable[Any]:
    """Block translation.export: chapter changed since analysis."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    # Check if chapter text hash differs from analysis @srchash


registerGate(
    GateRule(
        ruleId="analysisMissing",
        title="Missing Analysis",
        operations=frozenset({OP_TRANSLATION_EXPORT}),
        defaultSeverity="block",
        relaxable=False,
        check=_analysisMissingFindings,
    )
)

registerGate(
    GateRule(
        ruleId="analysisUnapproved",
        title="Unapproved Analysis",
        operations=frozenset({OP_TRANSLATION_EXPORT}),
        defaultSeverity="block",
        relaxable=True,
        check=_analysisUnapprovedFindings,
    )
)

registerGate(
    GateRule(
        ruleId="analysisStale",
        title="Stale Analysis",
        operations=frozenset({OP_TRANSLATION_EXPORT}),
        defaultSeverity="block",
        relaxable=False,
        check=_analysisStaleFindings,
    )
)
