"""
UmbraEdit - Ingest Gate Rules
==============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for DOCX ingest (P27): no headings, empty scenes,
unknown styles, lost features, image failures, unmapped footnotes.
"""  # noqa

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_IMPORT_COMMIT,
    Finding,
    GateRule,
    registerGate,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Gate rule IDs
RULE_NO_HEADINGS = "ingestNoHeadings"
RULE_EMPTY_SCENE = "ingestEmptyScene"
RULE_UNKNOWN_STYLE = "ingestUnknownStyle"
RULE_LOST_FEATURE = "ingestLostFeature"
RULE_IMAGE_FAILED = "ingestImageFailed"
RULE_FOOTNOTE_UNMAPPED = "ingestFootnoteUnmapped"


def _ingestNoHeadingsFindings(scope: Any) -> Iterable[Finding]:
    """Block import.commit: no chapter headings found in the document."""
    # Check the import plan for chapters
    plan = scope.options.get("importPlan")
    if not plan:
        return

    documents = plan.get("documents", [])
    has_chapter = any(d.get("kind") == "chapter" for d in documents)

    if not has_chapter:
        yield Finding(
            ruleId=RULE_NO_HEADINGS,
            severity="block",
            message="No chapter headings found in the document",
            fix="Ensure the DOCX uses Heading styles or contains 'Chapter N' headings",
            handle="import",
            detail={"documentCount": len(documents)},
        )


def _ingestEmptySceneFindings(scope: Any) -> Iterable[Finding]:
    """Block import.commit: a scene has no content."""
    plan = scope.options.get("importPlan")
    if not plan:
        return

    documents = plan.get("documents", [])
    for doc in documents:
        if doc.get("kind") == "scene" and not doc.get("text", "").strip():
            yield Finding(
                ruleId=RULE_EMPTY_SCENE,
                severity="block",
                message=f"Scene '{doc.get('planId')}' has no content",
                fix="Remove empty scene or add content before importing",
                handle=doc.get("planId"),
                detail={"planId": doc.get("planId")},
            )


def _ingestUnknownStyleFindings(scope: Any) -> Iterable[Finding]:
    """Advisory: document uses styles not in the known style map."""
    # This would check the pre-pass for unknown styles
    # For now, we'll check the import plan options
    unknown_styles = scope.options.get("unknownStyles", [])
    if unknown_styles:
        yield Finding(
            ruleId=RULE_UNKNOWN_STYLE,
            severity="advisory",
            message=f"Document uses {len(unknown_styles)} unknown style(s)",
            fix="Review the style mapping or add custom styles to the style map",
            handle="import",
            detail={"styles": unknown_styles},
        )


def _ingestLostFeatureFindings(scope: Any) -> Iterable[Finding]:
    """Block import.commit: content that cannot be represented (tables, text boxes, etc.)."""
    lost_features = scope.options.get("lostFeatures", [])
    for feature in lost_features:
        yield Finding(
            ruleId=RULE_LOST_FEATURE,
            severity="block",
            message=f"Unsupported content: {feature['type']} at paragraph {feature['paragraph']}",
            fix=f"Remove or convert {feature['type']} before importing",
            handle="import",
            line=feature.get("paragraph"),
            detail={"featureType": feature["type"], "paragraph": feature.get("paragraph")},
        )


def _ingestImageFailedFindings(scope: Any) -> Iterable[Finding]:
    """Block import.commit: an image could not be extracted."""
    failed_images = scope.options.get("failedImages", [])
    for img in failed_images:
        yield Finding(
            ruleId=RULE_IMAGE_FAILED,
            severity="block",
            message=f"Failed to extract image: {img.get('filename', 'unknown')}",
            fix="Ensure the image is embedded in the DOCX and not linked externally",
            handle="import",
            detail={"filename": img.get("filename"), "error": img.get("error")},
        )


def _ingestFootnoteUnmappedFindings(scope: Any) -> Iterable[Finding]:
    """Block import.commit: a footnote could not be mapped to content."""
    unmapped = scope.options.get("unmappedFootnotes", [])
    for fn in unmapped:
        yield Finding(
            ruleId=RULE_FOOTNOTE_UNMAPPED,
            severity="block",
            message=f"Footnote {fn.get('id')} could not be mapped to any paragraph",
            fix="Ensure footnotes have valid references in the document body",
            handle="import",
            detail={"footnoteId": fn.get("id")},
        )


registerGate(
    GateRule(
        ruleId=RULE_NO_HEADINGS,
        title="Import: No Chapter Headings",
        operations=frozenset({OP_IMPORT_COMMIT}),
        defaultSeverity="block",
        relaxable=False,
        check=_ingestNoHeadingsFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_EMPTY_SCENE,
        title="Import: Empty Scene",
        operations=frozenset({OP_IMPORT_COMMIT}),
        defaultSeverity="block",
        relaxable=False,
        check=_ingestEmptySceneFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_UNKNOWN_STYLE,
        title="Import: Unknown Style",
        operations=frozenset({OP_IMPORT_COMMIT}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_ingestUnknownStyleFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_LOST_FEATURE,
        title="Import: Lost Feature",
        operations=frozenset({OP_IMPORT_COMMIT}),
        defaultSeverity="block",
        relaxable=False,
        check=_ingestLostFeatureFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_IMAGE_FAILED,
        title="Import: Image Failed",
        operations=frozenset({OP_IMPORT_COMMIT}),
        defaultSeverity="block",
        relaxable=False,
        check=_ingestImageFailedFindings,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_FOOTNOTE_UNMAPPED,
        title="Import: Unmapped Footnote",
        operations=frozenset({OP_IMPORT_COMMIT}),
        defaultSeverity="block",
        relaxable=False,
        check=_ingestFootnoteUnmappedFindings,
    )
)