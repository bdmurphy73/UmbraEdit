"""
UmbraEdit - Translation Gate Rules
===================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for translation export (P25): glossary gaps, etc.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.edition import loadEdition
from umbraedit.umbra.gates import (
    OP_TRANSLATION_EXPORT,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.translate import _check_glossary_gaps

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _translationGlossaryGapFindings(scope: Any) -> Iterable[Finding]:
    """Block translation.export: entity mentioned in chapter has no target form in glossary."""
    project = scope.project
    if not project:
        return
    storage_path = project.storage.storagePath
    if not storage_path:
        return

    edition = loadEdition(storage_path)
    if not edition.source.get("path"):
        return

    # Check the chapter being translated (from scope.options)
    chapter_handle = scope.options.get("chapter", "") if scope.options else ""
    if not chapter_handle:
        return

    # Check for glossary gaps
    gaps = _check_glossary_gaps(storage_path, project, chapter_handle)
    for tag in gaps:
        yield Finding(
            ruleId="translationGlossaryGap",
            severity="block",
            message=f"Speaker '{tag}' has no target form in glossary",
            fix=f"Add a target form for '{tag}' in the edition entity sheet, or mark 'keep as written'",
            handle=chapter_handle,
            detail={"speaker": tag, "edition": edition.editionId},
        )


registerGate(
    GateRule(
        ruleId="translationGlossaryGap",
        title="Translation Glossary Gap",
        operations=frozenset({OP_TRANSLATION_EXPORT}),
        defaultSeverity="block",
        relaxable=True,  # Author can mark "keep as written"
        check=_translationGlossaryGapFindings,
    )
)

