"""
UmbraEdit - Cover Gate Rules
============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for book covers (P20): missing covers, invalid covers,
size mismatches, and edition covers. Imported at the end of
`umbra.gates` so the rules are always registered.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.covers import CoverStore
from umbraedit.umbra.gates import (
    OP_AUDIO_BOOK,
    OP_BUILD_RUN,
    OP_PUBLISH_HANDOFF,
    OP_PUBLISH_PACKAGE,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.metadata import loadMetadata

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _coverMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block: required covers are missing for enabled formats."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    loadMetadata(storagePath)
    store = CoverStore(storagePath)

    enabled_formats = store.getEnabledFormats()
    for fmt in enabled_formats:
        cover = store.getCover(fmt)
        reqs = store.getRequirements(fmt)
        if not cover and reqs.get("required", False):
            # Determine which operations this format affects
            operations = {OP_BUILD_RUN}
            if fmt == "epub":
                operations.add(OP_PUBLISH_PACKAGE)
                operations.add(OP_PUBLISH_HANDOFF)
            elif fmt == "audiobook":
                operations.add(OP_AUDIO_BOOK)
                operations.add(OP_PUBLISH_PACKAGE)
                operations.add(OP_PUBLISH_HANDOFF)
            else:
                operations.add(OP_PUBLISH_PACKAGE)
                operations.add(OP_PUBLISH_HANDOFF)

            yield Finding(
                ruleId="coverMissing",
                severity="block",
                message=f"Cover missing for format '{fmt}'",
                fix=f"Add a cover image for format '{fmt}' in the Book tab",
                handle="covers",
                detail={"format": fmt},
            )


def _coverInvalidFindings(scope: Any) -> Iterable[Finding]:
    """Block: covers fail validation (wrong type, size, aspect, etc.)."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    store = CoverStore(storagePath)
    enabled_formats = store.getEnabledFormats()

    for fmt in enabled_formats:
        findings = store.validateCover(fmt)
        for finding in findings:
            if finding.ruleId == "coverInvalid":
                yield Finding(
                    ruleId="coverInvalid",
                    severity="block",
                    message=finding.message,
                    fix=finding.fix,
                    handle="covers",
                    detail=finding.detail or {},
                )


def _coverSizeMismatchFindings(scope: Any) -> Iterable[Finding]:
    """Block publish: print cover size mismatch."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    store = CoverStore(storagePath)
    enabled_formats = store.getEnabledFormats()

    for fmt in enabled_formats:
        findings = store.validateCover(fmt)
        for finding in findings:
            if finding.ruleId == "coverSizeMismatch":
                yield Finding(
                    ruleId="coverSizeMismatch",
                    severity="block",
                    message=finding.message,
                    fix=finding.fix,
                    handle="covers",
                    detail=finding.detail or {},
                )


def _coverEditionMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block: edition project missing its own cover."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    loadMetadata(storagePath)
    # Check if this is an edition project
    edition_file = storagePath / "umbra" / "edition.json"
    if not edition_file.is_file():
        return  # Not an edition project

    store = CoverStore(storagePath)
    enabled_formats = store.getEnabledFormats()

    for fmt in enabled_formats:
        cover = store.getCover(fmt)
        reqs = store.getRequirements(fmt)
        if not cover and reqs.get("required", False):
            yield Finding(
                ruleId="coverEditionMissing",
                severity="block",
                message=f"Edition project missing cover for format '{fmt}'",
                fix=f"Add a cover for format '{fmt}' or use 'Use source cover' command",
                handle="covers",
                detail={"format": fmt, "edition": True},
            )


registerGate(
    GateRule(
        ruleId="coverMissing",
        title="Missing Cover",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE, OP_PUBLISH_HANDOFF, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_coverMissingFindings,
    )
)

registerGate(
    GateRule(
        ruleId="coverInvalid",
        title="Invalid Cover",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE, OP_PUBLISH_HANDOFF, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_coverInvalidFindings,
    )
)

registerGate(
    GateRule(
        ruleId="coverSizeMismatch",
        title="Cover Size Mismatch",
        operations=frozenset({OP_PUBLISH_PACKAGE, OP_PUBLISH_HANDOFF}),
        defaultSeverity="block",
        relaxable=False,
        check=_coverSizeMismatchFindings,
    )
)

registerGate(
    GateRule(
        ruleId="coverEditionMissing",
        title="Edition Cover Missing",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE, OP_PUBLISH_HANDOFF, OP_AUDIO_BOOK}),
        defaultSeverity="block",
        relaxable=False,
        check=_coverEditionMissingFindings,
    )
)
