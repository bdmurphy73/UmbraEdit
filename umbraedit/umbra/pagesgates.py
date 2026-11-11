"""
UmbraEdit - Page Gate Rules
============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for typed pages (P21): required pages, empty fields, order,
and variant availability.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_BUILD_RUN,
    OP_PUBLISH_PACKAGE,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.pages import PageManager

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _pageRequiredFindings(scope: Any) -> Iterable[Finding]:
    """Block: required pages are missing for enabled formats."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    manager = PageManager(storagePath)
    enabled_formats = manager.getPageTypes()  # This returns page types, not formats
    # We need to check metadata for enabled formats
    from umbraedit.umbra.metadata import loadMetadata

    metadata = loadMetadata(storagePath)
    enabled_formats = [fmt for fmt, config in metadata.formats.items() if config.get("enabled", False)]

    manager = PageManager(storagePath)
    all_pages = manager.getAllPages()
    page_types_by_matter = {}
    for page in all_pages:
        page_type_id = page.get("pageType")
        matter = page.get("matter")
        if page_type_id and matter:
            if matter not in page_types_by_matter:
                page_types_by_matter[matter] = set()
            page_types_by_matter[matter].add(page_type_id)

    for fmt in enabled_formats:
        from umbraedit.umbra.metadata import DEFAULT_FORMATS

        metadata.formats.get(fmt, DEFAULT_FORMATS.get(fmt, {}))
        # Check required pages for this format
        manager = PageManager(storagePath)
        page_types = manager.getPageTypes()
        for page_type in page_types.values():
            if fmt in page_type.requiredFor:
                # Check if this page type exists in the project
                handle = f"page-{page_type.id}"
                if handle not in manager._pages:
                    yield Finding(
                        ruleId="pageRequired",
                        severity="block",
                        message=f"Required page '{page_type.label}' is missing for format '{fmt}'",
                        fix=f"Create the required page '{page_type.label}' in the Page tab",
                        handle="pages",
                        detail={
                            "pageType": page_type.id,
                            "format": fmt,
                        },
                    )


def _pageFieldEmptyFindings(scope: Any) -> Iterable[Finding]:
    """Block: required fields are empty in pages."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    from umbraedit.umbra.metadata import loadMetadata
    metadata = loadMetadata(storagePath)
    enabled_formats = [fmt for fmt, config in metadata.formats.items() if config.get("enabled", False)]

    manager = PageManager(storagePath)
    for page in manager._pages.values():
        page_type_id = page.get("pageType")
        if not page_type_id:
            continue

        manager = PageManager(storagePath)
        page_type = manager.getPageType(page_type_id)
        if not page_type:
            continue

        # Check each enabled format for this page
        for fmt in enabled_formats:
            if fmt in page_type.requiredFor:
                fields = page_type.getEffectiveFields(fmt)
                page_fields = manager._pages.get(page.get("handle", ""), {}).get("fields", {})
                for field in fields:
                    if not field.optional and not page_fields.get(field.key):
                        yield Finding(
                            ruleId="pageFieldEmpty",
                            severity="block",
                            message=f"Required field '{field.label}' is empty in page '{page_type.label}' for format '{fmt}'",
                            fix=f"Fill in the '{field.label}' field in the Page form",
                            handle="pages",
                            detail={
                                "pageType": page_type_id,
                                "field": field.key,
                                "format": fmt,
                            },
                        )


def _pageOrderFindings(scope: Any) -> Iterable[Finding]:
    """Advisory: page order differs from type order."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    manager = PageManager(storagePath)
    pages_by_matter = {}
    for handle, page in manager._pages.items():
        matter = page.get("matter", "front")
        if matter not in pages_by_matter:
            pages_by_matter[matter] = []
        pages_by_matter[matter].append((page.get("order", 0), handle, page.get("pageType", "")))

    for matter, pages in pages_by_matter.items():
        pages.sort(key=lambda x: x[0])
        for i, (order, handle, page_type_id) in enumerate(pages):
            expected_order = i * 10
            if order != expected_order:
                page_type = PageManager(project.storage.storagePath).getPageType(page_type_id)
                label = page_type.label if page_type else page_type_id
                yield Finding(
                    ruleId="pageOrder",
                    severity="advisory",
                    message=f"Page '{label}' in {matter} matter has order {order}, expected {expected_order}",
                    fix="Reorder pages in the Page tab to match the standard order",
                    handle="pages",
                    detail={
                        "pageType": page_type_id,
                        "matter": matter,
                        "currentOrder": order,
                        "expectedOrder": expected_order,
                    },
                )


def _pageVariantMissingFindings(scope: Any) -> Iterable[Finding]:
    """Block: required page has no variant for enabled format."""
    project = scope.project
    if not project:
        return
    storagePath = project.storage.storagePath
    if not storagePath:
        return

    from umbraedit.umbra.metadata import loadMetadata
    metadata = loadMetadata(storagePath)
    enabled_formats = [fmt for fmt, config in metadata.formats.items() if config.get("enabled", False)]

    manager = PageManager(storagePath)
    page_types = manager.getPageTypes()

    for page_type in page_types.values():
        for fmt in enabled_formats:
            if fmt in page_type.requiredFor:
                variant = page_type.getVariant(fmt)
                if variant is None or not variant.enabled:
                    yield Finding(
                        ruleId="pageVariantMissing",
                        severity="block",
                        message=f"Page '{page_type.label}' has no enabled variant for format '{fmt}'",
                        fix=f"Add a variant for format '{fmt}' to page type '{page_type.id}' or disable the format",
                        handle="pages",
                        detail={
                            "pageType": page_type.id,
                            "format": fmt,
                        },
                    )


registerGate(
    GateRule(
        ruleId="pageRequired",
        title="Missing Required Page",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_pageRequiredFindings,
    )
)

registerGate(
    GateRule(
        ruleId="pageFieldEmpty",
        title="Empty Page Field",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_pageFieldEmptyFindings,
    )
)

registerGate(
    GateRule(
        ruleId="pageOrder",
        title="Page Order",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_pageOrderFindings,
    )
)

registerGate(
    GateRule(
        ruleId="pageVariantMissing",
        title="Missing Page Variant",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="block",
        relaxable=False,
        check=_pageVariantMissingFindings,
    )
)
