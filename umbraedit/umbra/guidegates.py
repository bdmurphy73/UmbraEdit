"""
UmbraEdit - Guide Gate Rules
============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for the Translation Guide (P22): misplaced guide keywords,
missing chapter references, and duplicate analysis documents.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.constants import nwItemClass
from umbraedit.umbra.gates import (
    OP_BUILD_RUN,
    Finding,
    GateRule,
    registerGate,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _guideKeywordMisplacedFindings(scope: Any) -> Iterable[Finding]:
    """Block: guide keywords used outside the Guide root."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return
    contentPath = project.storage.contentPath
    if not contentPath:
        return

    for item in project.tree:
        if not item.isFileType():
            continue
        if item.itemClass == nwItemClass.GUIDE:
            continue  # Guide root is allowed

        docFile = contentPath / f"{item.itemHandle}.md"
        if not docFile.is_file():
            continue

        try:
            text = docFile.read_text(encoding="utf-8")
        except Exception:
            continue

        # Check for guide keywords in the document
        for line_num, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("@"):
                continue
            keyword = stripped.split(":")[0].split()[0]
            if keyword in {"@guide", "@chapter", "@srchash", "@status", "@lang"}:
                yield Finding(
                    ruleId="guideKeywordMisplaced",
                    severity="block",
                    message="Guide keyword '{keyword}' used outside the Translation Guide root",
                    fix="Move this document to the Translation Guide root, or remove the guide keyword",
                    handle=item.itemHandle,
                    line=line_num,
                    detail={"keyword": keyword},
                )


def _analysisChapterMissingFindings(scope: Any) -> Iterable[Finding]:
    """Advisory: @chapter points to a handle that no longer exists."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return
    contentPath = project.storage.contentPath
    if not contentPath:
        return

    for item in project.tree:
        if not item.isFileType():
            continue
        if item.itemClass != nwItemClass.GUIDE:
            continue

        docFile = contentPath / f"{item.itemHandle}.md"
        if not docFile.is_file():
            continue

        try:
            text = docFile.read_text(encoding="utf-8")
        except Exception:
            continue

        # Find @chapter lines
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("@chapter:"):
                chapter_handle = stripped[9:].strip()
                if chapter_handle and not project.tree.checkExists(chapter_handle):
                    yield Finding(
                        ruleId="analysisChapterMissing",
                        severity="advisory",
                        message=f"Analysis document references missing chapter handle '{chapter_handle}'",
                        fix="Update or remove the @chapter reference",
                        handle=item.itemHandle,
                        detail={"chapterHandle": chapter_handle},
                    )


def _guideDuplicateAnalysisFindings(scope: Any) -> Iterable[Finding]:
    """Block: two analysis documents for one chapter."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return
    contentPath = project.storage.contentPath
    if not contentPath:
        return

    # Map chapter handle to analysis document handles
    chapter_analyses: dict[str, list[str]] = {}

    for item in project.tree:
        if not item.isFileType():
            continue
        if item.itemClass != nwItemClass.GUIDE:
            continue

        docFile = contentPath / f"{item.itemHandle}.md"
        if not docFile.is_file():
            continue

        try:
            text = docFile.read_text(encoding="utf-8")
        except Exception:
            continue

        # Check if this is an analysis document
        kind = None
        chapter_handle = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("@guide:"):
                kind = stripped[7:].strip()
            elif stripped.startswith("@chapter:"):
                chapter_handle = stripped[9:].strip()

        if kind == "analysis" and chapter_handle:
            chapter_analyses.setdefault(chapter_handle, []).append(item.itemHandle)

    # Report duplicates
    for chapter_handle, handles in chapter_analyses.items():
        if len(handles) > 1:
            for handle in handles:
                yield Finding(
                    ruleId="guideDuplicateAnalysis",
                    severity="block",
                    message=f"Multiple analysis documents for chapter '{chapter_handle}'",
                    fix="Keep only one analysis document per chapter",
                    handle=handle,
                    detail={
                        "chapterHandle": chapter_handle,
                        "duplicateHandles": handles,
                    },
                )


registerGate(
    GateRule(
        ruleId="guideKeywordMisplaced",
        title="Misplaced Guide Keyword",
        operations=frozenset({OP_BUILD_RUN}),
        defaultSeverity="block",
        relaxable=False,
        check=_guideKeywordMisplacedFindings,
    )
)

registerGate(
    GateRule(
        ruleId="analysisChapterMissing",
        title="Analysis Chapter Missing",
        operations=frozenset({"translation.export"}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_analysisChapterMissingFindings,
    )
)

registerGate(
    GateRule(
        ruleId="guideDuplicateAnalysis",
        title="Duplicate Analysis",
        operations=frozenset({"translation.export"}),
        defaultSeverity="block",
        relaxable=False,
        check=_guideDuplicateAnalysisFindings,
    )
)
