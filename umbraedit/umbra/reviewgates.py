"""
UmbraEdit - Review Annotation Gate Rules
=========================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rule for review annotations (P29): open review annotations.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.annotations import load_annotations
from umbraedit.umbra.gates import (
    OP_PUBLISH_PACKAGE,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.settings import umbraSettings

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _reviewOpenFindings(scope: Any) -> Iterable[Finding]:
    """Advisory/Block: project has open review annotations."""
    project = scope.project
    if not project:
        return
    storage_path = project.storage.storagePath
    if not storage_path:
        return

    # Check if blocking is enabled via setting
    block_on_open = umbraSettings.getBool("review.blockPublishOnOpen", False)
    severity = "block" if block_on_open else "advisory"

    annotations = load_annotations(storage_path)
    open_annotations = [a for a in annotations if a.status == "open"]

    if not open_annotations:
        return

    for ann in open_annotations:
        yield Finding(
            ruleId="reviewOpen",
            severity=severity,
            message=(
                f"Open review annotation '{ann.id}' in document {ann.handle}"
            ),
            fix="Resolve or delete the annotation in the Review dock",
            handle=ann.handle,
            detail={
                "annotationId": ann.id,
                "annotationKind": ann.kind,
                "annotationStatus": ann.status,
            },
        )


registerGate(
    GateRule(
        ruleId="reviewOpen",
        title="Open Review Annotations",
        operations=frozenset({OP_PUBLISH_PACKAGE}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_reviewOpenFindings,
    )
)
