"""
UmbraEdit - Edition Gate Rules
==============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for editions (P24): stale editions, pending metadata,
missing tags, missing covers, and missing source project.
"""  # noqa

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.constants import nwItemClass
from umbraedit.umbra.covers import CoverStore
from umbraedit.umbra.edition import EditionDoc, loadEdition, getEditionStatus
from umbraedit.umbra.gates import (
    OP_AUDIO_CHAPTER,
    OP_BUILD_RUN,
    OP_PUBLISH_PACKAGE,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.metadata import loadMetadata
from umbraedit.umbra.sheet import SheetManager

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _editionStaleFindings(scope: Any) -> Iterable[Finding]:
    """Advisory: edition has stale documents."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    edition = loadEdition(storagePath)
    if not edition.source.get("path"):
        return

    # Check each document in the edition
    for handle, doc in edition.docs.items():
        if doc.status == "stale":
            yield Finding(
                ruleId="editionStale",
                severity="advisory",
                message=f"Document '{handle}' in edition is stale",
                fix="Re-translate the document to update it",
                handle=handle,
                detail={
                    "editionId": edition.editionId,
                    "documentHandle": handle,
                    "baseTextHash": doc.baseTextHash,
                },
            )


def _editionMetadataPendingFindings(scope: Any) -> Iterable[Finding]:
    """Block publish/build for EPUB: translatable metadata still pending."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    edition = loadEdition(storagePath)
    if not edition.pending:
        return

    # Check if this is an EPUB build or publish
    operation = scope.operation
    if operation in {"publish.package", "build.run"}:
        # For publish, always check. For build, only if EPUB is target
        if operation == "publish.package" or "epub" in scope.options.get("formats", []):
            for key in edition.pending:
                yield Finding(
                    ruleId="editionMetadataPending",
                    severity="block",
                    message=f"Metadata '{key}' still needs translation",
                    fix=f"Translate '{key}' in the edition metadata",
                    handle="edition",
                    detail={"pendingKey": key, "editionId": edition.editionId},
                )


def _editionTagMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block audio.chapter: a speaker tag used in the edition has no note."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    editionPath = Path(scope.project.storage.storagePath)
    edition = loadEdition(storagePath)

    sheet = SheetManager(editionPath)
    sheet.buildFromProject(scope.project)  # type: ignore

    # Get all speaker tags used in edition documents
    from umbraedit.umbra.units import iterUnits, UnitKind

    contentPath = project.storage.contentPath
    if not contentPath:
        return

    for item in scope.project.tree:
        if not item.isFileType():
            continue
        handle = item.itemHandle
        docFile = contentPath / f"{handle}.md"
        if not docFile.is_file():
            continue

        text = docFile.read_text(encoding="utf-8")
        for unit in iterUnits(text):
            # Check if this is a dialogue unit (has voice data and is a paragraph)
            if unit.voice and unit.kind == UnitKind.PARAGRAPH:
                speaker = unit.voice.spk
                if speaker:
                    entity = sheet.getEntity(speaker)
                    if not entity:
                        yield Finding(
                            ruleId="editionTagMissing",
                            severity="block",
                            message=f"Speaker tag '{speaker}' has no entity note in edition",
                            fix=f"Create an entity note for '{speaker}' in the edition",
                            handle=handle,
                            line=unit.startLine,
                            detail={"speaker": speaker, "edition": True},
                        )


def _editionCoverMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block: edition missing required cover for enabled format."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    editionPath = Path(storagePath)
    edition = loadEdition(storagePath)
    coverStore = CoverStore(storagePath)

    enabledFormats = coverStore.getEnabledFormats()
    for fmt in enabledFormats:
        cover = coverStore.getCover(fmt)
        if not cover:
            reqs = coverStore.getRequirements(fmt)
            if reqs.get("required", False):
                yield Finding(
                    ruleId="coverEditionMissing",
                    severity="block",
                    message=f"Edition missing cover for format '{fmt}'",
                    fix=f"Add a cover for format '{fmt}' in the edition",
                    handle="edition",
                    detail={"format": fmt, "editionId": edition.editionId},
                )


def _editionSourceMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block: edition's source project path cannot be opened."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    edition = loadEdition(storagePath)
    if not edition.source.get("path"):
        return

    sourcePath = editionPath.parent / edition.source["path"]
    if not sourcePath.exists():
        yield Finding(
            ruleId="editionSourceMissing",
            severity="block",
            message=f"Edition source project not found at '{edition.source['path']}'",
            fix="Restore the source project or update the edition source path",
            handle="edition",
            detail={"sourcePath": edition.source["path"]},
        )


registerGate(
    GateRule(
        ruleId="editionStale",
        title="Edition Stale",
        operations=frozenset({"build.run", "publish.package"}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_editionStaleFindings,
    )
)

registerGate(
    GateRule(
        ruleId="editionMetadataPending",
        title="Edition Metadata Pending",
        operations=frozenset({"publish.package", "build.run"}),
        defaultSeverity="block",
        relaxable=False,
        check=_editionMetadataPendingFindings,
    )
)

registerGate(
    GateRule(
        ruleId="editionTagMissing",
        title="Edition Tag Missing",
        operations=frozenset({"audio.chapter"}),
        defaultSeverity="block",
        relaxable=False,
        check=_editionTagMissingFindings,
    )
)

registerGate(
    GateRule(
        ruleId="editionSourceMissing",
        title="Edition Source Missing",
        operations=frozenset({
            "build.run",
            "publish.package",
            "audio.chapter",
            "audio.book",
            "translation.export",
        }),
        defaultSeverity="block",
        relaxable=False,
        check=_editionSourceMissingFindings,
    )
)